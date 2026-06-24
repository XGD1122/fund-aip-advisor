import numpy as np


def score_ma_trend(row: dict) -> float:
    """均线趋势评分：多头排列满分"""
    ma5 = row.get("ma5", 0) or 0
    ma20 = row.get("ma20", 0) or 0
    ma60 = row.get("ma60", 0) or 0
    score = 50
    if ma5 > ma20:
        score += 25
    if ma20 > ma60:
        score += 25
    return min(100, max(0, score))


def score_macd(row: dict) -> float:
    """MACD信号评分"""
    dif = row.get("macd_dif", 0) or 0
    dea = row.get("macd_dea", 0) or 0
    hist = row.get("macd_hist", 0) or 0
    score = 50
    if dif > dea:
        score += 20
    if hist > 0:
        score += 20
    if dif > 0:
        score += 10
    return min(100, max(0, score))


def score_rsi(rsi_val: float) -> float:
    """RSI评分：40~70最佳，>80超买扣分，<30超卖扣分。
    修复了RSI=80处的跳变：现在>70统一使用递减函数，无分段断裂。"""
    if rsi_val is None or np.isnan(rsi_val):
        return 50
    if 40 <= rsi_val <= 70:
        # 最佳区间：80~100分
        return 80 + (rsi_val - 40) * 0.66
    elif rsi_val > 70:
        # >70 统一递减：70→100分, 80→80分, 90→30分, 100→0分
        return max(0, 100 - (rsi_val - 70) * 3.33)
    elif rsi_val >= 30:
        # 30~40：过渡区间，60~80分
        return 60 + (rsi_val - 30) * 2.0
    else:
        # <30 超卖：0→0分, 30→60分
        return max(0, rsi_val * 2.0)


def score_bollinger(row: dict) -> float:
    """布林带位置评分：中轨附近偏上最佳"""
    nav = row.get("unit_nav", 0) or 0
    upper = row.get("bb_upper", 0) or 0
    mid = row.get("bb_mid", 0) or 0
    lower = row.get("bb_lower", 0) or 0
    if upper == 0 or lower == 0 or mid == 0:
        return 50
    if lower <= nav <= upper:
        pos = (nav - mid) / (upper - mid) if upper != mid else 0
        if -0.3 <= pos <= 0.5:
            return 80
        elif pos > 0.5:
            return 50 + (1 - pos) * 60
        else:
            return 50 + (pos + 1) * 30
    elif nav > upper:
        return 30
    else:
        return 40
