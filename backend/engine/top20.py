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
from config import FUND_TYPE_FILTER, RISK_FREE_RATE
from data.fetcher import fetch_fund_nav
from data.cleaner import clean_nav_data, save_nav_data

FLAT_LINE_THRESHOLD = 0.0001
PROFITABILITY_1Y_MIN = 0.02
FREEFALL_60D = 0.30
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
    """主入口：按大师规则选出最值得买入的20只指数基金（排除C/E类收费份额）"""
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
            # 软惩罚而非硬排除：深度价值买点常在1年负收益后出现
            # r1y会在_score_master中触发额外扣分
            pass

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
    """获取候选基金：排除C类/E类份额（底层资产相同，仅费率不同），保留A类+无后缀等"""
    rows = conn.execute("""
        SELECT code, name, fund_type FROM fund_basic
        WHERE fund_type LIKE ?
          AND name NOT LIKE '%C'
          AND name NOT LIKE '%C类%'
          AND name NOT LIKE '%E'
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


def _deduplicate_sector(results: list, max_per_sector: int = 3) -> list:
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
    专业六维评分体系（对标天天基金+晨星+机构策略）：

    1. 估值安全边际 (30分) — NAV历史分位，"先看估值定贵贱"
    2. 收益能力 (20分) — 风险调整后收益+正收益稳定性
    3. 趋势与均线 (20分) — 均线偏离价值+MA斜率方向
    4. 技术反转 (15分) — RSI+KDJ+布林带，捕捉极端点
    5. 基本面质量 (15分) — 规模/年限/费率/跟踪误差
    6. 回撤与风控 (10分) — 回撤深度+波动率+连跌天数
    """
    price = (1 + rets).cumprod()
    n = len(price)

    # === 1. 估值安全边际 (30分) ===
    lookback = min(1260, n)
    nav_pct = calc_nav_percentile(price, lookback)
    v_score = _score_valuation(nav_pct)
    if n < MIN_VALUATION_DAYS:
        v_score = v_score * (n / float(MIN_VALUATION_DAYS))

    # === 2. 收益能力 (20分) — 正向评价收益 ===
    ret_score, sharpe_val = _score_returns(rets, r1y, r2y, n)

    # === 3. 趋势与均线 (20分) — 奖励企稳回升 ===
    ma_dev = _calc_ma_deviations(price)
    ma60_slope = float(sig.get("ma60_slope", 0) or 0)
    ma_score, ma_below = _score_ma_system(ma_dev, ma60_slope, r20)

    # === 4. 技术反转 (15分) ===
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
    current_nav_sig = float(sig.get("unit_nav", 0) or 0)
    bb_score = _score_bollinger_nav(current_nav_sig, bb_upper, bb_mid, bb_lower, bb_width_val)
    tech_score = _score_technical(rsi, dif, dea, hist, kdj_k, kdj_d, kdj_j, bb_score)

    # === 5. 基本面质量 (10分) ===
    qual_score = _score_quality(basic)

    # === 6. 回撤与风控 (10分) ===
    dd = _calc_max_drawdown(price)
    consecutive_down = 0
    raw_vals = rets.values
    for i in range(len(raw_vals) - 1, max(-1, len(raw_vals) - 21), -1):
        if raw_vals[i] < 0: consecutive_down += 1
        else: break
    annual_vol = float(rets.std() * np.sqrt(252)) if len(rets) >= 60 else 0
    risk_score = _score_risk(dd, annual_vol, consecutive_down)

    # === 综合评分 ===
    score = v_score + ret_score + ma_score + tech_score + qual_score + risk_score

    # === 追高防御（仅极端情况） ===
    warning = ""
    if r1y > 0.40:
        score *= 0.80
        warning = "追高风险: 近1年涨幅>40%"
    elif r1y > 0.30:
        score *= 0.88
        warning = "追高风险: 近1年涨幅>30%"
    elif nav_pct <= 0.25 and r20 > -0.02 and ma_below <= 1:
        warning = "低估值+趋势企稳+技术配合 → 优质买点"
    elif nav_pct <= 0.25 and ma_below <= 1:
        warning = "低估值+趋势改善（关注技术确认）"
    elif kdj_j < 0 and r20 > 0:
        warning = "KDJ极度超卖+短期反弹"
    elif sharpe_val > 0.5 and nav_pct < 0.3:
        warning = "高夏普+低估值 → 性价比突出"

    return {
        "score": min(100, max(0, score)),
        "nav_pct": nav_pct,
        "consecutive_down": consecutive_down,
        "drawdown": dd,
        "ma_below": ma_below,
        "warning": warning,
        "volatility": round(annual_vol * 100, 1),
        "bb_position": "下轨" if bb_lower > 0 and current_nav_sig > 0 and current_nav_sig <= bb_lower * 1.02 else
                       "下轨附近" if bb_lower > 0 and current_nav_sig > 0 and current_nav_sig <= bb_lower * 1.05 else
                       "中轨下方" if bb_mid > 0 and current_nav_sig > 0 and current_nav_sig < bb_mid else
                       "中轨上方" if bb_mid > 0 and current_nav_sig > 0 else "",
    }


# === 1. 估值安全边际 (0-30) ===
# 对标机构PE分位<30%=低估标准，这是价值投资最核心的维度

def _score_valuation(nav_pct: float) -> float:
    """估值安全边际 — 越便宜越加分"""
    if nav_pct <= 0.05:   return 30.0   # 极度低估：历史底部5%以内
    elif nav_pct <= 0.10: return 28.0
    elif nav_pct <= 0.20: return 24.0   # 显著低估
    elif nav_pct <= 0.30: return 18.0   # 低估（机构标准线PE<30%分位）
    elif nav_pct <= 0.40: return 12.0   # 偏低
    elif nav_pct <= 0.50: return 7.0    # 合理偏低
    elif nav_pct <= 0.60: return 4.0    # 合理
    elif nav_pct <= 0.70: return 1.0    # 略偏高
    else:                 return 0.0    # 安全边际不足


# === 2. 收益能力 (0-20) ===

def _score_returns(returns: pd.Series, r1y: float, r2y: float, n: int) -> tuple:
    """
    风险调整后收益 — 对标天天基金"收益率"+晨星风险调整收益核心
    正向评价：好收益加分，而不是跌了扣分
    """
    score = 0.0

    # 夏普比率 (10分) — 晨星核心指标
    if n >= 252:
        sh = calc_sharpe(returns=returns, risk_free=RISK_FREE_RATE)
    else:
        sh = 0
    if sh > 1.0:        score += 10.0
    elif sh > 0.7:      score += 8.0
    elif sh > 0.4:      score += 6.0
    elif sh > 0.15:     score += 4.0
    elif sh > 0:        score += 2.0
    # sh ≤ 0: 不奖励也不惩罚（可能是低估值机会）

    # 绝对收益 (5分) — 真金白银赚到钱才是好基金
    if r1y > 0.10:      score += 5.0    # 年化>10%
    elif r1y > 0.03:    score += 4.0    # 正收益
    elif r1y > 0:       score += 3.0
    elif r1y > -0.10:   score += 2.0    # 微亏可接受
    elif r1y > -0.20:   score += 1.0
    # r1y < -20%: 不加分，由估值/技术维度判断是否底部机会

    # 正收益稳定性 (5分) — 对标天天基金"稳定性"维度
    if n >= 60:
        monthly = returns.tail(min(252, n)).values
        chunks = max(1, len(monthly) // 21)
        monthly_rets = []
        for i in range(chunks):
            chunk = monthly[i*21:(i+1)*21]
            ret = (1 + pd.Series(chunk)).prod() - 1
            monthly_rets.append(ret)
        positive_months = sum(1 for r in monthly_rets if r > 0)
        total_months = max(1, len(monthly_rets))
        positive_ratio = positive_months / total_months
        if positive_ratio > 0.65:   score += 5.0
        elif positive_ratio > 0.55: score += 4.0
        elif positive_ratio > 0.45: score += 2.5
        elif positive_ratio > 0.35: score += 1.0
        # else: 不加分（可能是熊市底部）
    else:
        score += 2.0  # 数据不足给中值

    return min(20.0, score), sh


# === 3. 趋势与均线 (0-20) ===

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


def _score_ma_system(ma_dev: dict, ma60_slope: float = 0, r20: float = 0) -> tuple:
    """
    趋势与均线评分 (0-20) — 对标机构"估值+趋势双确认"
    跌破均线=价值信号(奖励)，均线斜率向上=企稳信号(加分)
    两者互补而非矛盾：深度跌破+斜率转正 = 最佳买点
    """
    score = 0.0
    below_count = 0  # 统计价格跌破几条均线
    d60 = ma_dev.get("ma60", 0) or 0
    d120 = ma_dev.get("ma120", 0) or 0
    d240 = ma_dev.get("ma240", 0) or 0

    # --- 均线偏离度 (12分) ---
    # 核心逻辑：跌破均线=价值机会。适度跌破加分，但极度偏离不加分（可能有问题）

    # MA240 偏离 (4分)
    if d240 < -0.10:      score += 3.0; below_count += 1  # 深度跌破 → 长线价值
    elif d240 < -0.03:    score += 3.5; below_count += 1  # 明显跌破 → 价值区域
    elif d240 < 0:        score += 4.0; below_count += 1  # 轻微跌破 → 黄金买点
    elif d240 < 0.02:     score += 3.0                     # 接近均线
    elif d240 < 0.05:     score += 2.0                     # 略高于均线
    else:                 score += 1.0                     # 远高于均线 → 偏贵

    # MA120 偏离 (4分)
    if d120 < -0.08:      score += 3.0; below_count += 1
    elif d120 < -0.02:    score += 3.5; below_count += 1
    elif d120 < 0:        score += 4.0; below_count += 1
    elif d120 < 0.03:     score += 3.0
    elif d120 < 0.08:     score += 2.0
    else:                 score += 1.0

    # MA60 偏离 (4分) — 短期偏离最关键
    if d60 < -0.06:       score += 2.5; below_count += 1  # 大幅偏离 → 超跌
    elif d60 < -0.02:     score += 3.0; below_count += 1  # 适度偏离 → 价值
    elif d60 < 0:         score += 4.0; below_count += 1  # 轻微跌破 → 最佳
    elif d60 < 0.02:      score += 3.5                     # 接近均线 → 即将突破
    elif d60 < 0.05:      score += 2.5                     # 小幅站上
    else:                 score += 1.0                     # 偏离过大 → 追高风险

    # --- 均线斜率/趋势 (8分) ---
    # 核心逻辑：均线方向向上=趋势向好，斜率越大越好

    # MA60 斜率 (5分)
    if ma60_slope > 0.03:     score += 5.0   # 强劲上翘 → 趋势确认
    elif ma60_slope > 0.015:  score += 4.0   # 稳步向上
    elif ma60_slope > 0.005:  score += 3.0   # 缓慢回升
    elif ma60_slope > 0:      score += 2.0   # 开始转正
    elif ma60_slope > -0.01:  score += 1.0   # 接近走平，即将拐头
    # 斜率 < -0.01: 还在下跌中，不加分

    # r20 动能确认 (3分) — 短期已开始反弹
    if r20 > 0.03:            score += 3.0   # 近20日稳健上涨
    elif r20 > 0.01:          score += 2.0   # 小幅上涨
    elif r20 > 0:             score += 1.0   # 微涨，至少没在跌
    # r20 ≤ 0: 不加分（未确认反弹）

    return min(20.0, score), below_count


# === 2.5 布林带位置 (整合进技术分前独立计算) ===

def _score_bollinger_nav(current_nav: float, bb_upper: float, bb_mid: float, bb_lower: float,
                         bb_width_val: float = 0) -> float:
    """布林带买入评分 (0-5)：越低越加分（一致的反向投资逻辑）"""
    score = 0.0
    if current_nav <= 0 or bb_lower <= 0 or bb_mid <= 0:
        return score

    # 核心逻辑：价格越接近/跌破下轨，买入越划算
    if current_nav <= bb_lower:
        score += 4.0   # 跌破下轨 → 深度超卖，反弹概率高
    elif current_nav <= bb_lower * 1.03:
        score += 3.0   # 紧贴下轨 → 超卖区域
    elif current_nav <= bb_lower * 1.08:
        score += 2.0   # 下轨附近 → 偏低估
    elif current_nav < bb_mid:
        score += 1.0   # 中轨下方 → 偏弱

    # 带宽收缩加成（预示变盘，双向可能）
    if bb_width_val > 0 and bb_width_val < 0.03:
        score += 1.0   # 带宽极窄，即将变盘

    return min(5.0, score)


# === 5. 基本面质量 (0-15) ===

def _score_quality(basic: dict) -> float:
    """基本面质量（0-15）— 对标晨星 People/Process/Parent + Price Score"""
    score = 0.0

    # 基金年限 (4分)
    est = basic.get("establish_date", "")
    try:
        d = datetime.strptime(str(est)[:10], "%Y-%m-%d")
        age = (datetime.now() - d).days / 365.0
    except Exception:
        age = 1
    if age >= 5:       score += 4.0
    elif age >= 3:     score += 3.0
    elif age >= 1:     score += 1.5

    # 基金规模 (4分)
    scale = basic.get("scale", 0) or 0
    if scale:
        s = float(scale) / 1e8
        if 5 <= s <= 50:    score += 4.0
        elif 2 <= s < 5 or s > 50: score += 2.5
        else:               score += 1.0
    else:
        score += 2.0

    # 费率优势 (3分) — 晨星 Price Score
    fee_mgmt = basic.get("fee_mgmt", 0) or 0
    fee_custody = basic.get("fee_custody", 0) or 0
    total_fee = float(fee_mgmt) + float(fee_custody)
    if total_fee <= 0.5:      score += 3.0
    elif total_fee <= 0.8:    score += 2.0
    elif total_fee <= 1.0:    score += 1.0

    # 跟踪误差 (4分) — 被动基金核心指标
    tracking_error = basic.get("tracking_error", 0) or 0
    te = float(tracking_error)
    if te <= 0:
        score += 2.0   # 数据缺失，给中值不惩罚也不奖励
    elif te < 0.01:   score += 4.0
    elif te < 0.03:   score += 3.0
    elif te < 0.05:   score += 2.0
    elif te < 0.10:   score += 1.0

    return min(15.0, score)


# === 6. 回撤与风控 (0-10) ===

def _calc_max_drawdown(price: pd.Series) -> float:
    """计算1年内最大回撤"""
    n = len(price)
    win = min(252, n)
    recent = price.tail(win)
    peak = recent.cummax()
    return float((recent - peak).div(peak).min())


def _score_risk(dd: float, annual_vol: float, consecutive_down: int) -> float:
    """
    回撤与风控 (0-10) — 对标天天基金"抗风险"+"稳定性"
    回撤深→机会大（加分），但波动过高/连续下跌→风险高（不加分）
    """
    score = 0.0

    # 回撤深度 (5分) — 深度回撤提供安全边际
    if dd <= -0.35:     score += 5.0
    elif dd <= -0.25:   score += 4.0
    elif dd <= -0.15:   score += 3.0
    elif dd <= -0.08:   score += 2.0
    elif dd < 0:        score += 1.0

    # 波动率 (3分)
    if annual_vol > 0:
        if annual_vol < 0.18:       score += 3.0
        elif annual_vol < 0.25:     score += 2.0
        elif annual_vol < 0.35:     score += 1.0

    # 连跌天数 (2分) — 越少越好
    if consecutive_down <= 2:   score += 2.0
    elif consecutive_down <= 5: score += 1.0

    return min(10.0, score)


# === 4. 技术反转 (0-15) ===

def _score_technical(rsi: float, dif: float, dea: float, hist: float,
                     kdj_k: float = 50, kdj_d: float = 50, kdj_j: float = 50,
                     bb_score: float = 0) -> float:
    """底部技术反转信号 (0-15)：RSI超卖 + MACD拐头 + KDJ + 布林带"""
    score = 0.0

    # RSI (6分) — 30-45最佳买入区
    if 30 <= rsi <= 40:       score += 6.0
    elif 25 <= rsi < 30:      score += 4.0
    elif rsi < 25:            score += 2.0
    elif 40 < rsi <= 45:      score += 4.0
    elif 45 < rsi <= 50:      score += 3.0
    elif 50 < rsi <= 60:      score += 2.0
    else:                     score += 1.0

    # MACD (4分)
    if dif > dea:
        score += 3.0   # 金叉
        if hist > 0:
            score += 1.0  # 动能确认
    elif dif < dea and abs(dea) > 0.001 and abs(dif - dea) / max(abs(dea), 0.001) < 0.05:
        score += 1.0   # 即将金叉

    # KDJ (3分)
    if kdj_j < 0:            score += 3.0
    elif kdj_j < 20:         score += 2.0
    if kdj_k > kdj_d and kdj_k < 30: score += 1.0

    # 布林带 (2分)
    if bb_score >= 3:        score += 2.0
    elif bb_score >= 2:      score += 1.0

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
        AND ((SELECT MAX(date) FROM fund_nav WHERE code=b.code) < ?
             OR NOT EXISTS (SELECT 1 FROM fund_nav WHERE code=b.code))
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
            try:
                f.result()
            except Exception as e:
                print(f"  thread error: {e}", flush=True)

    print(f"  NAV done: {fetched[0]}/{len(stale_codes)}", flush=True)
    update_signals()
    print(f"[{datetime.now()}] Refresh complete", flush=True)


def refresh_daily():
    """每日轻量刷新：只拉取净值过期的基金，只更新有变化的信号（约 3-10 分钟）"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = get_connection()
    # 找净值落后的指数基金（排除C/E类收费份额）
    stale = conn.execute("""
        SELECT b.code FROM fund_basic b
        WHERE b.fund_type LIKE ?
        AND b.name NOT LIKE '%C' AND b.name NOT LIKE '%C类%' AND b.name NOT LIKE '%E'
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
        try:
            df = fetch_fund_nav(code)
            if not df.empty:
                df = clean_nav_data(df)
                save_nav_data(df)
                updated_codes.append(code)
        except Exception as e:
            print(f"  fetch error [{code}]: {e}", flush=True)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(stale_codes)}", flush=True)

    print(f"  NAV updated: {len(updated_codes)}/{len(stale_codes)}", flush=True)

    # 只更新有净值变化的基金的信号
    if updated_codes:
        _update_signals_for_codes(updated_codes)
    print(f"[{datetime.now()}] Daily refresh complete", flush=True)


def update_signals():
    """全量更新指数基金信号（排除C/E类收费份额）"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE ? AND name NOT LIKE '%C' AND name NOT LIKE '%C类%' AND name NOT LIKE '%E'",
        (FUND_TYPE_FILTER + "%",)
    ).fetchall()]
    conn.close()
    _update_signals_for_codes(codes)


def _update_signals_for_codes(codes: list):
    """批量更新信号（优化版：单连接 + 批量预读NAV）"""
    total = len(codes)
    conn = get_connection()

    for i, code in enumerate(codes):
        # 直接在此处读取NAV，复用同一个连接
        rows = conn.execute(
            "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
            (code,)
        ).fetchall()
        if len(rows) < 20:
            continue

        df = _calc_signals_from_rows(rows)
        if df.empty:
            continue

        last = df.iloc[-1]
        try:
            conn.execute("""
                INSERT OR REPLACE INTO fund_signal
                (code, date, unit_nav, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, rsi14,
                 bb_upper, bb_mid, bb_lower, kdj_k, kdj_d, kdj_j, bb_width, atr14, ma60_slope)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, str(last["date"]),
                float(last.get("unit_nav", 0) or 0),
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

        if (i + 1) % 500 == 0:
            print(f"  signals: {i + 1}/{total}")
            conn.commit()

    conn.commit()
    conn.close()
    print(f"Signals done: {total}")


def _calc_signals_from_rows(rows: list) -> pd.DataFrame:
    """从已加载的净值行计算技术指标（无数据库IO）"""
    from engine.indicators import (
        calc_ma, calc_macd, calc_rsi, calc_bollinger,
        calc_kdj, calc_atr, calc_bb_width,
    )

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

    kdj = calc_kdj(nav, 9, 3, 3)
    df["kdj_k"] = kdj["kdj_k"]
    df["kdj_d"] = kdj["kdj_d"]
    df["kdj_j"] = kdj["kdj_j"]

    df["atr14"] = calc_atr(nav, 14)
    df["bb_width"] = calc_bb_width(nav, 20)

    ma60_s = calc_ma(nav, 60)
    df["ma60_slope"] = ma60_s.diff(20) / ma60_s.shift(20).replace(0, np.nan)
    df["ma60_slope"] = df["ma60_slope"].fillna(0)

    return df


def _calc_signals_for_fund(code: str) -> pd.DataFrame:
    """计算单只基金的信号（独立调用用，打开自己的连接）"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()

    if len(rows) < 20:
        return pd.DataFrame()

    return _calc_signals_from_rows(rows)
