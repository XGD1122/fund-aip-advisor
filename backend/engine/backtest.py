import pandas as pd
import numpy as np
from datetime import datetime
from models.database import get_connection
from config import TRAIN_TEST_SPLIT_DATE, FUND_TYPE_FILTER


def run_backtest(
    start_date: str,
    end_date: str,
    mode: str = "buy",
    rebalance_months: int = 3,
    top_n: int = 10,
    benchmark_code: str = "000300"
) -> dict:
    """执行策略回测（仅指数型基金）"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE ?", (FUND_TYPE_FILTER + "%",)
    ).fetchall()]
    conn.close()

    if not codes:
        return {"error": "无指数型基金数据，请先运行数据初始化"}

    rebalance_dates = _generate_rebalance_dates(start_date, end_date, rebalance_months)
    if not rebalance_dates:
        return {"error": "无有效调仓日期"}

    holdings = []
    for rb_date in rebalance_dates:
        # 使用截至该日期的历史数据评分
        ranked = _rank_funds_at_date(codes, rb_date, mode)
        selected = [r["code"] for r in ranked[:top_n]]
        if not selected:
            continue

        next_date = _get_next_rebalance_date(rb_date, rebalance_dates, end_date)
        period_return = _calc_period_portfolio_return(selected, rb_date, next_date)

        holdings.append({
            "date": rb_date,
            "funds": selected,
            "period_return": period_return,
        })

    portfolio_curve = _calc_portfolio_curve(holdings, start_date)
    bench_curve = _get_benchmark_curve(benchmark_code, start_date, end_date)
    metrics = _calc_backtest_metrics(portfolio_curve, bench_curve, start_date, end_date)
    _save_backtest_record(mode, start_date, end_date, rebalance_months, top_n,
                          metrics, benchmark_code)

    return {
        "metrics": metrics,
        "holdings": holdings[-20:],
        "portfolio_curve": portfolio_curve[-500:],
        "benchmark_curve": bench_curve[-500:],
    }


def run_aip_backtest(
    start_date: str,
    end_date: str,
    monthly_amount: float = 1000,
    top_n: int = 5,
    benchmark_code: str = "000300"
) -> dict:
    """定投回测：每月固定金额投入（仅指数型基金）"""
    conn = get_connection()
    codes = [r["code"] for r in conn.execute(
        "SELECT code FROM fund_basic WHERE fund_type LIKE ?", (FUND_TYPE_FILTER + "%",)
    ).fetchall()]
    conn.close()

    invest_dates = pd.date_range(start=start_date, end=end_date, freq="MS").strftime("%Y-%m-%d").tolist()
    if not invest_dates:
        return {"error": "无有效定投日期"}

    total_invested = 0
    total_shares = {}  # 按基金代码分别累计份额
    cash_flows = []    # 用于IRR计算：[(date, cashflow)] 负数为投入

    for inv_date in invest_dates:
        ranked = _rank_funds_at_date(codes, inv_date, "aip")
        selected = [r["code"] for r in ranked[:top_n]]
        if not selected:
            continue

        amount_per_fund = monthly_amount / len(selected)
        for code in selected:
            nav = _get_nav_at_date(code, inv_date)
            if nav and nav > 0:
                shares = amount_per_fund / nav
                total_shares[code] = total_shares.get(code, 0) + shares

        total_invested += monthly_amount
        cash_flows.append((inv_date, -monthly_amount))  # 负号表示现金流出

    # 计算最终市值
    final_value = 0
    for code, shares in total_shares.items():
        nav = _get_nav_at_date(code, end_date)
        if nav:
            final_value += shares * nav

    # 最终现金流（正号表示回收）
    cash_flows.append((end_date, final_value))

    total_return = (final_value - total_invested) / total_invested if total_invested > 0 else 0
    first_date = invest_dates[0] if invest_dates else start_date
    years = max(0.5, (pd.Timestamp(end_date) - pd.Timestamp(first_date)).days / 365)

    # 使用 XIRR 风格的内部收益率
    irr = _calc_xirr(cash_flows)

    return {
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "total_return": round(total_return * 100, 2),
        "annual_return": round(((1 + total_return) ** (1 / years) - 1) * 100, 2) if total_return > -1 else 0,
        "irr": round(irr * 100, 2),
        "years": round(years, 1),
        "cash_flows": [
            {"date": d, "amount": a, "cumulative": sum(c for _, c in cash_flows[:i+1] if c < 0)}
            for i, (d, a) in enumerate(cash_flows[:-1])
        ][-24:],
    }


def _generate_rebalance_dates(start: str, end: str, months: int) -> list:
    dates = pd.date_range(start=start, end=end, freq=f"{months}MS")
    return [d.strftime("%Y-%m-%d") for d in dates]


def _get_next_rebalance_date(current: str, all_dates: list, end_date: str) -> str:
    idx = all_dates.index(current) if current in all_dates else -1
    if idx >= 0 and idx + 1 < len(all_dates):
        return all_dates[idx + 1]
    return end_date


def _rank_funds_at_date(codes: list, date: str, mode: str) -> list:
    """用截至某日期的历史数据评分（回测核心——绝不使用未来数据）。

    使用与实盘评分一致的五维度体系，而非简化公式。
    由于回测时间点没有 fund_signal 表数据，技术面用可计算的替代指标。
    """
    conn = get_connection()
    results = []

    for code in codes:
        rows = conn.execute(
            "SELECT date, unit_nav, daily_return FROM fund_nav WHERE code=? AND date<=? ORDER BY date",
            (code, date)
        ).fetchall()
        if len(rows) < 60:
            continue

        nav_series = pd.Series([float(r["unit_nav"]) for r in rows])
        ret_series = pd.Series([float(r["daily_return"] or 0) for r in rows])

        # ---- 收益维度 (22%)：对齐实盘权重 ----
        r1m = _period_return(nav_series, 22)
        r3m = _period_return(nav_series, 66)
        r6m = _period_return(nav_series, 132)
        r1y = _period_return(nav_series, 252)
        r3y = ((1 + _period_return(nav_series, 756)) ** (1/3) - 1) if len(nav_series) >= 756 else 0

        # ---- 估值维度 (25%) ----
        # 净值分位（2年窗口）
        lookback = min(504, len(nav_series))
        nav_pct = float((nav_series.tail(lookback) < nav_series.iloc[-1]).mean())
        # MA120偏离
        ma120 = nav_series.rolling(120, min_periods=1).mean().iloc[-1]
        nav_deviation = float((nav_series.iloc[-1] - ma120) / ma120) if ma120 > 0 else 0
        # 60日回撤状态
        dd_state = abs(float(nav_series.iloc[-1] / nav_series.rolling(60, min_periods=1).max().iloc[-1] - 1))

        # ---- 风控维度 (18%) ----
        max_dd = abs(float((nav_series / nav_series.expanding().max() - 1).min()))
        sharpe = _calc_sharpe_hist(ret_series)
        vol = _calc_vol_hist(ret_series)

        # ---- 跟踪误差 (10%) ----
        tracking_err = _calc_vol_hist(ret_series)  # 近似

        if mode == "aip":
            # ===== 定投模式 =====
            # 长期趋势
            ma60 = nav_series.rolling(60, min_periods=1).mean()
            ma120_s = nav_series.rolling(120, min_periods=1).mean()
            ma60_slope = float((ma60.iloc[-1] - ma60.iloc[-min(21, len(ma60))]) / ma60.iloc[-min(21, len(ma60))]) if len(ma60) >= 21 and ma60.iloc[-min(21, len(ma60))] > 0 else 0
            ma120_slope = float((ma120_s.iloc[-1] - ma120_s.iloc[-min(21, len(ma120_s))]) / ma120_s.iloc[-min(21, len(ma120_s))]) if len(ma120_s) >= 21 and ma120_s.iloc[-min(21, len(ma120_s))] > 0 else 0

            # 归一化各维度到0~100
            val_score = _norm_pe_pct(nav_pct * 100)
            trend_score = (_norm_linear(ma60_slope) * 0.5 + _norm_linear(ma120_slope) * 0.5)
            vol_score_aip = _norm_vol_aip(vol)
            ret_score = _norm_linear(r1y) * 0.6 + _norm_linear(r3y) * 0.4
            risk_score = _norm_reverse(max_dd) * 0.55 + _norm_linear(sharpe) * 0.45
            track_score = _norm_tracking(tracking_err)

            # 加权总分（对齐实盘权重）
            total = (
                val_score * 0.30 +
                trend_score * 0.20 +
                vol_score_aip * 0.15 +
                risk_score * 0.12 +
                ret_score * 0.10 +
                track_score * 0.08 +
                50 * 0.05  # 基本面中性
            )
        else:
            # ===== 一笔买入模式 =====
            val_score = _norm_pe_pct(nav_pct * 100)
            ret_score = (_norm_linear(r1m) * 0.03 + _norm_linear(r3m) * 0.05 +
                        _norm_linear(r6m) * 0.05 + _norm_linear(r1y) * 0.06 +
                        _norm_linear(r3y) * 0.03) / 0.22
            risk_score = (_norm_reverse(max_dd) * 0.08 + _norm_linear(sharpe) * 0.04 +
                         _norm_reverse(vol) * 0.04 + _norm_linear(0) * 0.02) / 0.18
            tech_score = 50  # 回测无技术信号，用中性值
            track_score = _norm_tracking(tracking_err)

            total = (
                val_score * 0.25 +
                ret_score * 0.22 +
                risk_score * 0.18 +
                tech_score * 0.15 +
                track_score * 0.10 +
                50 * 0.10  # 基本面中性
            )

        results.append({
            "code": code,
            "score": round(total, 2),
        })

    conn.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---- 历史评分辅助归一化函数 ----

def _norm_linear(v: float) -> float:
    """正向指标归一化：0→50分, +25%→100分"""
    return max(0, min(100, 50 + v * 200))


def _norm_reverse(v: float) -> float:
    """反向指标归一化：0→100分, 20%→50分"""
    return max(0, min(100, 100 - abs(v) * 250))


def _norm_pe_pct(pct: float) -> float:
    """PE分位归一化"""
    v = max(0, min(100, pct))
    if v <= 30:
        return 90 + v * 0.33
    elif v <= 70:
        return 80 - (v - 30) * 0.5
    elif v <= 85:
        return 60 - (v - 70) * 1.33
    else:
        return max(0, 40 - (v - 85) * 2.67)


def _norm_vol_aip(vol: float) -> float:
    """AIP波动率归一化（区间最优15%~30%）"""
    if 0.15 <= vol <= 0.30:
        return 90 + (vol - 0.15) / 0.15 * 10
    elif 0.10 <= vol < 0.15:
        return 70 + (vol - 0.10) / 0.05 * 20
    elif vol > 0.30:
        return max(0, 90 - (vol - 0.30) * 150)
    else:
        return max(0, 70 - (0.10 - vol) * 300)


def _norm_tracking(te: float) -> float:
    """跟踪误差归一化"""
    if te <= 0.01:
        return 95 + te / 0.01 * 5
    elif te <= 0.02:
        return 80 + (0.02 - te) / 0.01 * 15
    elif te <= 0.04:
        return 50 + (0.04 - te) / 0.02 * 30
    else:
        return max(0, 50 - (te - 0.04) * 500)


def _period_return(nav: pd.Series, days: int) -> float:
    """从净值序列计算区间收益率"""
    if len(nav) < days or days == 0:
        if len(nav) < 2:
            return 0.0
        return float(nav.iloc[-1] / nav.iloc[0] - 1)
    return float(nav.iloc[-1] / nav.iloc[-days] - 1)


def _calc_sharpe_hist(returns: pd.Series) -> float:
    """历史夏普比率"""
    excess = returns - 0.017 / 252
    if excess.std() == 0 or len(excess) < 60:
        return 0.0
    return float(excess.mean() / excess.std() * np.sqrt(252))


def _calc_vol_hist(returns: pd.Series) -> float:
    """历史年化波动率"""
    if len(returns) < 60:
        return float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0
    return float(returns.tail(252).std() * np.sqrt(252))


# ---- 组合计算 ----

def _calc_period_portfolio_return(codes: list, start: str, end: str) -> float:
    returns = []
    conn = get_connection()
    for code in codes:
        r1 = conn.execute(
            "SELECT unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (code, start)
        ).fetchone()
        r2 = conn.execute(
            "SELECT unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
            (code, end)
        ).fetchone()
        if r1 and r2 and r1["unit_nav"] and r1["unit_nav"] > 0:
            returns.append(float(r2["unit_nav"] / r1["unit_nav"] - 1))
    conn.close()
    return float(np.mean(returns)) if returns else 0


def _calc_portfolio_curve(holdings: list, start_date: str) -> list:
    curve = []
    value = 1.0
    for h in holdings:
        value *= (1 + h["period_return"])
        curve.append({"date": h["date"], "value": round(value, 4)})
    return curve


def _get_benchmark_curve(code: str, start: str, end: str) -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE code=? AND date>=? AND date<=? ORDER BY date",
        (code, start, end)
    ).fetchall()
    conn.close()
    if not rows:
        return []
    base = rows[0]["close"]
    if base == 0:
        return []
    return [{"date": r["date"], "value": round(r["close"] / base, 4)} for r in rows]


def _calc_backtest_metrics(portfolio_curve: list, bench_curve: list,
                           start: str, end: str) -> dict:
    """计算回测核心指标，修复了信息比率计算"""
    default = {
        "total_return": 0, "annual_return": 0, "max_drawdown": 0,
        "sharpe": 0, "win_rate": 0, "alpha": 0, "info_ratio": 0,
        "benchmark_return": 0,
    }
    if not portfolio_curve:
        return default

    p_vals = pd.Series([p["value"] for p in portfolio_curve])
    total_return = float(p_vals.iloc[-1] / p_vals.iloc[0] - 1)
    days = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days)
    annual_return = (1 + total_return) ** (365 / days) - 1
    max_dd = float((p_vals / p_vals.expanding().max() - 1).min())

    daily_ret = p_vals.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

    # 基准收益
    b_vals = pd.Series([b["value"] for b in bench_curve]) if bench_curve else pd.Series([1])
    bench_return = float(b_vals.iloc[-1] / b_vals.iloc[0] - 1) if len(b_vals) > 1 else 0
    bench_annual = (1 + bench_return) ** (365 / days) - 1 if days > 0 else 0

    alpha = annual_return - bench_annual

    # 信息比率：超额收益 / 超额收益标准差（修复：分母应为超额收益的波动率）
    if bench_curve and len(bench_curve) == len(portfolio_curve):
        b_daily = b_vals.pct_change().dropna()
        # 对齐长度
        min_len = min(len(daily_ret), len(b_daily))
        excess_ret = daily_ret.iloc[-min_len:].values - b_daily.iloc[-min_len:].values
        excess_std = float(np.std(excess_ret))
        info_ratio = (annual_return - bench_annual) / (excess_std * np.sqrt(252)) if excess_std > 0 else 0
    else:
        info_ratio = 0

    win_rate = float((daily_ret > 0).mean()) if len(daily_ret) > 0 else 0

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate * 100, 1),
        "alpha": round(alpha * 100, 2),
        "info_ratio": round(info_ratio, 2),
        "benchmark_return": round(bench_return * 100, 2),
    }


def _get_nav_at_date(code: str, date: str) -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT unit_nav FROM fund_nav WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
        (code, date)
    ).fetchone()
    conn.close()
    return float(row["unit_nav"]) if row and row["unit_nav"] else 0


def _calc_xirr(cash_flows: list) -> float:
    """使用Newton-Raphson迭代计算内部收益率(XIRR)。
    cash_flows: [(date_str, amount)]，负数为投入，正数为回收。
    """
    if not cash_flows or len(cash_flows) < 2:
        return 0.0

    # 以第一天为基准，计算每笔现金流的天数偏移
    base_date = pd.Timestamp(cash_flows[0][0])
    times = []
    amounts = []

    for date_str, amount in cash_flows:
        days = (pd.Timestamp(date_str) - base_date).days
        years = days / 365.0
        times.append(years)
        amounts.append(amount)

    total_in = -sum(a for a in amounts if a < 0)
    total_out = sum(a for a in amounts if a > 0)
    if total_in == 0 or total_out == 0:
        return 0.0

    # Newton-Raphson迭代
    guess = 0.10  # 初始猜测10%
    for _ in range(100):
        npv = 0
        dnpv = 0  # 导数
        for t, a in zip(times, amounts):
            factor = (1 + guess) ** t
            npv += a / factor
            if t > 0:
                dnpv += -t * a / ((1 + guess) ** (t + 1))
        if abs(dnpv) < 1e-12:
            break
        guess_new = guess - npv / dnpv
        if abs(guess_new - guess) < 1e-8:
            guess = guess_new
            break
        guess = max(-0.99, min(10.0, guess_new))  # 限制在合理范围

    return guess if -0.5 <= guess <= 5.0 else 0.0


def _save_backtest_record(mode, start, end, rebalance_months, top_n,
                          metrics, benchmark_code):
    conn = get_connection()
    conn.execute("""
        INSERT INTO backtest_record
        (strategy_name, mode, start_date, end_date, rebalance_months, top_n,
         total_return, annual_return, max_drawdown, sharpe, win_rate, alpha, info_ratio,
         benchmark_name, benchmark_return, params_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"{mode}_策略_指数型", mode, start, end, rebalance_months, top_n,
        metrics.get("total_return", 0), metrics.get("annual_return", 0),
        metrics.get("max_drawdown", 0), metrics.get("sharpe", 0),
        metrics.get("win_rate", 0), metrics.get("alpha", 0),
        metrics.get("info_ratio", 0),
        benchmark_code, metrics.get("benchmark_return", 0),
        str({"rebalance_months": rebalance_months, "top_n": top_n}),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()
