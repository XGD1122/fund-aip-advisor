"""
今日Top20买入推荐引擎
基于格雷厄姆-巴菲特价值投资体系：
  格雷厄姆指数 / PE分位法 / 均线金字塔 / 回撤买入 / 双重验证
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from models.database import get_connection
from engine.indicators import (
    calc_period_return_from_returns,
    calc_nav_percentile, calc_ma_deviation_multi, calc_sharpe,
)
from data.fetcher import fetch_fund_nav
from data.cleaner import clean_nav_data, save_nav_data

FLAT_LINE_THRESHOLD = 0.0001
PROFITABILITY_1Y_MIN = 0.02
FREEFALL_60D = 0.30
FUND_TYPE_FILTER = "指数型"


def compute_top20() -> list:
    """主入口：按大师规则选出最值得买入的20只A类指数基金"""
    conn = get_connection()

    candidates = _get_a_class_candidates(conn)
    if not candidates:
        conn.close()
        return []

    all_codes = [c["code"] for c in candidates]
    active = _filter_active(conn, all_codes)
    signals = _batch_get_signals(conn, [c for c in all_codes if c in active])
    returns_data = _batch_get_returns(conn, list(active))
    conn.close()

    results = []
    for c in candidates:
        code = c["code"]
        if code not in active or code not in signals or code not in returns_data:
            continue

        rets = returns_data[code]
        n = len(rets)
        if n < 120:
            continue
        if _is_flat_line(rets):
            continue

        # 周期回报
        r5 = calc_period_return_from_returns(rets, 5)
        r10 = calc_period_return_from_returns(rets, 10)
        r20 = calc_period_return_from_returns(rets, 20)
        r60 = calc_period_return_from_returns(rets, 60)
        r1y = calc_period_return_from_returns(rets, 252)
        r2y = calc_period_return_from_returns(rets, 504) if n >= 504 else r1y

        if r1y < PROFITABILITY_1Y_MIN:
            continue

        sig = signals[code]
        s = _score_master(rets, r5, r10, r20, r60, r1y, r2y, sig, c)
        if s["score"] <= 0:
            continue

        results.append({
            "code": code,
            "name": c["name"],
            "fund_type": c["fund_type"],
            "score": round(s["score"], 1),
            "ret_5d": round(r5 * 100, 2),
            "ret_10d": round(r10 * 100, 2),
            "ret_20d": round(r20 * 100, 2),
            "ret_1y": round(r1y * 100, 2),
            "nav_pct_2y": round(s["nav_pct"] * 100, 1),
            "rsi": round(sig.get("rsi14", 50) or 50, 1),
            "consecutive_down": s["consecutive_down"],
            "drawdown": round(s.get("drawdown", 0) * 100, 1),
            "ma_below": s.get("ma_below", 0),
            "warning": s.get("warning", ""),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:20]


# ============================================================
# 候选筛选
# ============================================================

def _get_a_class_candidates(conn) -> list:
    rows = conn.execute("""
        SELECT code, name, fund_type FROM fund_basic
        WHERE fund_type LIKE ? AND (name LIKE '%A' OR name LIKE '%A类')
    """, (FUND_TYPE_FILTER + "%",)).fetchall()
    return [dict(r) for r in rows]


def _filter_active(conn, codes: list) -> set:
    stale_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    active = set()
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        placeholders = ",".join(["?"] * len(batch))
        rows = conn.execute(
            f"SELECT code FROM fund_nav WHERE code IN ({placeholders}) "
            "GROUP BY code HAVING MAX(date) >= ? AND COUNT(*) >= 120",
            (*batch, stale_date)
        ).fetchall()
        active.update(r["code"] for r in rows)
    return active


def _batch_get_signals(conn, codes: list) -> dict:
    result = {}
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        placeholders = ",".join(["?"] * len(batch))
        rows = conn.execute(
            f"""SELECT s.* FROM fund_signal s
                INNER JOIN (
                    SELECT code, MAX(date) AS max_date FROM fund_signal
                    WHERE code IN ({placeholders}) GROUP BY code
                ) latest ON s.code = latest.code AND s.date = latest.max_date""",
            batch
        ).fetchall()
        for r in rows:
            result[r["code"]] = dict(r)
    return result


def _batch_get_returns(conn, codes: list) -> dict:
    result = {}
    for i in range(0, len(codes), 500):
        batch = codes[i:i + 500]
        placeholders = ",".join(["?"] * len(batch))
        rows = conn.execute(
            f"SELECT code, daily_return FROM fund_nav "
            f"WHERE code IN ({placeholders}) ORDER BY code, date",
            batch
        ).fetchall()
        by_code = {}
        for r in rows:
            by_code.setdefault(r["code"], []).append(r["daily_return"] or 0)
        for code, rets in by_code.items():
            result[code] = pd.Series(rets, dtype=float)
    return result


def _is_flat_line(returns: pd.Series) -> bool:
    return float(returns.abs().mean()) < FLAT_LINE_THRESHOLD


# ============================================================
# 大师规则评分引擎
# ============================================================

def _score_master(rets: pd.Series, r5, r10, r20, r60, r1y, r2y,
                  sig: dict, basic: dict) -> dict:
    """
    基于格雷厄姆-巴菲特体系的五维评分：

    1. 估值分位 (30分) — Graham: "安全边际"
    2. 均线系统 (25分) — 金字塔抄底：跌破均线越多越买
    3. 回撤买入 (20分) — 从高点回撤 = 打折买入
    4. 质量保障 (15分) — 排除价值陷阱
    5. 技术信号 (10分) — RSI超卖 + MACD底部拐头
    """
    # 构建价格序列（从收益累积）
    price = (1 + rets).cumprod()
    n = len(price)

    # === 1. 估值分位 (30分) ===
    lookback = min(1260, n)  # 最多5年
    nav_pct = calc_nav_percentile(price, lookback)
    v_score = _score_valuation(nav_pct)  # 0-30

    # === 2. 均线系统 (25分) ===
    ma_dev = _calc_ma_deviations(price)
    ma_score, ma_below = _score_ma_system(ma_dev)  # 0-25

    # === 3. 回撤买入 (20分) ===
    dd, dd_score = _score_drawdown(price)  # 0-20

    # === 4. 质量保障 (15分) ===
    q_score = _score_quality(basic, rets)  # 0-15

    # === 5. 技术信号 (10分) ===
    rsi = sig.get("rsi14", 50) or 50
    dif = sig.get("macd_dif", 0) or 0
    dea = sig.get("macd_dea", 0) or 0
    hist = sig.get("macd_hist", 0) or 0
    t_score = _score_technical(rsi, dif, dea, hist)  # 0-10

    score = v_score + ma_score + dd_score + q_score + t_score

    # 崩盘惩罚：60日跌幅 > 30%
    if r60 < -FREEFALL_60D:
        score *= 0.3

    # 追高风险：1年涨幅 > 25%
    warning = ""
    if r1y > 0.25:
        warning = "追高风险: 近1年涨幅过大"
    elif nav_pct <= 0.2 and ma_below >= 2:
        warning = "低估值+均线支撑"

    # 连续下跌天数
    raw = rets.values
    cd = 0
    for i in range(len(raw) - 1, max(0, len(raw) - 30), -1):
        if raw[i] < 0:
            cd += 1
        else:
            break

    return {
        "score": min(100, max(0, score)),
        "nav_pct": nav_pct,
        "consecutive_down": cd,
        "drawdown": dd,
        "ma_below": ma_below,
        "warning": warning,
    }


# === 1. 估值分位 (0-30) ===

def _score_valuation(nav_pct: float) -> float:
    """格雷厄姆估值分位评分 — 越低越安全"""
    if nav_pct <= 0.10:
        return 30.0   # 极度低估（近5年最低10%）
    elif nav_pct <= 0.20:
        return 27.0   # 明显低估
    elif nav_pct <= 0.30:
        return 23.0   # 低估
    elif nav_pct <= 0.40:
        return 18.0   # 偏低
    elif nav_pct <= 0.50:
        return 13.0   # 合理偏低
    elif nav_pct <= 0.60:
        return 8.0    # 合理
    elif nav_pct <= 0.70:
        return 4.0    # 偏高
    else:
        return 1.0    # 高估


# === 2. 均线系统 (0-25) ===

def _calc_ma_deviations(price: pd.Series) -> dict:
    """计算价格对 MA60/MA120/MA240 的偏离度"""
    n = len(price)
    result = {}
    for w, label in [(60, "ma60"), (120, "ma120"), (240, "ma240")]:
        if n >= w:
            ma = price.tail(w).mean()
            result[label] = float((price.iloc[-1] - ma) / ma) if ma > 0 else 0
        else:
            result[label] = 0
    return result


def _score_ma_system(ma_dev: dict) -> tuple:
    """
    均线金字塔评分 (0-25)
    格雷厄姆式阶梯：跌破均线越多 → 打折越深 → 加分越多
    """
    score = 0.0
    below = 0
    d60 = ma_dev.get("ma60", 0) or 0
    d120 = ma_dev.get("ma120", 0) or 0
    d240 = ma_dev.get("ma240", 0) or 0

    if d240 < 0:
        score += 10.0   # 破年线 = 三年一遇好机会
        below += 1
    elif d240 < 0.02:
        score += 6.0    # 接近年线支撑
    else:
        score += 2.0    # 年线上方

    if d120 < 0:
        score += 8.0    # 破半年线
        below += 1
    elif d120 < 0.02:
        score += 5.0
    else:
        score += 2.0

    if d60 < 0:
        score += 7.0    # 破季线
        below += 1
    elif d60 < 0.02:
        score += 4.0
    else:
        score += 2.0

    # 双重验证加成：估值低 + 均线下方
    # (估值分位在主函数判断，这里只加均线分)

    return score, below


# === 3. 回撤买入 (0-20) ===

def _score_drawdown(price: pd.Series) -> tuple:
    """
    回撤买入法：从1年高点回撤越多，买入越有利
    巴菲特：别人恐惧时贪婪
    """
    n = len(price)
    window = min(252, n)  # 1年
    peak = price.tail(window).max()
    current = price.iloc[-1]
    dd = float((current - peak) / peak)  # 负值表示回撤

    if dd <= -0.30:
        score = 20.0   # 大跌30%+ → 极度恐惧 → 重仓机会
    elif dd <= -0.20:
        score = 18.0   # 跌20-30% → 深度回调
    elif dd <= -0.15:
        score = 15.0   # 跌15-20% → 明显回调
    elif dd <= -0.10:
        score = 12.0   # 跌10-15% → 正常回调
    elif dd <= -0.05:
        score = 8.0    # 温和回调
    elif dd <= 0:
        score = 4.0    # 横盘或微跌
    else:
        score = 1.0    # 创新高 → 不建议追

    return dd, score


# === 4. 质量保障 (0-15) ===

def _score_quality(basic: dict, returns: pd.Series) -> float:
    """排除价值陷阱：便宜但基本面差的基金要扣分"""
    score = 0.0

    # 基金年限 (5分)
    est = basic.get("establish_date", "")
    try:
        d = datetime.strptime(str(est)[:10], "%Y-%m-%d")
        age = (datetime.now() - d).days / 365.0
    except Exception:
        age = 1
    if age >= 5:
        score += 5.0
    elif age >= 3:
        score += 4.0
    elif age >= 1:
        score += 2.0
    else:
        score += 1.0

    # 规模 (5分)
    scale = basic.get("scale", 0) or 0
    if scale:
        s = float(scale) / 1e8
        if 5 <= s <= 50:
            score += 5.0
        elif 2 <= s < 5 or s > 50:
            score += 3.0
        else:
            score += 2.0
    else:
        score += 2.5

    # 夏普比率 (5分)
    if len(returns) >= 252:
        sh = calc_sharpe(returns=returns, risk_free=0.025)
        if sh > 0.8:
            score += 5.0
        elif sh > 0.5:
            score += 4.0
        elif sh > 0.2:
            score += 3.0
        elif sh > 0:
            score += 2.0
        else:
            score += 0.0   # 负夏普 → 亏钱基金
    else:
        score += 2.5

    return score


# === 5. 技术信号 (0-10) ===

def _score_technical(rsi: float, dif: float, dea: float, hist: float) -> float:
    """底部技术信号：RSI超卖 + MACD拐头"""
    score = 0.0

    # RSI (6分)
    if 30 <= rsi <= 40:
        score += 6.0   # 超卖黄金区
    elif 40 < rsi <= 45:
        score += 4.5   # 偏弱
    elif 45 < rsi <= 50:
        score += 3.0   # 中性偏低
    elif rsi < 30:
        score += 3.0   # 极度超卖 → 可能有雷
    elif 50 < rsi <= 60:
        score += 2.0
    else:
        score += 0.5

    # MACD底部拐头 (4分)
    if dif > dea:
        score += 2.0   # 金叉
        if hist > 0:
            score += 2.0  # 柱线转正 → 动能确认
    elif dif < dea and dif > dea * 1.05:  # 接近金叉
        score += 1.0

    return score


# ============================================================
# 数据刷新
# ============================================================

def refresh_all_data():
    """全量数据刷新（首次初始化用，耗时 30-60 分钟）"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_connection()
    stale = conn.execute("""
        SELECT b.code FROM fund_basic b
        WHERE b.fund_type LIKE ?
        AND (SELECT MAX(date) FROM fund_nav WHERE code=b.code) < ?
        OR NOT EXISTS (SELECT 1 FROM fund_nav WHERE code=b.code)
    """, (FUND_TYPE_FILTER + "%", yesterday)).fetchall()
    conn.close()

    stale_codes = [r[0] for r in stale]
    if len(stale_codes) == 0:
        print(f"[{datetime.now()}] NAV is up to date", flush=True)
        update_signals()
        return

    print(f"[{datetime.now()}] {len(stale_codes)} funds stale, 5 threads...", flush=True)
    fetched = [0]
    done = [0]
    lock = threading.Lock()

    def _fetch_one(code):
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
            with lock:
                fetched[0] += 1
        with lock:
            done[0] += 1
            if done[0] % 500 == 0:
                print(f"  {done[0]}/{len(stale_codes)}", flush=True)
        return True

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_one, code) for code in stale_codes]
        for f in as_completed(futures):
            pass

    print(f"  NAV done: {fetched[0]}/{len(stale_codes)}", flush=True)
    update_signals()
    print(f"[{datetime.now()}] Refresh complete", flush=True)


def refresh_daily():
    """每日轻量刷新：只拉取净值过期的基金，只更新有变化的信号（约 3-10 分钟）"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_connection()
    # 只找净值落后的A类指数基金（Top20只需要A类）
    stale = conn.execute("""
        SELECT b.code FROM fund_basic b
        WHERE b.fund_type LIKE ?
        AND (b.name LIKE '%A' OR b.name LIKE '%A类')
        AND (SELECT MAX(date) FROM fund_nav WHERE code=b.code) < ?
    """, (FUND_TYPE_FILTER + "%", yesterday)).fetchall()
    conn.close()

    stale_codes = [r[0] for r in stale]
    if len(stale_codes) == 0:
        print(f"[{datetime.now()}] All NAV up to date", flush=True)
        return

    print(f"[{datetime.now()}] {len(stale_codes)} funds need NAV update...", flush=True)
    updated_codes = []

    # V8 引擎单线程，直接顺序拉取（不需要线程池）
    for i, code in enumerate(stale_codes):
        df = fetch_fund_nav(code)
        if not df.empty:
            df = clean_nav_data(df)
            save_nav_data(df)
            updated_codes.append(code)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(stale_codes)}", flush=True)

    print(f"  NAV updated: {len(updated_codes)}/{len(stale_codes)}", flush=True)

    # 只更新有净值变化的基金的信号
    if updated_codes:
        _update_signals_for_codes(updated_codes)
    print(f"[{datetime.now()}] Daily refresh complete", flush=True)


def update_signals():
    """全量更新A类基金信号（初始化和全量刷新用）"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE ? AND (name LIKE '%A' OR name LIKE '%A类')",
        (FUND_TYPE_FILTER + "%",)
    ).fetchall()]
    conn.close()
    _update_signals_for_codes(codes)


def _update_signals_for_codes(codes: list):
    """只更新指定基金列表的信号（增量更新）"""
    total = len(codes)
    for i, code in enumerate(codes):
        df = _calc_signals_for_fund(code)
        if df.empty:
            continue
        conn = get_connection()
        last = df.iloc[-1]
        try:
            conn.execute("""
                INSERT OR REPLACE INTO fund_signal
                (code, date, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, rsi14, bb_upper, bb_mid, bb_lower)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, str(last["date"]),
                float(last.get("ma5", 0) or 0), float(last.get("ma20", 0) or 0),
                float(last.get("ma60", 0) or 0), float(last.get("ma120", 0) or 0),
                float(last.get("macd_dif", 0) or 0), float(last.get("macd_dea", 0) or 0),
                float(last.get("macd_hist", 0) or 0), float(last.get("rsi14", 50) or 50),
                float(last.get("bb_upper", 0) or 0), float(last.get("bb_mid", 0) or 0),
                float(last.get("bb_lower", 0) or 0),
            ))
        except Exception:
            pass
        conn.commit()
        conn.close()
        if (i + 1) % 500 == 0:
            print(f"  signals: {i + 1}/{total}")
    print(f"Signals done: {total}")


def _calc_signals_for_fund(code: str) -> pd.DataFrame:
    from engine.indicators import calc_ma, calc_macd, calc_rsi, calc_bollinger

    conn = get_connection()
    rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()

    if len(rows) < 20:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)

    nav = df["unit_nav"]
    df["ma5"] = calc_ma(nav, 5)
    df["ma20"] = calc_ma(nav, 20)
    df["ma60"] = calc_ma(nav, 60)
    df["ma120"] = calc_ma(nav, 120)

    macd = calc_macd(nav)
    df["macd_dif"] = macd["macd_dif"]
    df["macd_dea"] = macd["macd_dea"]
    df["macd_hist"] = macd["macd_hist"]

    df["rsi14"] = calc_rsi(nav, 14)

    bb = calc_bollinger(nav, 20)
    df["bb_upper"] = bb["bb_upper"]
    df["bb_mid"] = bb["bb_mid"]
    df["bb_lower"] = bb["bb_lower"]

    return df
