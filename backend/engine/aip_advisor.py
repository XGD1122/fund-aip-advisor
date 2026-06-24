"""
定投时机顾问引擎 (AIP Timing Advisor)

为每只指数基金生成独立的买入/卖出时机信号、定投额度建议、止盈判断。
"""

import pandas as pd
import numpy as np
from models.database import get_connection
from engine.indicators import (
    calc_nav_percentile, calc_ma_slope, calc_short_term_surge,
    calc_ma_deviation_multi, calc_max_drawdown, calc_volatility,
    calc_period_return,
)
from config import (
    BUY_PE_PERCENTILE, BUY_OVERSOLD_DRAWDOWN, BUY_OVERSOLD_RSI,
    BUY_MA120_SUPPORT_DEVIATION,
    SELL_PE_PERCENTILE, SELL_TREND_BREAK_SLOPE, SELL_SURGE_3M,
    SELL_OVERBOUGHT_RSI,
    AIP_MULTIPLIER_DOUBLE, AIP_MULTIPLIER_INCREASE,
    AIP_MULTIPLIER_NORMAL, AIP_MULTIPLIER_REDUCE, AIP_MULTIPLIER_PAUSE,
    AIP_NORMAL_PE_UPPER,
    STOP_PROFIT_PARTIAL, STOP_PROFIT_FULL, STOP_PROFIT_PE_THRESHOLD,
    TIMING_WEIGHTS, FUND_TYPE_FILTER,
    PE_PERCENTILE_HIGH, PE_PERCENTILE_LOW, PE_PERCENTILE_FAIR, PE_PERCENTILE_WARN,
)


def _get_nav_and_signals(code: str):
    """获取基金的净值数据和最新技术信号"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    signal_row = conn.execute(
        "SELECT * FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1",
        (code,)
    ).fetchone()
    conn.close()

    if len(rows) < 60:
        return None, None

    df = pd.DataFrame(rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)
    signal = dict(signal_row) if signal_row else {}
    return df, signal


def _detect_buy_signals(nav: pd.Series, signal: dict, nav_pct: float) -> list:
    """检测买入信号"""
    signals = []

    # 1. 估值低位信号 (最强)
    if nav_pct * 100 <= BUY_PE_PERCENTILE:
        signals.append({
            "type": "buy",
            "name": "估值低位",
            "icon": "🟢",
            "strength": 3,
            "description": f"PE分位 {nav_pct*100:.1f}% ≤ {BUY_PE_PERCENTILE}%，处于历史低位",
            "action": "建议加倍定投",
        })

    # 2. 超跌反弹信号
    if len(nav) >= 60:
        dd_60 = float(nav.iloc[-1] / nav.rolling(60, min_periods=1).max().iloc[-1] - 1)
        rsi = signal.get("rsi14", 50) or 50
        if abs(dd_60) > BUY_OVERSOLD_DRAWDOWN and rsi < BUY_OVERSOLD_RSI:
            signals.append({
                "type": "buy",
                "name": "超跌反弹",
                "icon": "🟢",
                "strength": 2,
                "description": f"距60日高点回撤 {abs(dd_60)*100:.1f}%，RSI={rsi:.0f} 超卖，恐慌修复机会",
                "action": "可增投",
            })

    # 3. 趋势转好信号 (MA5上穿MA20 + MACD金叉)
    ma5 = signal.get("ma5", 0) or 0
    ma20 = signal.get("ma20", 0) or 0
    macd_dif = signal.get("macd_dif", 0) or 0
    macd_dea = signal.get("macd_dea", 0) or 0
    if ma5 > ma20 and macd_dif > macd_dea and macd_dif > 0:
        signals.append({
            "type": "buy",
            "name": "趋势转好",
            "icon": "🟢",
            "strength": 2,
            "description": "MA5>MA20 且 MACD金叉，短期趋势向上",
            "action": "正常定投",
        })

    # 4. 均线支撑信号 (回踩MA120)
    if len(nav) >= 120:
        ma120_dev = calc_ma_deviation_multi(nav).get("ma120_dev", 0) or 0
        if abs(ma120_dev) < BUY_MA120_SUPPORT_DEVIATION:
            signals.append({
                "type": "buy",
                "name": "均线支撑",
                "icon": "🟢",
                "strength": 1,
                "description": f"净值偏离MA120仅 {abs(ma120_dev)*100:.1f}%，长期均线支撑位",
                "action": "可正常定投",
            })

    return signals


def _detect_sell_signals(nav: pd.Series, signal: dict, nav_pct: float) -> list:
    """检测卖出/减仓信号"""
    signals = []

    # 1. 估值高位信号 (最强)
    if nav_pct * 100 >= SELL_PE_PERCENTILE:
        signals.append({
            "type": "sell",
            "name": "估值高位",
            "icon": "🔴",
            "strength": 3,
            "description": f"PE分位 {nav_pct*100:.1f}% ≥ {SELL_PE_PERCENTILE}%，处于历史高位",
            "action": "暂停定投，考虑减仓",
        })

    # 2. 趋势转坏信号
    ma120_slope = calc_ma_slope(nav, 120, 20)
    ma5 = signal.get("ma5", 0) or 0
    ma20 = signal.get("ma20", 0) or 0
    if ma120_slope < SELL_TREND_BREAK_SLOPE and ma5 < ma20:
        signals.append({
            "type": "sell",
            "name": "趋势转坏",
            "icon": "🔴",
            "strength": 3,
            "description": f"MA120斜率 {ma120_slope*100:.1f}% < {SELL_TREND_BREAK_SLOPE*100:.0f}%，且MA5<MA20，中长期趋势破位",
            "action": "暂停定投",
        })

    # 3. 短期过热信号
    surge = calc_short_term_surge(nav, 66)
    if surge > SELL_SURGE_3M:
        signals.append({
            "type": "sell",
            "name": "短期过热",
            "icon": "🔴",
            "strength": 2,
            "description": f"近3月涨幅 {surge*100:.1f}% > {SELL_SURGE_3M*100:.0f}%，短期涨幅过大",
            "action": "减半定投，等待回调",
        })

    # 4. 超买回落信号
    rsi = signal.get("rsi14", 50) or 50
    macd_dif = signal.get("macd_dif", 0) or 0
    macd_dea = signal.get("macd_dea", 0) or 0
    if rsi > SELL_OVERBOUGHT_RSI and macd_dif < macd_dea:
        signals.append({
            "type": "sell",
            "name": "超买回落",
            "icon": "🔴",
            "strength": 1,
            "description": f"RSI={rsi:.0f} > {SELL_OVERBOUGHT_RSI} 且 MACD死叉，技术面见顶",
            "action": "注意风险，暂不增投",
        })

    return signals


def _calc_amount_multiplier(nav_pct: float, buy_signals: list, sell_signals: list,
                            trend_warning: bool, high_warning: bool) -> float:
    """计算定投额度倍数"""
    pe = nav_pct * 100

    # 暂停条件：高位 + 警告
    if pe >= SELL_PE_PERCENTILE and high_warning:
        return AIP_MULTIPLIER_PAUSE

    # 减半条件：偏高 或 趋势转坏
    if pe >= PE_PERCENTILE_WARN or trend_warning:
        return AIP_MULTIPLIER_REDUCE

    # 加倍条件：低位 + 有买入信号
    if pe <= BUY_PE_PERCENTILE and len(buy_signals) >= 2:
        return AIP_MULTIPLIER_DOUBLE

    # 增投条件：偏低
    if pe <= PE_PERCENTILE_FAIR:
        return AIP_MULTIPLIER_INCREASE

    # 正常
    if pe <= AIP_NORMAL_PE_UPPER:
        return AIP_MULTIPLIER_NORMAL

    # 默认正常
    return AIP_MULTIPLIER_NORMAL


def _calc_stop_profit(nav_pct: float, cost_nav: float = None, current_nav: float = None) -> list:
    """生成止盈建议"""
    if cost_nav is None or current_nav is None or cost_nav <= 0:
        return []
    signals = []
    profit_pct = (current_nav - cost_nav) / cost_nav

    if profit_pct > STOP_PROFIT_FULL and nav_pct * 100 > STOP_PROFIT_PE_THRESHOLD:
        signals.append({
            "type": "stop_profit",
            "name": "全部止盈",
            "icon": "🏁",
            "strength": 3,
            "description": f"累计收益 {profit_pct*100:.1f}% > {STOP_PROFIT_FULL*100:.0f}%，且PE分位>{STOP_PROFIT_PE_THRESHOLD}%，建议全部止盈",
            "action": "卖出全部持仓",
        })
    elif profit_pct > STOP_PROFIT_PARTIAL:
        signals.append({
            "type": "stop_profit",
            "name": "部分止盈",
            "icon": "🏁",
            "strength": 2,
            "description": f"累计收益 {profit_pct*100:.1f}% > {STOP_PROFIT_PARTIAL*100:.0f}%，建议卖出1/3",
            "action": "卖出1/3持仓，锁定利润",
        })

    return signals


def _calc_timing_score(nav_pct: float, buy_signals: list, sell_signals: list,
                       trend_up: bool, vol: float) -> float:
    """计算机时综合评分 (0~100)"""
    # 估值分 (35%)
    pe = nav_pct * 100
    if pe <= 20:
        val_score = 95
    elif pe <= 40:
        val_score = 80
    elif pe <= 70:
        val_score = 60
    elif pe <= 85:
        val_score = 35
    else:
        val_score = 10

    # 趋势分 (25%)
    if trend_up:
        trend_score = 85 + min(15, len(buy_signals) * 5)
    else:
        trend_score = 40 - min(30, len(sell_signals) * 10)

    # 技术信号分 (20%)
    buy_strength = sum(s["strength"] for s in buy_signals)
    sell_strength = sum(s["strength"] for s in sell_signals)
    tech_score = 50 + buy_strength * 12 - sell_strength * 15
    tech_score = max(0, min(100, tech_score))

    # 风险分 (20%) — 波动率惩罚
    if vol < 0.15:
        risk_score = 90
    elif vol < 0.25:
        risk_score = 80
    elif vol < 0.30:
        risk_score = 60
    else:
        risk_score = 30

    total = (
        val_score * TIMING_WEIGHTS["valuation"] +
        trend_score * TIMING_WEIGHTS["trend"] +
        tech_score * TIMING_WEIGHTS["technical"] +
        risk_score * TIMING_WEIGHTS["risk"]
    )
    return round(total, 1)


def get_timing_signals(code: str, cost_nav: float = None) -> dict:
    """获取单只基金的完整时机分析

    Args:
        code: 基金代码
        cost_nav: 用户持仓成本净值（可选，用于止盈计算）

    Returns:
        dict: 包含买入信号、卖出信号、定投建议、止盈建议、时机评分
    """
    df, signal = _get_nav_and_signals(code)
    if df is None:
        return {"code": code, "error": "数据不足", "timing_score": 0}

    nav = df["unit_nav"]
    returns = df["daily_return"]
    current_nav = float(nav.iloc[-1])

    # 核心估值
    nav_pct = calc_nav_percentile(nav, 504)

    # 信号检测
    buy_signals = _detect_buy_signals(nav, signal, nav_pct)
    sell_signals = _detect_sell_signals(nav, signal, nav_pct)

    # 趋势判断
    ma60_slope = calc_ma_slope(nav, 60, 20)
    ma120_slope = calc_ma_slope(nav, 120, 20)
    trend_up = ma60_slope > 0 and ma120_slope > 0
    trend_warning = ma120_slope < SELL_TREND_BREAK_SLOPE

    # 高位警告
    surge = calc_short_term_surge(nav, 66)
    ma_dev = calc_ma_deviation_multi(nav).get("ma120_dev", 0) or 0
    high_warning = (nav_pct * 100 >= SELL_PE_PERCENTILE or
                    surge > SELL_SURGE_3M or abs(ma_dev) > 0.20)

    # 定投倍数
    multiplier = _calc_amount_multiplier(nav_pct, buy_signals, sell_signals,
                                          trend_warning, high_warning)

    # 止盈
    stop_profit_signals = _calc_stop_profit(nav_pct, cost_nav, current_nav)

    # 波动率
    vol = calc_volatility(returns)

    # 时机综合评分
    timing_score = _calc_timing_score(nav_pct, buy_signals, sell_signals, trend_up, vol)

    # 综合建议文本
    if multiplier == 0:
        advice = "⛔ 暂停定投 — 估值高位 + 趋势预警，等待回调后再恢复"
    elif multiplier == 0.5:
        advice = "⚠️ 减半定投 — 估值偏高或趋势不稳，降低投入等待明朗"
    elif multiplier == 2.0:
        advice = "🌟 加倍定投 — 估值低位 + 买入信号共振，难得的加仓时机"
    elif multiplier == 1.5:
        advice = "👍 增投定投 — 估值偏低，适度增加投入"
    else:
        advice = "✅ 正常定投 — 估值合理，按计划执行"

    return {
        "code": code,
        "timing_score": timing_score,
        "nav_percentile_2y": round(nav_pct * 100, 1),
        "current_nav": round(current_nav, 4),
        "trend_up": trend_up,
        "trend_warning": trend_warning,
        "high_warning": high_warning,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "stop_profit_signals": stop_profit_signals,
        "aip_multiplier": multiplier,
        "advice": advice,
        "indicators": {
            "ma60_slope": round(ma60_slope * 100, 2),
            "ma120_slope": round(ma120_slope * 100, 2),
            "surge_3m": round(surge * 100, 1),
            "ma120_deviation": round(ma_dev * 100, 1),
            "volatility": round(vol * 100, 1),
            "rsi14": round(signal.get("rsi14", 50) or 50, 1),
        },
    }


def scan_opportunities(min_timing_score: float = 60, top_n: int = 20) -> list:
    """全市场定投机会扫描

    返回当前有买入信号且时机评分较高的基金列表。
    """
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE ?", (FUND_TYPE_FILTER + "%",)
    ).fetchall()]
    conn.close()

    opportunities = []
    for i, code in enumerate(codes):
        result = get_timing_signals(code)
        if "error" in result:
            continue
        # 只返回有投资价值的（至少没有高位警告）
        if result["high_warning"]:
            continue
        if result["timing_score"] >= min_timing_score:
            opportunities.append({
                "code": code,
                "timing_score": result["timing_score"],
                "nav_percentile_2y": result["nav_percentile_2y"],
                "buy_signals": [s["name"] for s in result["buy_signals"]],
                "buy_count": len(result["buy_signals"]),
                "aip_multiplier": result["aip_multiplier"],
                "trend_up": result["trend_up"],
                "advice": result["advice"],
            })
        if (i + 1) % 200 == 0:
            print(f"  扫描进度: {i+1}/{len(codes)}")

    opportunities.sort(key=lambda x: x["timing_score"], reverse=True)
    return opportunities[:top_n]


def check_portfolio(holdings: list) -> dict:
    """持仓诊断

    Args:
        holdings: [{"code": "000001", "cost_nav": 1.5000, "shares": 1000}, ...]

    Returns:
        dict: 每只基金的诊断结果和组合汇总
    """
    results = []
    total_value = 0
    total_cost = 0

    for h in holdings:
        code = h["code"]
        cost_nav = h.get("cost_nav", 0)
        shares = h.get("shares", 0)

        timing = get_timing_signals(code, cost_nav=cost_nav)
        if "error" in timing:
            continue

        current_nav = timing.get("current_nav", 0)
        market_value = shares * current_nav if current_nav else 0
        cost_value = shares * cost_nav if cost_nav else 0
        profit = market_value - cost_value
        profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0

        total_value += market_value
        total_cost += cost_value

        # 综合建议
        if timing["stop_profit_signals"]:
            action = "止盈"
            action_detail = timing["stop_profit_signals"][0]["action"]
        elif timing["aip_multiplier"] >= 2.0:
            action = "加仓"
            action_detail = "加倍定投"
        elif timing["aip_multiplier"] >= 1.5:
            action = "增投"
            action_detail = "1.5倍定投"
        elif timing["aip_multiplier"] == 0:
            action = "清仓"
            action_detail = "暂停定投，考虑卖出"
        elif timing["aip_multiplier"] == 0.5:
            action = "减仓"
            action_detail = "减半定投"
        else:
            action = "持有"
            action_detail = "正常定投"

        results.append({
            "code": code,
            "cost_nav": cost_nav,
            "current_nav": current_nav,
            "shares": shares,
            "market_value": round(market_value, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 1),
            "timing_score": timing["timing_score"],
            "aip_multiplier": timing["aip_multiplier"],
            "action": action,
            "action_detail": action_detail,
            "buy_signals": [s["name"] for s in timing["buy_signals"]],
            "sell_signals": [s["name"] for s in timing["sell_signals"]],
            "stop_profit_signals": [s["name"] for s in timing["stop_profit_signals"]],
        })

    total_profit = total_value - total_cost
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0

    return {
        "holdings": results,
        "summary": {
            "total_cost": round(total_cost, 2),
            "total_value": round(total_value, 2),
            "total_profit": round(total_profit, 2),
            "total_profit_pct": round(total_profit_pct, 1),
            "fund_count": len(results),
        },
    }
