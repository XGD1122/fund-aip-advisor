"""
交易顾问引擎：买入建议 / 卖出信号 / 持仓分析
融合专业投资体系：
  估值定投法 / 阶梯移动止盈 / 多级均线破位 / MACD背离 / 布林带退出
  凯利公式仓位管理 / 风险平价分析 / 组合相关性检查
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from models.database import get_connection
from engine.indicators import (
    calc_nav_percentile, calc_period_return_from_returns,
    calc_volatility, calc_sharpe, calc_calmar, calc_max_drawdown_full,
    detect_macd_divergence, detect_rsi_divergence,
    calc_macd, calc_rsi,
)
from engine.top20 import _identify_sector


def get_sell_signals(code: str, buy_nav: float = None, buy_date: str = None) -> dict:
    """
    9维卖出信号体系（专业增强版）：
    1. 目标止盈 — 固定收益率触发
    2. 移动止盈 — 阶梯式回撤保护（根据浮盈幅度动态调整）
    3. 估值退出 — NAV分位过高触发
    4. 均线破位 — 多级MA体系（MA5→MA10→MA20→MA60→MA120）
    5. MACD顶背离 — 上涨动能衰竭
    6. 布林带卖出 — 上轨超买/中轨破位
    7. 时间止盈 — 持有期效率评估
    8. RSI背离 — 价格动能背离
    + 综合卖出紧迫度评分 (0-100) + 详细操作计划
    """
    conn = get_connection()
    basic = conn.execute("SELECT name FROM fund_basic WHERE code=?", (code,)).fetchone()
    nav_rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date", (code,)
    ).fetchall()
    sig_row = conn.execute(
        "SELECT rsi14, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, "
        "bb_upper, bb_mid, bb_lower, bb_width, kdj_k, kdj_d, kdj_j FROM fund_signal "
        "WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()
    conn.close()

    if len(nav_rows) < 60:
        return {"error": "数据不足", "signals": [], "summary": "数据不足，无法判断",
                "sell_score": 0, "action_plan": None}

    df = pd.DataFrame(nav_rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)

    nav = df["unit_nav"]
    price = (1 + df["daily_return"]).cumprod()
    returns_series = df["daily_return"]
    current_nav = float(nav.iloc[-1])
    current_date = str(df.iloc[-1]["date"])
    n = len(price)

    signals = []
    sell_score = 0  # 综合卖出紧迫度 0-100
    monitor_items = []
    triggered_reasons = []  # 记录触发卖出的原因，用于统一决策

    # 提取技术指标
    rsi = float(sig_row["rsi14"]) if sig_row and sig_row["rsi14"] else 50
    dif = float(sig_row["macd_dif"]) if sig_row and sig_row["macd_dif"] else 0
    dea = float(sig_row["macd_dea"]) if sig_row and sig_row["macd_dea"] else 0
    hist = float(sig_row["macd_hist"]) if sig_row and sig_row["macd_hist"] else 0
    bb_upper = float(sig_row["bb_upper"]) if sig_row and sig_row["bb_upper"] else 0
    bb_mid = float(sig_row["bb_mid"]) if sig_row and sig_row["bb_mid"] else 0
    bb_lower = float(sig_row["bb_lower"]) if sig_row and sig_row["bb_lower"] else 0
    bb_width_val = float(sig_row["bb_width"]) if sig_row and sig_row["bb_width"] else 0

    # 计算估值分位
    lookback = min(1260, n)
    nav_pct = calc_nav_percentile(price, lookback)

    # 计算均线
    ma5 = float(nav.tail(5).mean()) if n >= 5 else current_nav
    ma10 = float(nav.tail(10).mean()) if n >= 10 else current_nav
    ma20 = float(nav.tail(20).mean()) if n >= 20 else current_nav
    ma60 = float(nav.tail(60).mean()) if n >= 60 else current_nav
    ma120 = float(nav.tail(120).mean()) if n >= 120 else current_nav

    # 计算持有收益
    profit_pct = None
    holding_days = None
    if buy_nav and buy_nav > 0:
        profit_pct = (current_nav - buy_nav) / buy_nav
    if buy_date:
        try:
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
            current_dt = datetime.strptime(current_date, "%Y-%m-%d")
            holding_days = (current_dt - buy_dt).days
        except Exception:
            pass

    # ================================================================
    # 维度1: 目标止盈（持有期调整版：持有越久，止盈阈值越高）
    # ================================================================
    if profit_pct is not None and profit_pct > 0:
        # 持有期调整系数：持有<90天=1.0(严格)，90~365天=1.2(适中)，>365天=1.5(宽容)
        if holding_days is not None:
            if holding_days < 90:
                adj = 1.0
            elif holding_days < 365:
                adj = 1.2
            else:
                adj = 1.5
        else:
            adj = 1.0

        adj_50 = 0.50 * adj
        adj_30 = 0.30 * adj
        adj_20 = 0.20 * adj
        adj_15 = 0.15 * adj

        if profit_pct >= adj_50:
            signals.append({"type": "目标止盈", "level": 3, "icon": "🔴", "weight": 30,
                "msg": f"浮盈 {profit_pct*100:.1f}%（持有{holding_days or '?'}天），超过{adj_50*100:.0f}%极端止盈线"})
            sell_score += 30
            triggered_reasons.append(f"浮盈{profit_pct*100:.0f}%触发{adj_50*100:.0f}%止盈线")
        elif profit_pct >= adj_30:
            signals.append({"type": "目标止盈", "level": 3, "icon": "🔴", "weight": 25,
                "msg": f"浮盈 {profit_pct*100:.1f}%，超过{adj_30*100:.0f}%止盈线"})
            sell_score += 25
            triggered_reasons.append(f"浮盈{profit_pct*100:.0f}%触发{adj_30*100:.0f}%止盈线")
        elif profit_pct >= adj_20:
            signals.append({"type": "目标止盈", "level": 2, "icon": "🟠", "weight": 18,
                "msg": f"浮盈 {profit_pct*100:.1f}%，超过{adj_20*100:.0f}%止盈线"})
            sell_score += 18
            triggered_reasons.append(f"浮盈{profit_pct*100:.0f}%触发{adj_20*100:.0f}%止盈线")
        elif profit_pct >= adj_15:
            signals.append({"type": "目标止盈", "level": 1, "icon": "🟡", "weight": 10,
                "msg": f"浮盈 {profit_pct*100:.1f}%，达到{adj_15*100:.0f}%止盈线，关注锁利时机"})
            sell_score += 10
            triggered_reasons.append(f"浮盈{profit_pct*100:.0f}%触发{adj_15*100:.0f}%止盈线")

    # ================================================================
    # 维度2: 阶梯式移动止盈（降低激活门槛+收紧允许回撤）
    # ================================================================
    if profit_pct is not None and profit_pct > 0.03 and buy_date and buy_nav and buy_nav > 0:
        buy_idx = df[df["date"] >= buy_date].index
        if len(buy_idx) > 0:
            peak_nav = float(nav.iloc[buy_idx[0]:].max())
            dd_from_peak = (current_nav - peak_nav) / peak_nav

            # 根据浮盈幅度确定允许回撤比例（盈越多，止盈越紧）
            if profit_pct >= 0.30:
                allowed_dd = 0.15   # 高利润时收紧止盈
            elif profit_pct >= 0.20:
                allowed_dd = 0.20
            elif profit_pct >= 0.10:
                allowed_dd = 0.28
            elif profit_pct >= 0.05:
                allowed_dd = 0.35
            else:
                allowed_dd = 0.50

            actual_dd_ratio = abs(dd_from_peak) / profit_pct if profit_pct > 0 else 0

            if actual_dd_ratio >= 1.0:  # 回撤超过允许比例
                if profit_pct >= 0.20:
                    signals.append({"type": "移动止盈", "level": 3, "icon": "🔴", "weight": 25,
                        "msg": f"从高点回撤{abs(dd_from_peak)*100:.1f}%，超过允许回撤{allowed_dd*100:.0f}%"})
                    sell_score += 25
                    triggered_reasons.append(f"移动止盈: 回撤{abs(dd_from_peak)*100:.1f}%超过允许值{allowed_dd*100:.0f}%")
                elif profit_pct >= 0.10:
                    signals.append({"type": "移动止盈", "level": 2, "icon": "🟠", "weight": 20,
                        "msg": f"从高点回撤{abs(dd_from_peak)*100:.1f}%，超过允许回撤{allowed_dd*100:.0f}%，注意锁利"})
                    sell_score += 20
                    triggered_reasons.append(f"移动止盈: 回撤超过允许值")
                else:
                    signals.append({"type": "移动止盈", "level": 1, "icon": "🟡", "weight": 10,
                        "msg": f"从高点回撤{abs(dd_from_peak)*100:.1f}%，超过允许值，考虑保本"})
                    sell_score += 10
                    triggered_reasons.append(f"移动止盈: 保本锁定")
            elif actual_dd_ratio >= 0.5:
                monitor_items.append(f"移动止盈关注: 当前回撤{abs(dd_from_peak)*100:.1f}%，接近允许值{allowed_dd*100:.0f}%的一半")

    # ================================================================
    # 维度3: 估值退出
    # ================================================================
    if nav_pct > 0.90:
        signals.append({"type": "估值退出", "level": 3, "icon": "🔴", "weight": 20,
            "msg": f"NAV分位{nav_pct*100:.0f}%，极度高估(>90%)"})
        sell_score += 20
        triggered_reasons.append(f"估值分位{nav_pct*100:.0f}%触发>90%清仓线")
    elif nav_pct > 0.80:
        signals.append({"type": "估值退出", "level": 2, "icon": "🟠", "weight": 15,
            "msg": f"NAV分位{nav_pct*100:.0f}%，高估(80-90%)"})
        sell_score += 15
        triggered_reasons.append(f"估值分位{nav_pct*100:.0f}%偏高")
    elif nav_pct > 0.70:
        signals.append({"type": "估值退出", "level": 1, "icon": "🟡", "weight": 10,
            "msg": f"NAV分位{nav_pct*100:.0f}%，估值偏高(70-80%)"})
        sell_score += 10
        triggered_reasons.append(f"估值分位{nav_pct*100:.0f}%进入偏高区")
    elif nav_pct > 0.60:
        monitor_items.append(f"估值关注: NAV分位{nav_pct*100:.0f}%，接近偏高区间")

    # ================================================================
    # 维度4: 多级均线破位
    # ================================================================
    ma_signals = []
    if n >= 120:
        if current_nav < ma120:
            ma_signals.append(("MA120", 3, "🔴", 15, f"跌破MA120({ma120:.4f})年线支撑"))
            sell_score += 15
            triggered_reasons.append(f"跌破MA120年线({ma120:.4f})")
        elif current_nav < ma60:
            ma_signals.append(("MA60", 2, "🟠", 10, f"跌破MA60({ma60:.4f})季线"))
            sell_score += 10
            triggered_reasons.append(f"跌破MA60季线({ma60:.4f})")
        elif current_nav < ma20:
            ma_signals.append(("MA20", 1, "🟡", 5, f"跌破MA20({ma20:.4f})月线"))
            sell_score += 5
            triggered_reasons.append(f"跌破MA20月线({ma20:.4f})")
        elif current_nav < ma10:
            ma_signals.append(("MA10", 0, "🟡", 3, f"跌破MA10({ma10:.4f})，短期走弱，关注"))
            monitor_items.append(f"短期走弱: 价格低于MA10({ma10:.4f})")

    for m in ma_signals:
        signals.append({"type": "均线破位", "level": m[1], "icon": m[2], "weight": m[3], "msg": m[4]})
        if m[1] >= 2:
            break  # 只显示最严重的破位信号

    # ================================================================
    # 维度5: MACD顶背离（真实背离检测，非简化的高位死叉判断）
    # ================================================================
    if sig_row and n >= 80:
        # 构建完整MACD序列用于背离检测
        macd_full = calc_macd(nav)
        divergence = detect_macd_divergence(nav, macd_full["macd_dif"], lookback=min(80, n))
        if divergence["type"] == "bearish" and divergence["strength"] > 0.3:
            sell_score += 10
            signals.append({"type": "MACD背离", "level": 2, "icon": "🟠", "weight": 10,
                "msg": f"MACD顶背离(强度{divergence['strength']:.1f})，上涨动能衰竭"})
            if rsi > 65:
                triggered_reasons.append("MACD顶背离+RSI偏高")
            else:
                monitor_items.append("MACD顶背离: 关注是否进一步确认")
        elif divergence["type"] == "bearish":
            monitor_items.append("MACD: 弱顶背离信号，等待确认")

    # ================================================================
    # 维度5.5: RSI背离
    # ================================================================
    if sig_row and n >= 60:
        rsi_div = detect_rsi_divergence(nav, calc_rsi(nav, 14), lookback=min(60, n))
        if rsi_div["type"] == "bearish" and rsi_div["strength"] > 0.3:
            sell_score += 8
            signals.append({"type": "RSI背离", "level": 2, "icon": "🟠", "weight": 8,
                "msg": f"RSI顶背离(强度{rsi_div['strength']:.1f})，价格动能背离"})
            monitor_items.append("RSI顶背离: 价格新高但RSI未确认")

    # ================================================================
    # 维度6: 布林带卖出信号
    # ================================================================
    if bb_upper > 0 and bb_mid > 0:
        if current_nav >= bb_upper * 0.99 and rsi > 65:
            signals.append({"type": "布林带", "level": 1, "icon": "🟡", "weight": 5,
                "msg": f"价格触及布林上轨+RSI={rsi:.0f}偏高，短期超买"})
            sell_score += 5
            monitor_items.append("布林带上轨超买，注意短期回调风险")
        elif current_nav < bb_mid and current_nav > bb_lower:
            # 从中轨上方跌回中轨下方
            prev_nav_val = float(nav.iloc[-2]) if len(nav) >= 2 else current_nav
            if prev_nav_val > bb_mid:
                signals.append({"type": "布林带", "level": 1, "icon": "🟡", "weight": 5,
                    "msg": "价格跌破布林中轨，短期趋势转弱"})
                sell_score += 5

    # ================================================================
    # 维度7: 时间止盈
    # ================================================================
    if holding_days is not None and profit_pct is not None:
        if holding_days < 30 and profit_pct > 0.10:
            signals.append({"type": "时间止盈", "level": 1, "icon": "🟡", "weight": 5,
                "msg": f"持有仅{holding_days}天浮盈{profit_pct*100:.1f}%，短期暴利需关注"})
            sell_score += 5
            triggered_reasons.append(f"短期暴利(持有{holding_days}天浮盈{profit_pct*100:.0f}%)")
        elif holding_days > 365 and profit_pct < 0.05:
            signals.append({"type": "时间止盈", "level": 0, "icon": "🟡", "weight": 3,
                "msg": f"持有超1年仅盈利{profit_pct*100:.1f}%，资金效率低，可考虑换仓"})
            monitor_items.append("资金效率: 持有超1年收益有限，关注换仓机会")

    # ================================================================
    # 维度8: RSI超买/背离
    # ================================================================
    if rsi > 75:
        signals.append({"type": "RSI", "level": 1, "icon": "🟡", "weight": 5,
            "msg": f"RSI={rsi:.0f}进入超买区(>75)，短期回调概率大"})
        sell_score += 5
        monitor_items.append(f"RSI超买: {rsi:.0f}，关注是否形成顶背离")
    elif rsi > 70:
        monitor_items.append(f"RSI偏高: {rsi:.0f}，接近超买区")

    # ================================================================
    # 综合判断（统一层级系统，summary 与 suggested_sell_pct 永远对齐）
    # 专业原则：单一信号不构成卖出决策，需综合评分驱动
    # ================================================================
    sell_score = min(100, sell_score)

    if sell_score >= 70:
        summary = "强烈建议清仓"
        suggested_sell_pct = 100
        action = "全部清仓"
    elif sell_score >= 45:
        summary = "建议减仓"
        suggested_sell_pct = 50
        action = "卖出1/2仓位"
    elif sell_score >= 20:
        summary = "关注"
        suggested_sell_pct = 0   # 关注但不建议立即操作
        action = None
    else:
        summary = "继续持有"
        suggested_sell_pct = 0   # 安心持有
        action = None

    # 如果没有卖出信号，补充持有提示
    if not signals:
        signals.append({"type": "持有", "level": 0, "icon": "🟢", "weight": 0,
            "msg": "当前无明显卖出信号，建议继续持有观望"})

    # 构建统一操作计划（仅当有值得关注的信号时）
    action_plan = None
    if sell_score >= 20:
        plan = {
            "level": "清仓" if sell_score >= 70 else "减仓" if sell_score >= 45 else "关注",
            "action": action,
            "suggested_sell_pct": suggested_sell_pct,
            "triggered_reasons": triggered_reasons[:5],
            "monitor_items": monitor_items[:5],
            "signals_summary": [s["msg"] for s in signals[:5] if s.get("weight", 0) > 0],
            "next_review_date": (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
        }
        action_plan = plan

    return {
        "code": code,
        "name": basic["name"] if basic else code,
        "current_nav": round(current_nav, 4),
        "current_date": current_date,
        "profit_pct": round(profit_pct * 100, 2) if profit_pct is not None else None,
        "holding_days": holding_days,
        "nav_pct": round(nav_pct * 100, 1),
        "rsi": round(rsi, 1),
        "signals": signals,
        "summary": summary,
        "sell_score": sell_score,
        "suggested_sell_pct": suggested_sell_pct,
        "action_plan": action_plan,
        "technicals": {
            "ma5": round(ma5, 4), "ma10": round(ma10, 4),
            "ma20": round(ma20, 4), "ma60": round(ma60, 4), "ma120": round(ma120, 4),
            "bb_upper": round(bb_upper, 4), "bb_mid": round(bb_mid, 4), "bb_lower": round(bb_lower, 4),
        }
    }


def get_buy_advice(code: str) -> dict:
    """
    生成买入建议（增强版）：
    估值状态 + 定投倍数 + 入场时机 + 仓位比例 + 分批计划 + 网格参数
    """
    conn = get_connection()
    basic = conn.execute(
        "SELECT name, fund_type FROM fund_basic WHERE code=?", (code,)
    ).fetchone()
    if not basic:
        return {"error": "基金不存在"}

    nav_rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date", (code,)
    ).fetchall()

    sig_row = conn.execute(
        "SELECT rsi14, ma5, ma20, ma60, ma120, macd_dif, macd_dea, macd_hist, "
        "bb_upper, bb_mid, bb_lower, bb_width, kdj_k, kdj_d, kdj_j, atr14 "
        "FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()

    holdings = conn.execute(
        "SELECT * FROM portfolio WHERE code=? AND (status IS NULL OR status='active' OR status='')",
        (code,)
    ).fetchall()
    already_hold = len(holdings) > 0
    conn.close()

    if len(nav_rows) < 120:
        if already_hold:
            return {"code": code, "name": basic["name"], "buy_urgency": "已持有，数据不足无法评估加仓",
                    "suggested_position": "已有持仓", "dca_multiplier": 0, "already_hold": True}
        return {"error": "数据不足（少于120个交易日），不建议参与"}
        return {"error": "数据不足（少于120个交易日），不建议参与"}

    df = pd.DataFrame(nav_rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)

    nav = df["unit_nav"]
    price = (1 + df["daily_return"]).cumprod()
    n = len(price)
    current_nav = float(nav.iloc[-1])
    returns_series = df["daily_return"]

    # 估值分位
    lookback = min(1260, n)
    nav_pct = calc_nav_percentile(price, lookback)

    # 均线支撑位
    ma60 = float(nav.tail(60).mean()) if n >= 60 else current_nav
    ma120 = float(nav.tail(120).mean()) if n >= 120 else current_nav
    ma240 = float(nav.tail(240).mean()) if n >= 240 else current_nav

    # 技术指标
    rsi = float(sig_row["rsi14"]) if sig_row and sig_row["rsi14"] else 50
    dif = float(sig_row["macd_dif"]) if sig_row and sig_row["macd_dif"] else 0
    dea = float(sig_row["macd_dea"]) if sig_row and sig_row["macd_dea"] else 0
    hist = float(sig_row["macd_hist"]) if sig_row and sig_row["macd_hist"] else 0
    bb_upper = float(sig_row["bb_upper"]) if sig_row and sig_row["bb_upper"] else 0
    bb_mid = float(sig_row["bb_mid"]) if sig_row and sig_row["bb_mid"] else 0
    bb_lower = float(sig_row["bb_lower"]) if sig_row and sig_row["bb_lower"] else 0
    bb_width_val = float(sig_row["bb_width"]) if sig_row and sig_row["bb_width"] else 0
    kdj_k = float(sig_row["kdj_k"]) if sig_row and sig_row["kdj_k"] else 50
    kdj_d = float(sig_row["kdj_d"]) if sig_row and sig_row["kdj_d"] else 50
    kdj_j = float(sig_row["kdj_j"]) if sig_row and sig_row["kdj_j"] else 50
    atr14 = float(sig_row["atr14"]) if sig_row and sig_row["atr14"] else 0

    # 周期收益
    r60d = calc_period_return_from_returns(returns_series, min(60, n))
    r1y = calc_period_return_from_returns(returns_series, min(252, n))

    # 波动率
    annual_vol = calc_volatility(returns_series) if n >= 60 else 0

    # 估值状态 + 定投倍数（专业估值定投法）
    if nav_pct <= 0.05:
        valuation_label = "五年一遇极度低估"
        buy_urgency = "重仓买入（2倍定投）"
        suggested_position = "25%~35%仓位"
        dca_multiplier = 2.0
    elif nav_pct <= 0.10:
        valuation_label = "极度低估"
        buy_urgency = "强烈建议买入（1.5倍定投）"
        suggested_position = "20%~30%仓位"
        dca_multiplier = 1.5
    elif nav_pct <= 0.20:
        valuation_label = "明显低估"
        buy_urgency = "建议买入（1.2倍定投）"
        suggested_position = "15%~20%仓位"
        dca_multiplier = 1.2
    elif nav_pct <= 0.30:
        valuation_label = "低估"
        buy_urgency = "可以买入"
        suggested_position = "10%~15%仓位"
        dca_multiplier = 1.0
    elif nav_pct <= 0.40:
        valuation_label = "偏低"
        buy_urgency = "可少量买入"
        suggested_position = "5%~10%仓位"
        dca_multiplier = 0.7
    elif nav_pct <= 0.50:
        valuation_label = "合理偏低"
        buy_urgency = "观望，等回调再买"
        suggested_position = "暂不加仓"
        dca_multiplier = 0.3
    elif nav_pct <= 0.60:
        valuation_label = "合理"
        buy_urgency = "不建议买入"
        suggested_position = "暂不加仓"
        dca_multiplier = 0
    elif nav_pct <= 0.70:
        valuation_label = "偏高"
        buy_urgency = "不建议买入，建议等待"
        suggested_position = "不买"
        dca_multiplier = 0
    elif nav_pct <= 0.80:
        valuation_label = "高估"
        buy_urgency = "不建议买入，等待回调15%+"
        suggested_position = "不买"
        dca_multiplier = 0
    else:
        valuation_label = "极度高估"
        buy_urgency = "严禁买入，考虑卖出"
        suggested_position = "不买"
        dca_multiplier = 0

    # 入场价位建议（多级支撑位）
    entry_points = []
    if bb_lower > 0 and current_nav > bb_lower:
        entry_points.append({"level": "布林下轨", "price": round(bb_lower, 4), "label": "布林带下轨支撑（强支撑）"})
    if current_nav > ma60:
        entry_points.append({"level": "保守", "price": round(ma60, 4), "label": "MA60季线支撑"})
    if current_nav > ma120:
        entry_points.append({"level": "安全边际", "price": round(ma120, 4), "label": "MA120半年线（格雷厄姆安全边际）"})
    if current_nav > ma240:
        entry_points.append({"level": "极端机会", "price": round(ma240, 4), "label": "MA240年线（历史大底级别）"})
    if nav_pct <= 0.30:
        entry_points.insert(0, {"level": "现价", "price": round(current_nav, 4), "label": "低估区间，现价可建底仓"})

    # 分批建议
    if nav_pct <= 0.10:
        batch_plan = f"分3批买入：第一批现价建40%底仓，第二批MA60({ma60:.4f})加仓30%，第三批MA120({ma120:.4f})补仓30%"
    elif nav_pct <= 0.20:
        batch_plan = f"分2~3批买入：第一批现价建30%底仓，第二批MA60({ma60:.4f})附近加40%，第三批MA120({ma120:.4f})补30%"
    elif nav_pct <= 0.30:
        batch_plan = f"分2批买入：一半现价，一半等回调到MA60({ma60:.4f})附近"
    elif nav_pct <= 0.40:
        batch_plan = f"等回调到MA60({ma60:.4f})以下再建仓，分2批买入"
    else:
        batch_plan = f"当前估值偏高，建议加入自选，等回调10%~15%至MA60({ma60:.4f})附近再考虑"

    # 网格交易参数建议
    grid_params = None
    if nav_pct <= 0.40 and annual_vol > 0 and current_nav > 0:
        grid_spacing = max(0.015, min(0.04, annual_vol / 16))  # 基于波动率算网格间距
        grid_low = round(current_nav * 0.85, 4)
        grid_high = round(current_nav * 1.15, 4)
        grid_params = {
            "spacing": round(grid_spacing * 100, 1),
            "lower": grid_low,
            "upper": grid_high,
            "suggested_grids": max(5, int((grid_high - grid_low) / (current_nav * grid_spacing))),
            "note": "波动率自适应网格，震荡市中捕捉波段收益"
        }

    # 风险提示
    risks = []
    if rsi < 25:
        risks.append(f"RSI={rsi:.0f}严重超卖，需排查是否为趋势性下跌而非价值回归")
    elif rsi < 30:
        risks.append(f"RSI极度超卖（{rsi:.0f}），可能有潜在利空，建仓前请确认基本面")
    if r60d < -0.25:
        risks.append(f"近60日跌幅{r60d*100:.1f}%，需警惕是否为趋势性下跌而非回调，建议等待企稳信号")
    elif r60d < -0.15:
        risks.append(f"近60日跌幅{r60d*100:.1f}%，回调幅度较大，关注止跌信号")
    if r1y > 0.30:
        risks.append(f"近1年涨幅{r1y*100:.1f}%，追高风险较大，建议等待充分回调")
    if annual_vol > 0.35:
        risks.append(f"年化波动率{annual_vol*100:.0f}%，属于高波动品种，仓位不宜过重")
    if kdj_j < 0:
        risks.append("KDJ的J值<0，极度超卖，可能继续下探，建议分3批以上建仓")
    if bb_width_val > 0 and bb_width_val < 0.02:
        risks.append("布林带宽度极窄，即将变盘，建议等方向明确后再操作")

    # 已持有调整：允许低位加仓（摊平成本是定投核心策略）
    if already_hold:
        if dca_multiplier >= 1.5:
            buy_urgency = f"已持有，当前极度低估（{nav_pct*100:.0f}分位），强烈建议加仓摊平成本"
            suggested_position = "加仓至目标仓位的70%~80%"
        elif dca_multiplier >= 1.0:
            buy_urgency = f"已持有，当前估值偏低（{nav_pct*100:.0f}分位），可考虑加仓"
            suggested_position = "加仓至目标仓位的50%~60%"
        elif dca_multiplier >= 0.5:
            buy_urgency = "已持有，当前估值合理，暂不建议追加"
            suggested_position = "维持现有仓位"
        else:
            buy_urgency = "已持有，当前估值偏高，不建议追加"
            suggested_position = "维持现有仓位，关注卖出信号"

    return {
        "code": code,
        "name": basic["name"],
        "current_nav": round(current_nav, 4),
        "valuation": {"pct": round(nav_pct * 100, 1), "label": valuation_label},
        "buy_urgency": buy_urgency,
        "suggested_position": suggested_position,
        "dca_multiplier": dca_multiplier,
        "entry_points": entry_points[:4],
        "batch_plan": batch_plan,
        "grid_params": grid_params,
        "risk_warnings": risks,
        "already_hold": already_hold,
        "indicators": {
            "rsi": round(rsi, 1),
            "ma60": round(ma60, 4),
            "ma120": round(ma120, 4),
            "ma240": round(ma240, 4),
            "r60d": round(r60d * 100, 2),
            "r1y": round(r1y * 100, 2),
            "volatility": round(annual_vol * 100, 1),
            "kdj_k": round(kdj_k, 1),
            "kdj_d": round(kdj_d, 1),
            "kdj_j": round(kdj_j, 1),
            "bb_upper": round(bb_upper, 4),
            "bb_lower": round(bb_lower, 4),
            "macd_signal": "金叉" if dif > dea else "死叉",
        },
    }


def analyze_portfolio() -> dict:
    """
    持仓组合分析（专业增强版）：
    风险指标 / 相关性检查 / 仓位评分 / 再平衡清单 / 现金管理
    """
    conn = get_connection()
    holdings = conn.execute(
        "SELECT id, code, name, buy_date, buy_nav, shares, buy_amount FROM portfolio WHERE status IS NULL OR status='active' OR status='' ORDER BY buy_date"
    ).fetchall()
    conn.close()

    if not holdings:
        return {"status": "empty", "message": "暂无持仓记录", "holdings_count": 0}

    total_invested = 0
    total_value = 0
    details = []
    sector_allocation = {}
    returns_by_code = {}  # 用于相关性计算

    # 批量获取所有持仓的净值数据（避免N+1查询）
    conn2 = get_connection()
    codes = [h["code"] for h in holdings]

    # 批量获取最新净值
    placeholders = ",".join(["?" for _ in codes])
    nav_rows = conn2.execute(
        f"SELECT code, unit_nav, date FROM fund_nav WHERE code IN ({placeholders}) AND (code, date) IN "
        f"(SELECT code, MAX(date) FROM fund_nav WHERE code IN ({placeholders}) GROUP BY code)",
        codes + codes
    ).fetchall()
    nav_map = {r["code"]: (r["unit_nav"], r["date"]) for r in nav_rows}

    # 批量获取近1年日收益
    ret_rows = conn2.execute(
        f"SELECT code, daily_return FROM fund_nav WHERE code IN ({placeholders}) "
        f"AND date >= date('now', '-252 days') ORDER BY code, date",
        codes
    ).fetchall()
    ret_map = {}
    for r in ret_rows:
        code = r["code"]
        ret_map.setdefault(code, []).append(float(r["daily_return"] or 0))
    conn2.close()

    for h in holdings:
        code = h["code"]
        buy_nav = float(h["buy_nav"])
        shares = float(h["shares"]) if h["shares"] else 0
        buy_amount = float(h["buy_amount"]) if h["buy_amount"] else buy_nav * shares

        if buy_amount == 0 and shares > 0:
            buy_amount = buy_nav * shares
            shares = buy_amount / buy_nav if buy_nav > 0 else 0

        total_invested += buy_amount

        # 使用批量查询结果
        nav_info = nav_map.get(code)
        current_nav = float(nav_info[0]) if nav_info else buy_nav
        current_date = str(nav_info[1]) if nav_info else "N/A"

        if shares == 0 and buy_nav > 0:
            shares = buy_amount / buy_nav

        current_value = shares * current_nav
        total_value += current_value
        profit = current_value - buy_amount
        profit_pct = (profit / buy_amount * 100) if buy_amount > 0 else 0

        # 存储日收益序列
        ret_list = ret_map.get(code, [])
        if ret_list:
            returns_by_code[code] = pd.Series(ret_list)

        # 赛道分类
        name = h["name"] or ""
        sector = _identify_sector(name)
        sector_allocation.setdefault(sector, 0)
        sector_allocation[sector] += current_value

        # 卖出信号（8维增强版）
        sell = get_sell_signals(code, buy_nav, h["buy_date"])

        # 单只仓位占比（先暂存，后面统一计算）
        details.append({
            "id": h["id"],
            "code": code,
            "name": name,
            "buy_date": h["buy_date"],
            "buy_nav": round(buy_nav, 4),
            "current_nav": round(current_nav, 4),
            "shares": round(shares, 2),
            "buy_amount": round(buy_amount, 2),
            "current_value": round(current_value, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "position_pct": 0,  # 计算完 total_value 后更新
            "sector": sector,
            "nav_pct": sell.get("nav_pct", 50),
            "sell_summary": sell.get("summary", ""),
            "sell_score": sell.get("sell_score", 0),
            "sell_signals": sell.get("signals", []),
            "suggested_sell_pct": sell.get("suggested_sell_pct", 0),
            "sell_action_plan": sell.get("action_plan"),
        })

    total_profit = total_value - total_invested
    total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0

    # 计算仓位占比（使用最终 total_value）
    for d in details:
        d["position_pct"] = round(d["current_value"] / total_value * 100, 1) if total_value > 0 else 0

    # ================================================================
    # 赛道集中度分析
    # ================================================================
    sector_detail = {}
    for sec, val in sector_allocation.items():
        pct = val / total_value * 100 if total_value > 0 else 0
        sector_detail[sec] = {"value": round(val, 2), "pct": round(pct, 1)}

    # ================================================================
    # 组合风险指标
    # ================================================================
    risk_metrics = {}
    warnings = []

    # 加权平均波动率
    if returns_by_code:
        total_vol = 0
        for d in details:
            code = d["code"]
            if code in returns_by_code:
                vol = calc_volatility(returns_by_code[code]) if len(returns_by_code[code]) >= 60 else 0
                total_vol += vol * d["position_pct"] / 100
        risk_metrics["portfolio_volatility"] = round(total_vol * 100, 1)
        if total_vol > 0.30:
            warnings.append(f"组合波动率{total_vol*100:.0f}%，偏高，建议降低权益仓位或增加低波动品种")
    else:
        risk_metrics["portfolio_volatility"] = 0

    # 集中度预警（收紧到25%）
    for sec, info in sector_detail.items():
        if info["pct"] > 40:
            warnings.append(f"赛道「{sec}」占比{info['pct']}%，严重超标(>40%)，建议立即分散")
        elif info["pct"] > 25:
            warnings.append(f"赛道「{sec}」占比{info['pct']}%，超过25%警戒线，建议分散配置")

    # 单只基金集中度
    for d in details:
        if d["position_pct"] > 25:
            warnings.append(f"「{d['name']}」单只占比{d['position_pct']}%，超过25%，建议降低集中度")
        elif d["position_pct"] > 20:
            warnings.append(f"「{d['name']}」单只占比{d['position_pct']}%，接近20%上限，关注")

    # ================================================================
    # 相关性分析
    # ================================================================
    correlation_warnings = []
    if len(returns_by_code) >= 2:
        codes_list = list(returns_by_code.keys())
        for i in range(len(codes_list)):
            for j in range(i + 1, len(codes_list)):
                c1, c2 = codes_list[i], codes_list[j]
                r1, r2 = returns_by_code[c1], returns_by_code[c2]
                min_len = min(len(r1), len(r2))
                if min_len >= 60:
                    corr = float(r1.tail(min_len).corr(r2.tail(min_len)))
                    if corr > 0.85:
                        n1 = next((d["name"] for d in details if d["code"] == c1), c1)
                        n2 = next((d["name"] for d in details if d["code"] == c2), c2)
                        correlation_warnings.append({
                            "pair": [n1, n2],
                            "correlation": round(corr, 2),
                            "severity": "high" if corr > 0.9 else "medium",
                            "msg": f"「{n1}」与「{n2}」相关性{corr:.2f}，高度同质化，建议保留一只"
                        })

    # ================================================================
    # 仓位合理性评分
    # ================================================================
    # 基于持仓基金的平均估值分位给出建议仓位（复用已计算的数据）
    nav_pcts = [d["nav_pct"] for d in details if d.get("nav_pct") is not None]
    avg_nav_pct = sum(nav_pcts) / len(nav_pcts) if nav_pcts else 50

    # 基于平均估值分位的建议仓位
    if avg_nav_pct < 20:
        suggested_equity_pct = 85
    elif avg_nav_pct < 40:
        suggested_equity_pct = 70
    elif avg_nav_pct < 60:
        suggested_equity_pct = 50
    elif avg_nav_pct < 80:
        suggested_equity_pct = 30
    else:
        suggested_equity_pct = 15

    cash_advice = {
        "suggested_equity_pct": suggested_equity_pct,
        "suggested_cash_pct": 100 - suggested_equity_pct,
        "avg_valuation_pct": round(avg_nav_pct, 1),
        "note": f"基于持仓平均估值分位{avg_nav_pct:.0f}%，建议权益仓位{suggested_equity_pct}%，现金{100-suggested_equity_pct}%"
    }

    # ================================================================
    # 再平衡建议（增强）
    # ================================================================
    rebalance = ""
    rebalance_actions = []

    if len(details) == 1:
        if details[0]["profit_pct"] > 20:
            rebalance = "仅持有一只基金且盈利可观，建议先部分止盈，将资金分配到2-3个低估值赛道"
        else:
            rebalance = "仅持有一只基金，风险集中。建议从Top20中选择2-3个不同赛道的基金分散配置"
    elif len(details) >= 3 and total_profit_pct > 15:
        rebalance = "组合整体盈利较好，可以考虑卖出部分盈利较高的持仓，买入当前低估值的赛道进行再平衡"
    elif len(details) >= 3 and len(warnings) > 0:
        rebalance = "赛道集中度过高，建议减持占比过大的赛道，增加低相关性的其他赛道"
    elif len(correlation_warnings) > 0:
        rebalance = "持仓相关性过高，建议合并同质化持仓，释放资金配置到低相关性赛道"
    else:
        rebalance = "组合结构合理，保持观察，等待卖出信号"

    # 生成再平衡操作清单
    if len(warnings) > 0 or len(correlation_warnings) > 0:
        # 找出占比最大的赛道/基金
        for sec, info in sorted(sector_detail.items(), key=lambda x: x[1]["pct"], reverse=True):
            if info["pct"] > 25:
                rebalance_actions.append({
                    "action": f"减持「{sec}」赛道",
                    "detail": f"当前占比{info['pct']}%，建议降至25%以下",
                    "priority": "high" if info["pct"] > 40 else "medium"
                })
        for cw in correlation_warnings:
            if cw["severity"] == "high":
                rebalance_actions.append({
                    "action": "合并同质化持仓",
                    "detail": cw["msg"],
                    "priority": "high"
                })

    # ================================================================
    # 卖出优先度排序
    # ================================================================
    sell_priority = sorted(
        [d for d in details if d["sell_score"] >= 30],
        key=lambda x: x["sell_score"], reverse=True
    )

    return {
        "status": "ok",
        "holdings_count": len(details),
        "total_invested": round(total_invested, 2),
        "total_value": round(total_value, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "details": details,
        "sector_allocation": sector_detail,
        "risk_metrics": risk_metrics,
        "correlation_warnings": correlation_warnings,
        "warnings": warnings,
        "rebalance_advice": rebalance,
        "rebalance_actions": rebalance_actions[:5],
        "sell_priority": sell_priority[:5],
        "cash_advice": cash_advice,
    }
