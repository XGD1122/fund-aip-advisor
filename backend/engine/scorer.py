import pandas as pd
import numpy as np
from models.database import get_connection
from engine.indicators import (
    calc_period_return, calc_period_return_from_returns, calc_max_drawdown, calc_sharpe,
    calc_volatility, calc_calmar, calc_nav_deviation, calc_ma_slope,
    calc_nav_percentile, calc_short_term_surge, calc_ma_deviation_multi,
    calc_tracking_error, calc_adjusted_nav,
)
from engine.signals import score_ma_trend, score_macd, score_rsi, score_bollinger
from config import (
    SCORE_WEIGHTS_BUY, SCORE_WEIGHTS_AIP,
    SUB_WEIGHTS_BUY, SUB_WEIGHTS_AIP,
    get_dim_indicator_map,
    PE_PERCENTILE_HIGH, PE_PERCENTILE_WARN,
    PE_PERCENTILE_LOW, PE_PERCENTILE_FAIR,
    SURGE_3M_WARNING, MA_DEVIATION_WARNING,
)


def _get_fund_nav_data(code: str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? ORDER BY date",
        (code,)
    ).fetchall()
    conn.close()
    if len(rows) < 60:
        return None
    df = pd.DataFrame(rows, columns=["date", "unit_nav", "daily_return"])
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce").fillna(0)
    return df


def _get_latest_signal(code: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM fund_signal WHERE code=? ORDER BY date DESC LIMIT 1",
        (code,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def _get_fund_basic(code: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM fund_basic WHERE code=?", (code,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def score_one_fund_buy(code: str) -> dict:
    """一笔买入模式：使用复权净值（消除分红跳空）"""
    df = _get_fund_nav_data(code)
    if df is None:
        return _empty_score("buy")

    nav = df["unit_nav"]
    returns = df["daily_return"]
    adj_nav = calc_adjusted_nav(nav, returns)  # 复权净值
    signal = _get_latest_signal(code)
    basic = _get_fund_basic(code)

    # 收益指标：日收益率复利
    r1m = calc_period_return_from_returns(returns, 22)
    r3m = calc_period_return_from_returns(returns, 66)
    r6m = calc_period_return_from_returns(returns, 132)
    r1y = calc_period_return_from_returns(returns, 252)
    r3y_ret = calc_period_return_from_returns(returns, 756)
    r3y = ((1 + r3y_ret) ** (1 / 3) - 1) if len(returns) >= 756 and r3y_ret > -1 else 0

    # 估值指标：复权净值
    ma_dev = calc_ma_deviation_multi(adj_nav)
    nav_dev_120 = ma_dev.get("ma120_dev", 0)
    nav_pct = calc_nav_percentile(adj_nav, 504)
    surge_3m = calc_short_term_surge(adj_nav, 66)
    dd_state = float(adj_nav.iloc[-1] / adj_nav.rolling(60, min_periods=1).max().iloc[-1] - 1) if len(adj_nav) >= 60 else 0

    # 风控指标：复权净值
    max_dd = calc_max_drawdown(adj_nav)
    sharpe = calc_sharpe(returns)
    vol = calc_volatility(returns)
    calmar = calc_calmar(adj_nav, returns)

    # 基本面
    fund_scale = basic.get("scale", 0) or 0
    est_date = basic.get("establish_date", "")
    fund_age = 0
    if est_date:
        try:
            fund_age = (pd.Timestamp.now() - pd.Timestamp(est_date)).days / 365
        except Exception:
            pass
    fee_rate = (basic.get("fee_mgmt", 0) or 0) + (basic.get("fee_custody", 0) or 0)

    # 技术信号：复权净值
    ma_s = score_ma_trend(signal)
    macd_s = score_macd(signal)
    rsi_s = score_rsi(signal.get("rsi14", 50))
    bb_s = score_bollinger({**signal, "unit_nav": float(adj_nav.iloc[-1]) if len(adj_nav) > 0 else 0})

    # 跟踪误差
    tracking_err = calc_tracking_error(returns)

    raw = {
        "return_1m": r1m, "return_3m": r3m, "return_6m": r6m, "return_1y": r1y, "return_3y": r3y,
        "pe_percentile": nav_pct * 100,
        "nav_deviation": nav_dev_120,
        "drawdown_state": abs(dd_state),
        "max_drawdown": abs(max_dd), "sharpe": sharpe, "volatility": vol, "calmar": calmar,
        "fund_scale": fund_scale, "fund_age": fund_age, "fee_rate": fee_rate,
        "ma_trend": ma_s, "macd_signal": macd_s, "rsi": rsi_s, "bollinger": bb_s,
        "tracking_error": tracking_err,
        "adj_nav_latest": float(adj_nav.iloc[-1]),  # 最新复权净值（给前端画图）
    }

    score = _weighted_sum(raw, SUB_WEIGHTS_BUY, SCORE_WEIGHTS_BUY, mode="buy")

    nav_pct_2y = raw.get("pe_percentile", 50)
    if nav_pct_2y >= PE_PERCENTILE_HIGH:
        position_risk = "高位⚠️"
    elif nav_pct_2y >= PE_PERCENTILE_WARN:
        position_risk = "偏高⚡"
    elif nav_pct_2y <= PE_PERCENTILE_LOW:
        position_risk = "低位✅"
    elif nav_pct_2y <= PE_PERCENTILE_FAIR:
        position_risk = "偏低👍"
    else:
        position_risk = "正常"

    high_warning = (
        nav_pct_2y >= PE_PERCENTILE_HIGH
        or surge_3m > SURGE_3M_WARNING
        or nav_dev_120 > MA_DEVIATION_WARNING
    )

    return {
        **score, "code": code, "raw": raw,
        "position_risk": position_risk,
        "high_warning": high_warning,
        "nav_percentile_2y": round(nav_pct_2y, 1),
        "tracking_error": round(tracking_err * 100, 2),
        "adj_nav_latest": round(float(adj_nav.iloc[-1]), 4),
    }


def score_one_fund_aip(code: str) -> dict:
    """定投模式：使用复权净值"""
    df = _get_fund_nav_data(code)
    if df is None:
        return _empty_score("aip")

    nav = df["unit_nav"]
    returns = df["daily_return"]
    adj_nav = calc_adjusted_nav(nav, returns)
    basic = _get_fund_basic(code)
    signal = _get_latest_signal(code)

    # 长期趋势：复权净值
    ma60_slope = calc_ma_slope(adj_nav, 60, 20)
    ma120_slope = calc_ma_slope(adj_nav, 120, 20)

    # 收益：日收益率复利
    r1y = calc_period_return_from_returns(returns, 252)
    r3y_ret = calc_period_return_from_returns(returns, 756)
    r3y = ((1 + r3y_ret) ** (1 / 3) - 1) if len(returns) >= 756 and r3y_ret > -1 else 0

    # 估值：复权净值
    ma_dev = calc_ma_deviation_multi(adj_nav)
    nav_dev_120 = ma_dev.get("ma120_dev", 0)
    nav_pct = calc_nav_percentile(adj_nav, 504)
    dd_state = float(adj_nav.iloc[-1] / adj_nav.rolling(60, min_periods=1).max().iloc[-1] - 1) if len(adj_nav) >= 60 else 0
    surge_3m = calc_short_term_surge(adj_nav, 66)

    # 风控
    vol = calc_volatility(returns)
    max_dd = calc_max_drawdown(adj_nav)
    sharpe = calc_sharpe(returns)
    tracking_err = calc_tracking_error(returns)

    # 基本面
    fund_scale = basic.get("scale", 0) or 0
    est_date = basic.get("establish_date", "")
    fund_age = 0
    if est_date:
        try:
            fund_age = (pd.Timestamp.now() - pd.Timestamp(est_date)).days / 365
        except Exception:
            pass
    fee_rate = (basic.get("fee_mgmt", 0) or 0) + (basic.get("fee_custody", 0) or 0)

    rsi_val = signal.get("rsi14", 50) or 50

    raw = {
        "pe_percentile": nav_pct * 100,
        "nav_deviation": nav_dev_120,
        "drawdown_state": abs(dd_state),
        "ma60_slope": ma60_slope, "ma120_slope": ma120_slope,
        "return_1y": r1y, "return_3y": r3y,
        "volatility_aip": vol,
        "max_drawdown": abs(max_dd), "sharpe": sharpe,
        "tracking_error": tracking_err,
        "fund_scale": fund_scale, "fund_age": fund_age, "fee_rate": fee_rate,
    }

    score = _weighted_sum(raw, SUB_WEIGHTS_AIP, SCORE_WEIGHTS_AIP, mode="aip")

    nav_pct_2y = raw.get("pe_percentile", 50)
    is_overbought = rsi_val > 75 and surge_3m > 0.15

    if nav_pct_2y <= PE_PERCENTILE_LOW and not is_overbought:
        aip_rating = "极佳定投时机 🌟"
    elif nav_pct_2y <= PE_PERCENTILE_LOW:
        aip_rating = "适合定投 ✅（低位但短期偏热，等待回调更佳）"
    elif nav_pct_2y <= PE_PERCENTILE_FAIR:
        aip_rating = "适合定投 ✅"
    elif is_overbought and nav_pct_2y >= PE_PERCENTILE_WARN:
        aip_rating = "暂停定投 ⚠️（高位+过热）"
    elif nav_pct_2y >= PE_PERCENTILE_HIGH:
        aip_rating = "暂停定投 ⚠️"
    elif nav_pct_2y >= PE_PERCENTILE_WARN:
        aip_rating = "谨慎定投 ⚡"
    elif is_overbought:
        aip_rating = "谨慎定投 ⚡（短期过热）"
    else:
        aip_rating = "可以定投"

    trend_up = ma60_slope > 0 and ma120_slope > 0
    trend_warning = ma120_slope < -0.05 or (surge_3m > 0.25 and rsi_val > 70)

    return {
        **score, "code": code, "raw": raw,
        "aip_rating": aip_rating,
        "trend_up": trend_up,
        "trend_warning": trend_warning,
        "nav_percentile_2y": round(nav_pct_2y, 1),
        "tracking_error": round(tracking_err * 100, 2),
        "rsi14": round(rsi_val, 1),
        "surge_3m": round(surge_3m * 100, 1),
        "adj_nav_latest": round(float(adj_nav.iloc[-1]), 4),
    }


def _weighted_sum(raw: dict, sub_weights: dict, dim_weights: dict, mode: str = "buy") -> dict:
    dim_indicator_map = get_dim_indicator_map(mode)
    dims = {}
    for dim, indicators in dim_indicator_map.items():
        dim_score = 0
        dim_w_sum = 0
        for ind in indicators:
            w = sub_weights.get(ind, 0)
            v = raw.get(ind, 0) or 0
            dim_score += w * _normalize_to_score(ind, v, mode)
            dim_w_sum += w
        dims[dim] = dim_score / dim_w_sum if dim_w_sum > 0 else 50

    total = 0
    for d in dims:
        w = dim_weights.get(d, 0)
        total += dims[d] * w

    result = {
        "total_score": round(total, 2),
        "return_score": round(dims.get("return_", 50), 2),
        "valuation_score": round(dims.get("valuation", 50), 2),
        "risk_score": round(dims.get("risk", 50), 2),
        "fundamental_score": round(dims.get("fundamental", 50), 2),
        "technical_score": round(dims.get("technical", 50), 2),
        "tracking_score": round(dims.get("tracking", 50), 2),
    }
    if mode == "aip":
        result["trend_score"] = round(dims.get("trend", 50), 2)
        result["volatility_score"] = round(dims.get("volatility", 50), 2)
    return result


def _normalize_to_score(indicator: str, value: float, mode: str = "buy") -> float:
    if indicator in ("return_1m", "return_3m", "return_6m", "return_1y", "return_3y",
                     "sharpe", "calmar", "ma_trend", "macd_signal",
                     "ma60_slope", "ma120_slope"):
        return max(0, min(100, 50 + value * 200))
    if indicator in ("max_drawdown", "volatility", "fee_rate", "drawdown_state"):
        return max(0, min(100, 100 - abs(value) * 250))
    if indicator in ("nav_deviation",):
        if -0.05 <= value <= 0.10:
            return 90
        elif value > 0.10:
            return max(0, 90 - (value - 0.10) * 300)
        else:
            return max(0, 90 - abs(value + 0.05) * 200)
    if indicator in ("pe_percentile", "nav_pct_2y"):
        v = max(0, min(100, value))
        if v <= 30:
            return 90 + v * 0.33
        elif v <= 70:
            return 80 - (v - 30) * 0.5
        elif v <= 85:
            return 60 - (v - 70) * 1.33
        else:
            return max(0, 40 - (v - 85) * 2.67)
    if indicator in ("volatility_aip",):
        if 0.15 <= value <= 0.30:
            return 90 + (value - 0.15) / 0.15 * 10
        elif 0.10 <= value < 0.15:
            return 70 + (value - 0.10) / 0.05 * 20
        elif value > 0.30:
            return max(0, 90 - (value - 0.30) * 150)
        else:
            return max(0, 70 - (0.10 - value) * 300)
    if indicator in ("tracking_error",):
        if value <= 0.01:
            return 95 + value / 0.01 * 5
        elif value <= 0.02:
            return 80 + (0.02 - value) / 0.01 * 15
        elif value <= 0.04:
            return 50 + (0.04 - value) / 0.02 * 30
        else:
            return max(0, 50 - (value - 0.04) * 500)
    if indicator in ("rsi", "bollinger"):
        return max(0, min(100, value))
    if indicator in ("fund_scale",):
        if 2 <= value <= 50:
            return 100
        elif value < 2:
            return max(0, 100 - (2 - value) * 20)
        else:
            return max(0, 100 - (value - 50) * 1.5)
    if indicator in ("fund_age",):
        return min(100, value * 100 / 3)
    if indicator in ("surge_3m",):
        if value <= 0.10:
            return 100
        elif value <= 0.25:
            return 100 - (value - 0.10) * 200
        else:
            return max(0, 70 - (value - 0.25) * 300)
    return 50


def _empty_score(mode: str) -> dict:
    result = {
        "total_score": 0, "return_score": 0, "valuation_score": 0,
        "risk_score": 0, "fundamental_score": 0, "technical_score": 0,
        "tracking_score": 0,
        "code": "", "raw": {},
        "position_risk": "数据不足",
        "high_warning": False,
        "nav_percentile_2y": 0,
        "tracking_error": 0,
        "adj_nav_latest": 0,
    }
    if mode == "aip":
        result["aip_rating"] = "数据不足"
        result["trend_up"] = False
        result["trend_warning"] = False
        result["trend_score"] = 0
        result["volatility_score"] = 0
    return result
