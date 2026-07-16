from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db, get_connection
from datetime import datetime, timedelta
import time
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="指数基金买入推荐", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 简易缓存
_cache = {"data": None, "time": 0, "date": ""}
CACHE_TTL = 300  # 5分钟


@app.on_event("startup")
def startup():
    init_db()
    # 启动时检查数据是否过期，若过期后台自动刷新
    import threading

    def _auto_refresh_if_stale():
        conn = None
        try:
            conn = get_connection()
            row = conn.execute("SELECT MAX(date) FROM fund_signal").fetchone()
            latest = row[0] if row and row[0] else None
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            need_refresh = False
            if latest is None or latest < yesterday:
                need_refresh = True
                reason = f"信号日期过期(最新: {latest})"
            else:
                fund_count = conn.execute(
                    "SELECT COUNT(*) FROM fund_basic WHERE fund_type LIKE '指数型%' AND name NOT LIKE '%C' AND name NOT LIKE '%C类%' AND name NOT LIKE '%E'"
                ).fetchone()[0]
                signal_count = conn.execute(
                    "SELECT COUNT(*) FROM fund_signal WHERE date=?", (latest,)
                ).fetchone()[0]
                coverage = signal_count / fund_count if fund_count > 0 else 0
                if coverage < 0.8:
                    need_refresh = True
                    reason = f"信号覆盖率仅 {coverage:.0%} ({signal_count}/{fund_count})"
                else:
                    print(f"[启动检查] 数据完整 ({latest}, 覆盖率 {coverage:.0%})，跳过刷新")
                    return

            print(f"[启动检查] {reason}，自动刷新...")
            from engine.top20 import refresh_daily
            refresh_daily()
            print("[启动检查] 刷新完成")
        except Exception as e:
            print(f"[启动检查] 刷新失败: {e}")
        finally:
            if conn:
                conn.close()

    threading.Thread(target=_auto_refresh_if_stale, daemon=True).start()

    # 每日定时刷新：每小时检查一次，发现数据过期自动刷新
    def _daily_scheduler():
        import time as _time
        while True:
            _time.sleep(3600)  # 每小时检查一次
            try:
                conn = get_connection()
                try:
                    row = conn.execute("SELECT MAX(date) FROM fund_signal").fetchone()
                finally:
                    conn.close()
                latest = row[0] if row and row[0] else None
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                if latest is None or latest < yesterday:
                    print(f"[定时刷新] 数据过期(最新: {latest})，开始刷新...")
                    from engine.top20 import refresh_daily
                    refresh_daily()
                    print("[定时刷新] 完成")
            except Exception as e:
                print(f"[定时刷新] 失败: {e}")

    threading.Thread(target=_daily_scheduler, daemon=True).start()


@app.get("/api/top20")
def api_top20(refresh: bool = False):
    """返回今日最值得买入的Top20基金（缓存5分钟）"""
    try:
        global _cache
        today = datetime.now().strftime("%Y-%m-%d")

        # 检查缓存：同一天、未过期、未强制刷新
        if not refresh and _cache["data"] is not None and _cache["date"] == today:
            if time.time() - _cache["time"] < CACHE_TTL:
                return _cache["data"]

        from engine.top20 import compute_top20

        results = compute_top20()

        conn = get_connection()
        row = conn.execute("SELECT MAX(date) FROM fund_nav").fetchone()
        conn.close()
        updated_at = row[0] if row else "未知"

        data = {
            "count": len(results),
            "updated_at": updated_at,
            "results": results,
        }

        # 存入缓存
        _cache = {"data": data, "time": time.time(), "date": today}
        return data
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/admin/refresh")
def api_admin_refresh():
    """手动触发每日数据刷新"""
    from engine.top20 import refresh_daily
    refresh_daily()
    return {"status": "ok", "message": "数据刷新完成"}


@app.get("/api/fund/{code}/nav/{date}")
def api_fund_nav_on_date(code: str, date: str):
    """查询某只基金在指定日期的净值"""
    conn = get_connection()
    row = conn.execute(
        "SELECT unit_nav, daily_return FROM fund_nav WHERE code=? AND date=?",
        (code, date)
    ).fetchone()
    conn.close()
    if not row:
        # 尝试找最近交易日
        conn = get_connection()
        row = conn.execute(
            "SELECT date, unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (code, date)
        ).fetchone()
        conn.close()
        if row:
            return {"code": code, "date": row["date"], "nav": round(float(row["unit_nav"]), 4), "exact": False, "note": f"{date} 无数据，使用最近交易日 {row['date']}"}
        return {"error": f"基金 {code} 在 {date} 及之前均无净值数据"}
    return {"code": code, "date": date, "nav": round(float(row["unit_nav"]), 4), "exact": True}


@app.get("/api/fund/{code}")
def api_fund_detail(code: str):
    """返回单只基金的净值历史、技术指标、评分明细"""
    try:
        conn = get_connection()
        basic = conn.execute(
            "SELECT code, name, fund_type FROM fund_basic WHERE code=?", (code,)
        ).fetchone()
        if not basic:
            return {"error": "基金不存在"}

        nav_rows = conn.execute(
            "SELECT date, unit_nav, acc_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
            (code,)
        ).fetchall()

        signal_rows = conn.execute(
            "SELECT date, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, rsi14, "
            "kdj_k, kdj_d, kdj_j, bb_upper, bb_mid, bb_lower, bb_width, atr14, ma60_slope "
            "FROM fund_signal WHERE code=? ORDER BY date",
            (code,)
        ).fetchall()
        conn.close()

        navs = [{"date": r["date"], "nav": round(float(r["unit_nav"]), 4),
                 "daily_return": round(float(r["daily_return"] or 0), 4)} for r in nav_rows]
        signals = [{"date": r["date"], "ma5": round(float(r["ma5"] or 0), 4),
                    "ma20": round(float(r["ma20"] or 0), 4),
                    "ma60": round(float(r["ma60"] or 0), 4),
                    "ma120": round(float(r["ma120"] or 0), 4),
                    "macd_dif": round(float(r["macd_dif"] or 0), 4),
                    "macd_dea": round(float(r["macd_dea"] or 0), 4),
                    "macd_hist": round(float(r["macd_hist"] or 0), 4),
                    "rsi": round(float(r["rsi14"] or 50), 1),
                    "kdj_k": round(float(r["kdj_k"] or 50), 1),
                    "kdj_d": round(float(r["kdj_d"] or 50), 1),
                    "kdj_j": round(float(r["kdj_j"] or 50), 1),
                    "bb_upper": round(float(r["bb_upper"] or 0), 4),
                    "bb_mid": round(float(r["bb_mid"] or 0), 4),
                    "bb_lower": round(float(r["bb_lower"] or 0), 4),
                    "bb_width": round(float(r["bb_width"] or 0) * 100, 2)}
                   for r in signal_rows]

        # 计算近几期收益
        from engine.indicators import calc_period_return_from_returns
        import pandas as pd
        df_nav = pd.DataFrame(nav_rows, columns=["date", "unit_nav", "acc_nav", "daily_return"])
        df_nav["daily_return"] = pd.to_numeric(df_nav["daily_return"], errors="coerce").fillna(0)
        df_nav["unit_nav"] = pd.to_numeric(df_nav["unit_nav"], errors="coerce")
        returns_series = df_nav["daily_return"]  # keep as Series for .tail()
        rets = {
            "r5d": round(calc_period_return_from_returns(returns_series, 5) * 100, 2),
            "r10d": round(calc_period_return_from_returns(returns_series, 10) * 100, 2),
            "r20d": round(calc_period_return_from_returns(returns_series, 20) * 100, 2),
            "r60d": round(calc_period_return_from_returns(returns_series, 60) * 100, 2),
            "r1y": round(calc_period_return_from_returns(returns_series, 252) * 100, 2),
        }

        # 最新技术指标
        last_sig = signals[-1] if signals else {}

        return {
            "code": basic["code"],
            "name": basic["name"],
            "fund_type": basic["fund_type"],
            "nav_history": navs,
            "signals": signals,  # 全部历史
            "latest": {
                "rsi": last_sig.get("rsi", 50),
                "ma5": last_sig.get("ma5", 0),
                "ma20": last_sig.get("ma20", 0),
                "ma60": last_sig.get("ma60", 0),
                "ma120": last_sig.get("ma120", 0),
                "macd_dif": last_sig.get("macd_dif", 0),
                "macd_dea": last_sig.get("macd_dea", 0),
                "nav": navs[-1]["nav"] if navs else 0,
                "kdj_k": last_sig.get("kdj_k", 50),
                "kdj_d": last_sig.get("kdj_d", 50),
                "kdj_j": last_sig.get("kdj_j", 50),
                "bb_upper": last_sig.get("bb_upper", 0),
                "bb_mid": last_sig.get("bb_mid", 0),
                "bb_lower": last_sig.get("bb_lower", 0),
                "bb_width": last_sig.get("bb_width", 0),
            },
            "returns": rets,
            "record_count": len(navs),
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# 持仓管理 API
# ============================================================

class PortfolioAdd(BaseModel):
    code: str
    buy_date: str          # YYYY-MM-DD
    buy_nav: float
    shares: Optional[float] = 0
    buy_amount: Optional[float] = 0
    notes: Optional[str] = ""
    merge: Optional[bool] = True   # 默认合并到已有持仓


@app.post("/api/portfolio/add")
def api_portfolio_add(body: PortfolioAdd):
    """添加一只持仓（同基金默认合并，自动计算均价）"""
    try:
        conn = get_connection()
        basic = conn.execute("SELECT name FROM fund_basic WHERE code=?", (body.code,)).fetchone()
        if not basic:
            conn.close()
            return {"error": "基金不存在"}
        name = basic["name"]

        # 计算份额：如果 shares 为 0 或未提供，从 buy_amount / buy_nav 推算
        shares = body.shares if body.shares and body.shares > 0 else 0
        buy_amount = body.buy_amount if body.buy_amount else 0
        if shares <= 0 and buy_amount > 0 and body.buy_nav > 0:
            shares = buy_amount / body.buy_nav

        if body.merge:
            # 检查是否已有持仓，有则合并
            existing = conn.execute(
                "SELECT id, buy_amount, shares, buy_date, notes FROM portfolio WHERE code=? AND (status IS NULL OR status='active' OR status='') LIMIT 1",
                (body.code,)
            ).fetchone()
            if existing:
                # 合并：累加金额和份额，保留最早买入日期
                new_amount = float(existing["buy_amount"]) + buy_amount
                new_shares = float(existing["shares"]) + shares
                new_nav = new_amount / new_shares if new_shares > 0 else body.buy_nav
                old_notes = existing["notes"] or ""
                new_batch = f"定投 {body.buy_date} @ {body.buy_nav}"
                if old_notes:
                    new_notes = old_notes + " | " + new_batch
                else:
                    new_notes = new_batch
                conn.execute(
                    "UPDATE portfolio SET buy_amount=?, shares=?, buy_nav=?, notes=? WHERE id=?",
                    (new_amount, new_shares, new_nav, new_notes, existing["id"])
                )
                conn.commit()
                conn.close()
                return {"status": "ok", "message": f"已合并到 {name}（累计投入 ¥{new_amount:.0f}）"}

        conn.execute(
            "INSERT INTO portfolio (code, name, buy_date, buy_nav, shares, buy_amount, notes) VALUES (?,?,?,?,?,?,?)",
            (body.code, name, body.buy_date, body.buy_nav, shares, buy_amount, body.notes)
        )
        conn.commit()
        conn.close()
        return {"status": "ok", "message": f"已添加 {name}"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/portfolio")
def api_portfolio_list():
    """持仓列表 + 实时盈亏 + 卖出信号"""
    from engine.advisor import analyze_portfolio
    return analyze_portfolio()


@app.delete("/api/portfolio/{holding_id}")
def api_portfolio_delete(holding_id: int):
    """删除一笔持仓"""
    conn = get_connection()
    cur = conn.execute("DELETE FROM portfolio WHERE id=?", (holding_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    if deleted == 0:
        return {"error": "持仓不存在"}
    return {"status": "ok", "message": "已删除"}


@app.put("/api/portfolio/{holding_id}")
def api_portfolio_update(holding_id: int, notes: str = ""):
    """更新持仓备注"""
    conn = get_connection()
    conn.execute("UPDATE portfolio SET notes=? WHERE id=?", (notes, holding_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


class SellRequest(BaseModel):
    sell_nav: float
    sell_date: Optional[str] = None  # 默认当天
    sell_pct: Optional[float] = 100  # 卖出比例 1-100，默认100=全部卖出


@app.put("/api/portfolio/{holding_id}/sell")
def api_portfolio_sell(holding_id: int, body: SellRequest):
    """卖出一笔持仓（支持部分卖出：sell_pct<100 时按比例减仓）"""
    try:
        conn = get_connection()
        holding = conn.execute(
            "SELECT code, name, buy_nav, buy_amount, shares, status FROM portfolio WHERE id=?",
            (holding_id,)
        ).fetchone()
        if not holding:
            conn.close()
            return {"error": "持仓不存在"}
        if holding["status"] == "sold":
            conn.close()
            return {"error": "该持仓已卖出"}

        sell_date = body.sell_date or datetime.now().strftime("%Y-%m-%d")
        sell_nav = body.sell_nav
        sell_pct = body.sell_pct if body.sell_pct is not None else 100

        # 验证卖出比例范围
        if sell_pct < 1 or sell_pct > 100:
            conn.close()
            return {"error": "卖出比例需在1-100之间"}

        shares = float(holding["shares"])
        buy_amount = float(holding["buy_amount"])
        buy_nav = float(holding["buy_nav"])

        sell_shares = shares * (sell_pct / 100)
        sell_cost = buy_amount * (sell_pct / 100)  # 按比例分摊成本
        proceeds = sell_nav * sell_shares
        profit = proceeds - sell_cost
        profit_pct = (proceeds / sell_cost - 1) * 100 if sell_cost > 0 else 0

        if sell_pct >= 100:
            # 全部卖出：标记为 sold
            conn.execute(
                "UPDATE portfolio SET status='sold', sell_date=?, sell_nav=? WHERE id=?",
                (sell_date, sell_nav, holding_id)
            )
        else:
            # 部分卖出：减少份额和金额
            remain_shares = shares - sell_shares
            remain_amount = buy_amount - sell_cost
            new_buy_nav = remain_amount / remain_shares if remain_shares > 0 else buy_nav
            conn.execute(
                "UPDATE portfolio SET shares=?, buy_amount=?, buy_nav=?, notes=COALESCE(notes,'') || ? WHERE id=?",
                (round(remain_shares, 2), round(remain_amount, 2), round(new_buy_nav, 4),
                 f" | 部分卖出 {sell_date} @ {sell_nav} ({sell_pct:.0f}%)", holding_id)
            )

        conn.commit()
        conn.close()
        return {
            "status": "ok",
            "code": holding["code"],
            "name": holding["name"],
            "buy_nav": buy_nav,
            "sell_nav": sell_nav,
            "sell_date": sell_date,
            "sell_pct": sell_pct,
            "sell_shares": round(sell_shares, 2),
            "cost": round(sell_cost, 2),
            "proceeds": round(proceeds, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/portfolio/history")
def api_portfolio_history():
    """已卖出的历史持仓记录"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, code, name, buy_date, buy_nav, sell_date, sell_nav,
               shares, buy_amount,
               ROUND(shares * sell_nav, 2) as proceeds,
               ROUND(shares * sell_nav - shares * buy_nav, 2) as profit,
               CASE WHEN buy_amount > 0
                    THEN ROUND((shares * sell_nav - buy_amount) / buy_amount * 100, 2)
                    ELSE ROUND((sell_nav / buy_nav - 1) * 100, 2)
               END as profit_pct
        FROM portfolio WHERE status='sold' ORDER BY sell_date DESC
    """).fetchall()
    conn.close()

    history = []
    for r in rows:
        h = dict(r)
        total_buy = float(r["buy_nav"]) * float(r["shares"])
        total_sell = float(r["sell_nav"]) * float(r["shares"])
        h["total_cost"] = round(total_buy, 2)
        h["total_proceeds"] = round(total_sell, 2)
        h["total_profit"] = round(total_sell - total_buy, 2)
        history.append(h)

    return {"status": "ok", "count": len(history), "history": history}


@app.get("/api/portfolio/analysis")
def api_portfolio_analysis():
    """持仓组合分析"""
    from engine.advisor import analyze_portfolio
    return analyze_portfolio()


@app.get("/api/fund/{code}/advice")
def api_fund_advice(code: str):
    """单只基金的买卖建议（含持仓上下文）"""
    from engine.advisor import get_buy_advice, get_sell_signals

    # 查询是否已持有，获取买入成本用于准确的卖出信号
    conn = get_connection()
    holding = conn.execute(
        "SELECT buy_nav, buy_date FROM portfolio WHERE code=? AND (status IS NULL OR status='active' OR status='') LIMIT 1",
        (code,)
    ).fetchone()
    conn.close()

    buy = get_buy_advice(code)
    if "error" in buy:
        return buy

    buy_nav = float(holding["buy_nav"]) if holding else None
    buy_date = holding["buy_date"] if holding else None
    sell = get_sell_signals(code, buy_nav=buy_nav, buy_date=buy_date)
    return {"buy": buy, "sell": sell}


@app.get("/api/portfolio/risk")
def api_portfolio_risk():
    """组合风险分析（详细版）"""
    from engine.advisor import analyze_portfolio
    return analyze_portfolio()


@app.get("/api/fund/{code}/technicals")
def api_fund_technicals(code: str):
    """技术指标仪表盘：RSI/MACD/KDJ/布林带/均线 一览"""
    conn = get_connection()
    basic = conn.execute(
        "SELECT name, fund_type FROM fund_basic WHERE code=?", (code,)
    ).fetchone()
    sig_row = conn.execute(
        "SELECT * FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()
    # 获取前一日信号用于对比
    sig_prev = conn.execute(
        "SELECT * FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1 OFFSET 1", (code,)
    ).fetchone()
    conn.close()

    if not basic:
        return {"error": "基金不存在"}
    if not sig_row:
        return {"error": "暂无技术指标数据"}

    def _safe_float(val, default=0):
        return round(float(val or default), 4)

    def _trend(curr, prev, key):
        """判断指标方向"""
        c = float(curr.get(key, 0) or 0)
        if prev is None:
            return "flat"
        p = float(prev.get(key, 0) or 0)
        if p == 0:
            return "flat"
        if c > p * 1.02:
            return "up"
        elif c < p * 0.98:
            return "down"
        return "flat"

    current = dict(sig_row)
    prev_dict = dict(sig_prev) if sig_prev else None
    rsi = float(current.get("rsi14", 50) or 50)
    dif = _safe_float(current.get("macd_dif"))
    dea = _safe_float(current.get("macd_dea"))
    hist = _safe_float(current.get("macd_hist"))
    kdj_k = float(current.get("kdj_k", 50) or 50)
    kdj_d = float(current.get("kdj_d", 50) or 50)
    kdj_j = float(current.get("kdj_j", 50) or 50)

    return {
        "code": code,
        "name": basic["name"],
        "technicals": {
            "rsi": {
                "value": round(rsi, 1),
                "zone": "超买" if rsi > 70 else "超卖" if rsi < 30 else "中性",
                "trend": _trend(current, prev_dict, "rsi14"),
            },
            "macd": {
                "dif": dif, "dea": dea, "hist": hist,
                "signal": "金叉" if dif > dea else "死叉",
                "hist_direction": "up" if hist > 0 else "down",
                "trend": _trend(current, prev_dict, "macd_dif"),
            },
            "kdj": {
                "k": round(kdj_k, 1), "d": round(kdj_d, 1), "j": round(kdj_j, 1),
                "zone": "超买" if kdj_j > 100 else "超卖" if kdj_j < 0 else "中性",
                "signal": "金叉" if kdj_k > kdj_d else "死叉",
            },
            "bollinger": {
                "upper": _safe_float(current.get("bb_upper")),
                "mid": _safe_float(current.get("bb_mid")),
                "lower": _safe_float(current.get("bb_lower")),
                "width": round(float(current.get("bb_width", 0) or 0) * 100, 2),
            },
            "ma": {
                "ma5": _safe_float(current.get("ma5")),
                "ma20": _safe_float(current.get("ma20")),
                "ma60": _safe_float(current.get("ma60")),
                "ma120": _safe_float(current.get("ma120")),
                "ma60_slope": round(float(current.get("ma60_slope", 0) or 0) * 100, 2),
            },
            "atr14": _safe_float(current.get("atr14")),
        }
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
