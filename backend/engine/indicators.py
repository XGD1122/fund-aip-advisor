import pandas as pd
import numpy as np
from models.database import get_connection


def calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def calc_ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9) -> dict:
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    hist = 2 * (dif - dea)
    return {"macd_dif": dif, "macd_dea": dea, "macd_hist": hist}


def calc_rsi(close: pd.Series, window=14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=window, adjust=False).mean()
    avg_loss = loss.ewm(span=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_bollinger(close: pd.Series, window=20, num_std=2) -> dict:
    mid = calc_ma(close, window)
    std = close.rolling(window=window, min_periods=1).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return {"bb_mid": mid, "bb_upper": upper, "bb_lower": lower}


def calc_drawdown(nav: pd.Series) -> pd.Series:
    """计算滚动回撤序列"""
    cummax = nav.expanding().max()
    return (nav - cummax) / cummax


def calc_max_drawdown(nav: pd.Series, window_days: int = 252) -> float:
    """近一年最大回撤"""
    rolling_max = nav.rolling(window=window_days, min_periods=1).max()
    drawdown = (nav - rolling_max) / rolling_max
    return float(drawdown.min())


def calc_sharpe(returns: pd.Series, risk_free: float = 0.017, window_days: int = 252) -> float:
    """年化夏普比率"""
    excess = returns - risk_free / 252
    if excess.std() == 0 or len(excess) < window_days:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(252))


def calc_volatility(returns: pd.Series, window_days: int = 252) -> float:
    """年化波动率"""
    if len(returns) < window_days:
        return float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0
    return float(returns.tail(window_days).std() * np.sqrt(252))


def calc_calmar(nav: pd.Series, returns: pd.Series = None) -> float:
    """Calmar比率 = 年化收益 / 全区间最大回撤绝对值"""
    annual_ret = calc_annual_return(nav)
    # 使用全区间最大回撤（而非仅近一年）
    cummax = nav.expanding().max()
    drawdown = (nav - cummax) / cummax
    max_dd = abs(float(drawdown.min()))
    if max_dd == 0:
        return 0.0
    return annual_ret / max_dd


def calc_tracking_error(returns: pd.Series, window_days: int = 252) -> float:
    """计算年化跟踪误差（指数基金核心指标）。
    由于没有直接对应的指数日收益数据，用基金日收益相对其自身均值的偏离来估算。
    当有指数数据时，应替换为基金收益-指数收益的标准差。
    """
    if len(returns) < 60:
        return 0.05  # 数据不足时返回较高值
    # 用日收益的波动率作为跟踪误差的近似
    # 实际应为 std(fund_return - benchmark_return)，这里用绝对波动率作为上界估算
    daily_vol = float(returns.tail(window_days).std()) if len(returns) >= window_days else float(returns.std())
    if np.isnan(daily_vol):
        return 0.05
    return daily_vol * np.sqrt(252)


def calc_max_drawdown_full(nav: pd.Series) -> float:
    """计算全区间最大回撤（不限窗口）"""
    cummax = nav.expanding().max()
    drawdown = (nav - cummax) / cummax
    return float(drawdown.min())


def calc_annual_return(nav: pd.Series, window_days: int = 252) -> float:
    """滚动年化收益率"""
    if len(nav) < 2:
        return 0.0
    days = min(window_days, len(nav) - 1)
    total_return = (nav.iloc[-1] / nav.iloc[-days - 1]) - 1 if days < len(nav) else (nav.iloc[-1] / nav.iloc[0]) - 1
    years = days / 252
    if years == 0:
        return 0.0
    return float((1 + total_return) ** (1 / years) - 1)


def calc_adjusted_nav(nav: pd.Series, returns: pd.Series) -> pd.Series:
    """从原始净值+日收益率构建复权净值（消除分红跳空）。
    从第一个净值开始，按照 daily_return 逐日复利累积。
    复权净值 = first_nav * ∏(1 + daily_return_i)
    """
    if len(nav) < 2:
        return nav.copy()
    cum_ret = (1 + returns.fillna(0)).cumprod()
    adj = nav.iloc[0] * cum_ret
    # 对齐索引
    adj.index = nav.index
    return adj


def calc_period_return_from_returns(returns: pd.Series, days: int) -> float:
    """从日收益率计算指定天数的累计收益（不受分红除权影响）"""
    if len(returns) < days or days == 0:
        if len(returns) < 2:
            return 0.0
        return float((1 + returns).prod() - 1)
    return float((1 + returns.tail(days)).prod() - 1)


def calc_period_return(nav: pd.Series, days: int) -> float:
    """计算指定天数的收益率（使用日收益复利，不受分红影响）"""
    # 注：调用方应传入 returns 而非 nav，此函数保留向后兼容
    if len(nav) < days or days == 0:
        if len(nav) < 2:
            return 0.0
        return float(nav.iloc[-1] / nav.iloc[0] - 1)
    return float(nav.iloc[-1] / nav.iloc[-days] - 1)


def calc_nav_deviation(nav: pd.Series) -> float:
    """净值相对MA120的偏离度"""
    if len(nav) < 120:
        return 0.0
    ma120 = nav.rolling(window=120, min_periods=1).mean().iloc[-1]
    current = nav.iloc[-1]
    if ma120 == 0:
        return 0.0
    return float((current - ma120) / ma120)


def calc_ma_slope(nav: pd.Series, window: int, lookback: int = 20) -> float:
    """计算均线在近lookback天的斜率"""
    ma = nav.rolling(window=window, min_periods=1).mean()
    if len(ma) < lookback + 1:
        return 0.0
    recent = ma.tail(lookback + 1)
    return float((recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0])


def calc_nav_percentile(nav: pd.Series, lookback: int = 504) -> float:
    """当前净值在过去lookback天中的百分位（504≈2年）。>80%=高位"""
    if len(nav) < lookback:
        lookback = len(nav)
    if lookback < 20:
        return 0.5
    recent = nav.tail(lookback)
    current = nav.iloc[-1]
    return float((recent < current).mean())


def calc_short_term_surge(nav: pd.Series, days: int = 66) -> float:
    """近3月涨幅是否过大（>20%可能是短期过热信号）"""
    if len(nav) < days:
        return 0.0
    return float(nav.iloc[-1] / nav.iloc[-days] - 1)


def calc_ma_deviation_multi(nav: pd.Series) -> dict:
    """多周期均线偏离度"""
    result = {}
    for window, label in [(60, "ma60"), (120, "ma120"), (250, "ma250")]:
        if len(nav) >= window:
            ma = nav.rolling(window=window, min_periods=1).mean().iloc[-1]
            if ma > 0:
                result[f"{label}_dev"] = float((nav.iloc[-1] - ma) / ma)
            else:
                result[f"{label}_dev"] = 0.0
        else:
            result[f"{label}_dev"] = 0.0
    return result


# === KDJ 指标 ===

def calc_kdj(close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3) -> dict:
    """
    KDJ随机指标（用滚动窗口高低点近似，适配基金净值数据）
    标准公式: RSV = (C - Ln) / (Hn - Ln) * 100
    """
    low_n = close.rolling(window=n, min_periods=1).min()
    high_n = close.rolling(window=n, min_periods=1).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)

    k = rsv.ewm(span=m1, adjust=False).mean()
    d = k.ewm(span=m2, adjust=False).mean()
    j = 3 * k - 2 * d

    return {"kdj_k": k, "kdj_d": d, "kdj_j": j}


# === ATR 平均真实波幅 ===

def calc_atr(close: pd.Series, window: int = 14) -> pd.Series:
    """
    用日收益率反推隐含波动幅度来近似ATR（适配基金净值数据）
    TR ≈ |daily_return| * close（近似真实波动）
    """
    daily_pct = close.pct_change().abs()
    # 使用EWMA平滑
    atr = daily_pct * close
    atr = atr.ewm(span=window, adjust=False).mean()
    return atr


# === 布林带宽度 ===

def calc_bb_width(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    """布林带宽度 = (上轨-下轨) / 中轨"""
    mid = calc_ma(close, window)
    std = close.rolling(window=window, min_periods=1).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return width.fillna(0)


# === 背离检测 ===

def detect_macd_divergence(close: pd.Series, dif: pd.Series, lookback: int = 60) -> dict:
    """
    检测MACD顶背离/底背离
    顶背离: 价格创新高，MACD DIF未创新高 → 上涨动能衰竭
    底背离: 价格创新低，MACD DIF未创新低 → 下跌动能衰竭
    返回: {"type": "bearish"/"bullish"/None, "strength": 0-1}
    """
    if len(close) < lookback:
        return {"type": None, "strength": 0}

    recent_close = close.tail(lookback)
    recent_dif = dif.tail(lookback)

    # 找近期的局部极值点（简化：用区间最高/最低点）
    close_max_idx = recent_close.idxmax()
    close_min_idx = recent_close.idxmin()

    # 顶背离检测
    close_peak = recent_close.max()
    dif_at_close_peak = recent_dif.loc[close_max_idx] if close_max_idx in recent_dif.index else 0
    dif_peak = recent_dif.max()

    bearish = False
    if dif_at_close_peak < dif_peak * 0.95:  # DIF在价格高点时未同步创新高
        bearish = True

    # 底背离检测
    close_trough = recent_close.min()
    dif_at_close_trough = recent_dif.loc[close_min_idx] if close_min_idx in recent_dif.index else 0
    dif_trough = recent_dif.min()

    bullish = False
    if dif_at_close_trough > dif_trough * 1.05:  # DIF在价格低点时未同步创新低
        bullish = True

    if bearish:
        strength = min(1.0, (dif_peak - dif_at_close_peak) / abs(dif_peak) * 5 if dif_peak != 0 else 0)
        return {"type": "bearish", "strength": round(strength, 2)}
    elif bullish:
        strength = min(1.0, (dif_at_close_trough - dif_trough) / abs(dif_trough) * 5 if dif_trough != 0 else 0)
        return {"type": "bullish", "strength": round(strength, 2)}

    return {"type": None, "strength": 0}


def detect_rsi_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 60) -> dict:
    """
    检测RSI顶背离/底背离
    顶背离: 价格创新高，RSI未创新高
    底背离: 价格创新低，RSI未创新低
    """
    if len(close) < lookback:
        return {"type": None, "strength": 0}

    recent_close = close.tail(lookback)
    recent_rsi = rsi.tail(lookback)

    close_max_idx = recent_close.idxmax()
    close_min_idx = recent_close.idxmin()

    # 顶背离
    close_peak = recent_close.max()
    rsi_at_close_peak = recent_rsi.loc[close_max_idx] if close_max_idx in recent_rsi.index else 50
    rsi_peak = recent_rsi.max()

    bearish = rsi_at_close_peak < rsi_peak - 5  # RSI差5点以上算背离

    # 底背离
    rsi_at_close_trough = recent_rsi.loc[close_min_idx] if close_min_idx in recent_rsi.index else 50
    rsi_trough = recent_rsi.min()

    bullish = rsi_at_close_trough > rsi_trough + 5

    if bearish:
        strength = min(1.0, (rsi_peak - rsi_at_close_peak) / 20)
        return {"type": "bearish", "strength": round(strength, 2)}
    elif bullish:
        strength = min(1.0, (rsi_at_close_trough - rsi_trough) / 20)
        return {"type": "bullish", "strength": round(strength, 2)}

    return {"type": None, "strength": 0}


# === 全信号计算（更新版，包含新指标） ===

def calc_all_signals_for_fund(code: str) -> pd.DataFrame:
    """计算一只基金的全部技术信号并保存"""
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

    # MA60 斜率（近20日）
    ma60_series = calc_ma(nav, 60)
    df["ma60_slope"] = ma60_series.diff(20) / ma60_series.shift(20).replace(0, np.nan)
    df["ma60_slope"] = df["ma60_slope"].fillna(0)

    return df
