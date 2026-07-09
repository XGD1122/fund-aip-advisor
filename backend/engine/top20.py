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
MIN_DATA_DAYS = 252          # 最少1年数据
MIN_VALUATION_DAYS = 504     # 估值分位满分所需最少交易日（2年）

SECTOR_KEYWORDS = {
    "自由现金流": ["自由现金流", "现金流"],
    "卫星产业": ["卫星产业", "卫星"],
    "新能源": ["新能源", "光伏", "锂电", "电池", "风电", "碳中和"],
    "医药": ["医药", "医疗", "生物医药", "中药", "创新药"],
    "半导体": ["半导体", "芯片", "集成电路"],
    "军工": ["军工", "国防", "空天"],
    "消费": ["消费", "食品饮料", "白酒", "家电"],
    "红利": ["红利", "高股息"],
    "金融": ["银行", "金融", "证券", "保险"],
    "科技": ["科技", "人工智能", "AI", "机器人", "云计算", "大数据"],
}


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
        if n < MIN_DATA_DAYS:
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
            "volatility": s.get("volatility", 0),
            "bb_position": s.get("bb_position", ""),
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return _deduplicate_sector(results)[:20]


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


def _identify_sector(name: str) -> str:
    """按基金名称识别所属赛道"""
    for sector, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return sector
    return "其他"


def _deduplicate_sector(results: list, max_per_sector: int = 4) -> list:
    """同赛道去重：每个赛道最多保留N只，防止抱团霸榜"""
    seen = {}
    filtered = []
    for r in results:
        sector = _identify_sector(r["name"])
        seen.setdefault(sector, 0)
        if seen[sector] < max_per_sector:
            filtered.append(r)
            seen[sector] += 1
    return filtered


# ============================================================
# 大师规则评分引擎
# ============================================================

def _score_master(rets: pd.Series, r5, r10, r20, r60, r1y, r2y,
                  sig: dict, basic: dict) -> dict:
    """
    基于格雷厄姆-巴菲特体系的五维评分（增强版）：

    1. 估值分位 (30分) — 10档专业估值定投体系
    2. 均线系统 (25分) — 金字塔抄底 + MA60趋势方向
    3. 回撤买入 (20分) — 从高点回撤 = 打折买入
    4. 质量保障 (15分) — 排除价值陷阱
    5. 技术信号 (15分) — RSI + MACD + KDJ + 布林带 多指标共振
    附加：波动率调整因子
    """
    # 构建价格序列（从收益累积）
    price = (1 + rets).cumprod()
    n = len(price)

    # === 1. 估值分位 (30分) ===
    lookback = min(1260, n)  # 最多5年
    nav_pct = calc_nav_percentile(price, lookback)
    v_score = _score_valuation(nav_pct)  # 0-30

    # 数据不足2年的基金，估值分按比例打折（避免新基金虚高）
    if n < MIN_VALUATION_DAYS:
        v_score = v_score * (n / float(MIN_VALUATION_DAYS))

    # === 2. 均线系统 (25分) ===
    ma_dev = _calc_ma_deviations(price)
    ma60_slope = float(sig.get("ma60_slope", 0) or 0)
    ma_score, ma_below = _score_ma_system(ma_dev, ma60_slope)  # 0-25

    # === 3. 回撤买入 (20分) ===
    dd, dd_score = _score_drawdown(price)  # 0-20

    # === 4. 质量保障 (15分) ===
    q_score = _score_quality(basic, rets)  # 0-15

    # === 5. 技术信号 (15分) ===
    rsi = sig.get("rsi14", 50) or 50
    dif = sig.get("macd_dif", 0) or 0
    dea = sig.get("macd_dea", 0) or 0
    hist = sig.get("macd_hist", 0) or 0
    kdj_k = sig.get("kdj_k", 50) or 50
    kdj_d = sig.get("kdj_d", 50) or 50
    kdj_j = sig.get("kdj_j", 50) or 50
    bb_upper = sig.get("bb_upper", 0) or 0
    bb_mid = sig.get("bb_mid", 0) or 0
    bb_lower = sig.get("bb_lower", 0) or 0
    bb_width_val = sig.get("bb_width", 0) or 0

    # 布林带位置评估
    bb_score = _score_bollinger(price, bb_upper, bb_mid, bb_lower, bb_width_val)
    t_score = _score_technical(rsi, dif, dea, hist, kdj_k, kdj_d, kdj_j, bb_score)  # 0-15

    score = v_score + ma_score + dd_score + q_score + t_score

    # === 波动率调整因子 ===
    annual_vol = float(rets.std() * np.sqrt(252)) if len(rets) >= 60 else 0
    if annual_vol > 0.40:
        score *= 0.80   # 高波动基金，风险打折
    elif annual_vol > 0.25:
        score *= 0.90   # 中等波动

    # 崩盘惩罚：60日跌幅 > 30%
    if r60 < -FREEFALL_60D:
        score *= 0.3

    # 追高风险：1年涨幅 > 25%
    warning = ""
    if r1y > 0.25:
        warning = "追高风险: 近1年涨幅过大"
    elif nav_pct <= 0.2 and ma_below >= 2:
        warning = "低估值+均线支撑"
    elif kdj_j < 0:
        warning = "KDJ极度超卖"
    elif bb_width_val > 0 and bb_width_val < 0.02:
        warning = "布林带极窄，变盘在即"

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
        "volatility": round(annual_vol * 100, 1),
        "bb_position": "下轨" if bb_lower > 0 and float(price.iloc[-1]) <= bb_lower * 1.02 else
                       "下轨附近" if bb_lower > 0 and float(price.iloc[-1]) <= bb_lower * 1.05 else
                       "中轨下方" if bb_mid > 0 and float(price.iloc[-1]) < bb_mid else
                       "中轨上方" if bb_mid > 0 else "",
    }


# === 1. 估值分位 (0-30) ===

def _score_valuation(nav_pct: float) -> float:
    """格雷厄姆估值分位评分 — 10档专业估值定投体系"""
    if nav_pct <= 0.05:
        return 30.0   # 五年一遇，重仓机会
    elif nav_pct <= 0.10:
        return 28.0   # 极度低估，2倍定投区
    elif nav_pct <= 0.20:
        return 25.0   # 明显低估，1.5倍定投区
    elif nav_pct <= 0.30:
        return 21.0   # 低估，正常加仓
    elif nav_pct <= 0.40:
        return 16.0   # 偏低，可少量买入
    elif nav_pct <= 0.50:
        return 11.0   # 合理偏低，观望
    elif nav_pct <= 0.60:
        return 6.0    # 合理，暂不加仓
    elif nav_pct <= 0.70:
        return 3.0    # 偏高，不建议买入
    elif nav_pct <= 0.80:
        return 1.0    # 高估，等待回调
    else:
        return 0.0    # 极度高估，不买


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


def _score_ma_system(ma_dev: dict, ma60_slope: float = 0) -> tuple:
    """
    均线金字塔评分 (0-25)
    格雷厄姆式阶梯：跌破均线越多 → 打折越深 → 加分越多
    新增：MA60趋势方向加成
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

    # MA60趋势方向加成 (0~2分)
    if ma60_slope > 0.02:
        score += 2.0    # 均线向上，趋势健康
        below = max(0, below - 1)  # 趋势向上时降低破位严重度
    elif ma60_slope > 0:
        score += 1.0    # 均线走平

    return score, below


# === 2.5 布林带位置 (整合进技术分前独立计算) ===

def _score_bollinger(price: pd.Series, bb_upper: float, bb_mid: float, bb_lower: float,
                     bb_width_val: float = 0) -> float:
    """布林带位置评分 (0-5)，整合入技术分"""
    current = float(price.iloc[-1])
    score = 0.0

    if bb_lower > 0 and current <= bb_lower * 1.02:
        score += 3.0   # 触及/跌破下轨 → 超卖反弹机会
    elif bb_lower > 0 and current <= bb_lower * 1.05:
        score += 2.0   # 接近下轨
    elif bb_mid > 0 and current < bb_mid:
        score += 1.0   # 中轨下方，偏弱
    elif bb_mid > 0 and current > bb_mid:
        score += 2.0   # 突破中轨，趋势转强

    # 带宽收缩加成（预示变盘）
    if bb_width_val > 0 and bb_width_val < 0.03:
        score += 1.0   # 带宽极窄，即将变盘

    return min(5.0, score)


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

def _score_technical(rsi: float, dif: float, dea: float, hist: float,
                     kdj_k: float = 50, kdj_d: float = 50, kdj_j: float = 50,
                     bb_score: float = 0) -> float:
    """底部技术信号 (0-15)：RSI超卖 + MACD拐头 + KDJ + 布林带"""
    score = 0.0

    # RSI (6分) — 保持原有逻辑
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

    # MACD (4分) — 保持原有逻辑
    if dif > dea:
        score += 2.0   # 金叉
        if hist > 0:
            score += 2.0  # 柱线转正 → 动能确认
    elif dif < dea and dif > dea * 1.05:  # 接近金叉
        score += 1.0

    # KDJ (3分) — 新增
    if kdj_j < 0:
        score += 2.0   # J值<0，极度超卖
    elif kdj_j < 20:
        score += 1.5   # 深度超卖
    if kdj_k > kdj_d and kdj_k < 30:
        score += 1.0   # 低位金叉

    # 布林带位置 (2分) — 从bb_score映射
    if bb_score >= 3:
        score += 2.0
    elif bb_score >= 2:
        score += 1.0

    return min(15.0, score)


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
                (code, date, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, rsi14,
                 bb_upper, bb_mid, bb_lower, kdj_k, kdj_d, kdj_j, bb_width, atr14, ma60_slope)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, str(last["date"]),
                float(last.get("ma5", 0) or 0), float(last.get("ma20", 0) or 0),
                float(last.get("ma60", 0) or 0), float(last.get("ma120", 0) or 0),
                float(last.get("macd_dif", 0) or 0), float(last.get("macd_dea", 0) or 0),
                float(last.get("macd_hist", 0) or 0), float(last.get("rsi14", 50) or 50),
                float(last.get("bb_upper", 0) or 0), float(last.get("bb_mid", 0) or 0),
                float(last.get("bb_lower", 0) or 0),
                float(last.get("kdj_k", 50) or 50), float(last.get("kdj_d", 50) or 50),
                float(last.get("kdj_j", 50) or 50),
                float(last.get("bb_width", 0) or 0), float(last.get("atr14", 0) or 0),
                float(last.get("ma60_slope", 0) or 0),
            ))
        except Exception as e:
            print(f"  signal insert error [{code}]: {e}")
        conn.commit()
        conn.close()
        if (i + 1) % 500 == 0:
            print(f"  signals: {i + 1}/{total}")
    print(f"Signals done: {total}")


def _calc_signals_for_fund(code: str) -> pd.DataFrame:
    from engine.indicators import (
        calc_ma, calc_macd, calc_rsi, calc_bollinger,
        calc_kdj, calc_atr, calc_bb_width,
    )

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

    # 新增指标
    kdj = calc_kdj(nav, 9, 3, 3)
    df["kdj_k"] = kdj["kdj_k"]
    df["kdj_d"] = kdj["kdj_d"]
    df["kdj_j"] = kdj["kdj_j"]

    df["atr14"] = calc_atr(nav, 14)
    df["bb_width"] = calc_bb_width(nav, 20)

    # MA60 斜率（近20日变化率）
    ma60_s = calc_ma(nav, 60)
    df["ma60_slope"] = ma60_s.diff(20) / ma60_s.shift(20).replace(0, np.nan)
    df["ma60_slope"] = df["ma60_slope"].fillna(0)

    return df
