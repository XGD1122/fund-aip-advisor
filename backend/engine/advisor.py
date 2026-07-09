"""
交易顾问引擎：买入建议 / 卖出信号 / 持仓分析
融合社区"焚决"精华——止盈铁律、回撤止损、估值退出、均线破位
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from models.database import get_connection
from engine.indicators import calc_nav_percentile, calc_period_return_from_returns
from engine.top20 import _identify_sector, SECTOR_KEYWORDS


def get_sell_signals(code: str, buy_nav: float = None, buy_date: str = None) -> dict:
    """对一只基金生成多维度卖出信号"""
    conn = get_connection()
    basic = conn.execute("SELECT name FROM fund_basic WHERE code=?", (code,)).fetchone()
    nav_rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date", (code,)
    ).fetchall()
    sig_row = conn.execute(
        "SELECT rsi14 FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()
    conn.close()

    if len(nav_rows) < 60:
        return {"error": "数据不足", "signals": [], "summary": "数据不足，无法判断"}

    df = pd.DataFrame(nav_rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)

    nav = df["unit_nav"]
    price = (1 + df["daily_return"]).cumprod()
    current_nav = float(nav.iloc[-1])
    current_date = df.iloc[-1]["date"]
    signals = []
    action_level = 0  # 0=持有, 1=关注, 2=减仓, 3=清仓

    # === 1. 目标止盈（有持仓成本时触发） ===
    profit_pct = None
    if buy_nav and buy_nav > 0:
        profit_pct = (current_nav - buy_nav) / buy_nav
        if profit_pct >= 0.30:
            signals.append({"type": "止盈", "level": 3, "icon": "🔴",
                "msg": f"浮盈 {profit_pct*100:.1f}%，超过30%止盈线，建议全部清仓"})
            action_level = max(action_level, 3)
        elif profit_pct >= 0.20:
            signals.append({"type": "止盈", "level": 2, "icon": "🟠",
                "msg": f"浮盈 {profit_pct*100:.1f}%，超过20%止盈线，建议卖出1/2"})
            action_level = max(action_level, 2)
        elif profit_pct >= 0.15:
            signals.append({"type": "止盈", "level": 1, "icon": "🟡",
                "msg": f"浮盈 {profit_pct*100:.1f}%，达到15%止盈线，建议卖出1/3锁定利润"})
            action_level = max(action_level, 1)

    # === 2. 回撤止损（基于买入日期） ===
    if buy_date and buy_nav and buy_nav > 0:
        buy_idx = df[df["date"] >= buy_date].index
        if len(buy_idx) > 0:
            peak_nav = float(nav.iloc[buy_idx[0]:].max())
            dd_from_peak = (current_nav - peak_nav) / peak_nav
            if dd_from_peak <= -0.15:
                signals.append({"type": "止损", "level": 3, "icon": "🔴",
                    "msg": f"从买入后高点回撤 {abs(dd_from_peak)*100:.1f}%，超过15%止损线，建议清仓"})
                action_level = max(action_level, 3)
            elif dd_from_peak <= -0.08:
                signals.append({"type": "止损", "level": 2, "icon": "🟠",
                    "msg": f"从买入后高点回撤 {abs(dd_from_peak)*100:.1f}%，超过8%止损线，建议减仓1/2"})
                action_level = max(action_level, 2)

    # === 3. 估值退出 ===
    n = len(price)
    lookback = min(1260, n)
    nav_pct = calc_nav_percentile(price, lookback)
    if nav_pct > 0.90:
        signals.append({"type": "估值", "level": 3, "icon": "🔴",
            "msg": f"NAV分位 {nav_pct*100:.0f}%，极度高估（>90%），建议全部清仓"})
        action_level = max(action_level, 3)
    elif nav_pct > 0.70:
        signals.append({"type": "估值", "level": 1, "icon": "🟡",
            "msg": f"NAV分位 {nav_pct*100:.0f}%，估值偏高（>70%），建议分批止盈"})
        action_level = max(action_level, 1)

    # === 4. 均线破位 ===
    if n >= 120:
        ma60 = nav.tail(60).mean()
        ma120 = nav.tail(120).mean()
        below_ma60 = current_nav < ma60
        below_ma120 = current_nav < ma120
        if below_ma120 and below_ma60:
            # 检查是否刚跌破（前一日在均线上方）
            prev_nav = float(nav.iloc[-2])
            prev_ma60 = nav.tail(61).head(60).mean() if n >= 61 else ma60
            if prev_nav > prev_ma60:
                signals.append({"type": "均线", "level": 2, "icon": "🟠",
                    "msg": "刚跌破MA60和MA120支撑，趋势转弱，建议减仓"})
                action_level = max(action_level, 2)
            else:
                signals.append({"type": "均线", "level": 1, "icon": "🟡",
                    "msg": "处于MA60和MA120下方，趋势偏弱，关注反弹力度"})
                action_level = max(action_level, 1)

    # === 5. RSI极端信号 ===
    rsi = float(sig_row["rsi14"]) if sig_row and sig_row["rsi14"] else 50
    if rsi > 80:
        signals.append({"type": "RSI", "level": 1, "icon": "🟡",
            "msg": f"RSI={rsi:.0f}，进入超买区，短期可能回调"})

    # 如果没有卖出信号
    if not signals:
        signals.append({"type": "持有", "level": 0, "icon": "🟢",
            "msg": "当前无明显卖出信号，建议继续持有观望"})

    # 综合判断
    level_labels = {0: "继续持有", 1: "关注，准备操作", 2: "建议减仓", 3: "建议清仓"}
    summary = level_labels.get(action_level, "继续持有")

    return {
        "code": code,
        "name": basic["name"] if basic else code,
        "current_nav": round(current_nav, 4),
        "current_date": str(current_date),
        "profit_pct": round(profit_pct * 100, 2) if profit_pct is not None else None,
        "nav_pct": round(nav_pct * 100, 1),
        "rsi": round(rsi, 1),
        "signals": signals,
        "summary": summary,
        "action_level": action_level,
    }


def get_buy_advice(code: str) -> dict:
    """生成买入建议：估值状态 + 入场时机 + 仓位比例"""
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
        "SELECT rsi14, ma5, ma20, ma60, ma120, macd_dif, macd_dea FROM fund_signal "
        "WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()

    # 查已有仓位
    holdings = conn.execute("SELECT * FROM portfolio WHERE code=?", (code,)).fetchall()
    already_hold = len(holdings) > 0
    conn.close()

    if len(nav_rows) < 120:
        return {"error": "数据不足（少于120个交易日），不建议参与"}

    df = pd.DataFrame(nav_rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)

    nav = df["unit_nav"]
    price = (1 + df["daily_return"]).cumprod()
    n = len(price)
    current_nav = float(nav.iloc[-1])

    # 估值分位
    lookback = min(1260, n)
    nav_pct = calc_nav_percentile(price, lookback)

    # 均线支撑位
    ma60 = float(nav.tail(60).mean()) if n >= 60 else current_nav
    ma120 = float(nav.tail(120).mean()) if n >= 120 else current_nav
    ma240 = float(nav.tail(240).mean()) if n >= 240 else current_nav

    # RSI
    rsi = float(sig_row["rsi14"]) if sig_row and sig_row["rsi14"] else 50

    # 近60日跌幅
    returns_series = df["daily_return"]
    r60d = calc_period_return_from_returns(returns_series, min(60, n))
    r1y = calc_period_return_from_returns(returns_series, min(252, n))

    # 估值状态
    if nav_pct <= 0.10:
        valuation_label = "极度低估"
        buy_urgency = "强烈建议买入"
        suggested_position = "20%~30%仓位"
    elif nav_pct <= 0.20:
        valuation_label = "明显低估"
        buy_urgency = "建议买入"
        suggested_position = "15%~20%仓位"
    elif nav_pct <= 0.30:
        valuation_label = "低估"
        buy_urgency = "可以买入"
        suggested_position = "10%~15%仓位"
    elif nav_pct <= 0.40:
        valuation_label = "偏低"
        buy_urgency = "可少量买入"
        suggested_position = "5%~10%仓位"
    elif nav_pct <= 0.50:
        valuation_label = "合理偏低"
        buy_urgency = "观望，等回调再买"
        suggested_position = "暂不加仓"
    elif nav_pct <= 0.70:
        valuation_label = "合理偏高"
        buy_urgency = "不建议买入"
        suggested_position = "暂不加仓"
    else:
        valuation_label = "高估"
        buy_urgency = "不建议买入，等待回调"
        suggested_position = "不买"

    # 入场价位建议
    entry_points = []
    if current_nav > ma60:
        entry_points.append({"level": "保守", "price": round(ma60, 4), "label": "MA60支撑位"})
    if current_nav > ma120:
        entry_points.append({"level": "激进", "price": round(ma120, 4), "label": "MA120支撑位"})
    if nav_pct <= 0.30:
        entry_points.insert(0, {"level": "现价", "price": round(current_nav, 4), "label": "低估区间，现价可买"})

    # 分批建议
    if nav_pct <= 0.20:
        batch_plan = "分2~3批买入：第一批现价建底仓，第二批MA60附近加仓，第三批MA120附近补仓"
    elif nav_pct <= 0.30:
        batch_plan = "分2批买入：一半现价，一半等回调到MA60附近"
    elif nav_pct <= 0.40:
        batch_plan = "等回调到MA60以下再建仓，分2批买入"
    else:
        batch_plan = "当前估值偏高，建议加入自选，等回调10%~15%再考虑"

    # 风险提示
    risks = []
    if rsi < 30:
        risks.append("RSI极度超卖（<30），可能有潜在利空，建仓前请确认基本面")
    if r60d < -0.25:
        risks.append(f"近60日跌幅 {r60d*100:.1f}%，需警惕是否为趋势性下跌而非回调")
    if r1y > 0.30:
        risks.append(f"近1年涨幅 {r1y*100:.1f}%，追高风险较大")

    if already_hold:
        buy_urgency = "已持有，不建议追加"
        batch_plan = "已有持仓，建议参考卖出信号管理"

    return {
        "code": code,
        "name": basic["name"],
        "current_nav": round(current_nav, 4),
        "valuation": {"pct": round(nav_pct * 100, 1), "label": valuation_label},
        "buy_urgency": buy_urgency,
        "suggested_position": suggested_position,
        "entry_points": entry_points,
        "batch_plan": batch_plan,
        "risk_warnings": risks,
        "already_hold": already_hold,
        "indicators": {
            "rsi": round(rsi, 1),
            "ma60": round(ma60, 4),
            "ma120": round(ma120, 4),
            "r60d": round(r60d * 100, 2),
            "r1y": round(r1y * 100, 2),
        },
    }


def analyze_portfolio() -> dict:
    """持仓组合分析：总盈亏、赛道集中度、再平衡建议"""
    conn = get_connection()
    holdings = conn.execute(
        "SELECT id, code, name, buy_date, buy_nav, shares, buy_amount FROM portfolio ORDER BY buy_date"
    ).fetchall()
    conn.close()

    if not holdings:
        return {"status": "empty", "message": "暂无持仓记录", "holdings_count": 0}

    total_invested = 0
    total_value = 0
    details = []
    sector_allocation = {}

    for h in holdings:
        code = h["code"]
        buy_nav = float(h["buy_nav"])
        shares = float(h["shares"]) if h["shares"] else 0
        buy_amount = float(h["buy_amount"]) if h["buy_amount"] else buy_nav * shares

        if buy_amount == 0 and shares > 0:
            buy_amount = buy_nav * shares
            shares = buy_amount / buy_nav if buy_nav > 0 else 0

        total_invested += buy_amount

        # 获取最新净值
        conn2 = get_connection()
        row = conn2.execute(
            "SELECT unit_nav, date FROM fund_nav WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        conn2.close()

        current_nav = float(row["unit_nav"]) if row else buy_nav
        current_date = str(row["date"]) if row else "N/A"

        if shares == 0 and buy_nav > 0:
            shares = buy_amount / buy_nav

        current_value = shares * current_nav
        total_value += current_value
        profit = current_value - buy_amount
        profit_pct = (profit / buy_amount * 100) if buy_amount > 0 else 0

        # 赛道分类
        name = h["name"] or ""
        sector = _identify_sector(name)
        sector_allocation.setdefault(sector, 0)
        sector_allocation[sector] += current_value

        # 卖出信号
        sell = get_sell_signals(code, buy_nav, h["buy_date"])

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
            "sector": sector,
            "sell_summary": sell.get("summary", ""),
            "sell_action_level": sell.get("action_level", 0),
        })

    total_profit = total_value - total_invested
    total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0

    # 赛道集中度分析
    sector_detail = {}
    for sec, val in sector_allocation.items():
        pct = val / total_value * 100 if total_value > 0 else 0
        sector_detail[sec] = {"value": round(val, 2), "pct": round(pct, 1)}

    # 集中度预警
    warnings = []
    for sec, info in sector_detail.items():
        if info["pct"] > 30:
            warnings.append(f"赛道「{sec}」占比 {info['pct']}%，超过30%警戒线，建议分散配置")

    # 再平衡建议
    if len(details) == 1:
        if details[0]["profit_pct"] > 20:
            rebalance = "仅持有一只基金且盈利可观，建议先部分止盈，将资金分配到2-3个低估值赛道"
        else:
            rebalance = "仅持有一只基金，风险集中。建议从Top20中选择2-3个不同赛道的基金分散配置"
    elif len(details) >= 3 and total_profit_pct > 15:
        rebalance = "组合整体盈利较好，可以考虑卖出部分盈利较高的持仓，买入当前低估值的赛道进行再平衡"
    elif len(details) >= 3 and len(warnings) > 0:
        rebalance = "赛道集中度过高，建议减持占比过大的赛道，增加低相关性的其他赛道"
    else:
        rebalance = "组合结构合理，保持观察，等待卖出信号"

    # 卖出优先度排序
    sell_priority = [d for d in details if d["sell_action_level"] >= 2]
    sell_priority.sort(key=lambda x: x["sell_action_level"], reverse=True)

    return {
        "status": "ok",
        "holdings_count": len(details),
        "total_invested": round(total_invested, 2),
        "total_value": round(total_value, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "details": details,
        "sector_allocation": sector_detail,
        "warnings": warnings,
        "rebalance_advice": rebalance,
        "sell_priority": sell_priority[:3],
    }
