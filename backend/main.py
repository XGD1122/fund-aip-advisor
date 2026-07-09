from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.database import init_db, get_connection
from datetime import datetime, timedelta
import time

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
                # 只统计A类基金，因为Top20只用A类
                fund_count = conn.execute(
                    "SELECT COUNT(*) FROM fund_basic WHERE fund_type LIKE '指数型%' AND (name LIKE '%A' OR name LIKE '%A类')"
                ).fetchone()[0]
                signal_count = conn.execute(
                    "SELECT COUNT(*) FROM fund_signal WHERE date=?", (latest,)
                ).fetchone()[0]
                conn.close()
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

    threading.Thread(target=_auto_refresh_if_stale, daemon=True).start()


@app.get("/api/top20")
def api_top20(refresh: bool = False):
    """返回今日最值得买入的Top20基金（缓存5分钟）"""
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


@app.get("/api/admin/refresh")
def api_admin_refresh():
    """手动触发每日数据刷新"""
    from engine.top20 import refresh_daily
    refresh_daily()
    return {"status": "ok", "message": "数据刷新完成"}


@app.get("/api/fund/{code}")
def api_fund_detail(code: str):
    """返回单只基金的净值历史、技术指标、评分明细"""
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
        "SELECT date, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, rsi14 FROM fund_signal WHERE code=? ORDER BY date",
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
                "rsi": round(float(r["rsi14"] or 50), 1)}
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
        },
        "returns": rets,
        "record_count": len(navs),
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
