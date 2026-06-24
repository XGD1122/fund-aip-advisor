from fastapi import APIRouter, Query, HTTPException, Body
from typing import Optional, List
from engine.rank import rank_all_funds, get_top_funds, get_fund_detail_with_score, update_signals
from engine.backtest import run_backtest, run_aip_backtest
from engine.scorer import score_one_fund_buy, score_one_fund_aip
from engine.aip_advisor import get_timing_signals, scan_opportunities, check_portfolio
from models.database import get_connection
from config import (
    TOP_N_DEFAULT, SCORE_WEIGHTS_BUY, SCORE_WEIGHTS_AIP,
    SUB_WEIGHTS_BUY, SUB_WEIGHTS_AIP,
    FUND_TYPE_FILTER, RISK_FREE_RATE,
)

router = APIRouter(prefix="/api")


# ---- 筛选 & 排名 ----

@router.get("/funds/top")
def api_top_funds(
    mode: str = Query("buy", pattern=r"^(buy|aip)$"),
    fund_type: Optional[str] = None,
    top_n: int = TOP_N_DEFAULT,
    refresh: bool = False,
):
    """获取Top-N基金排名"""
    if refresh:
        update_signals()
    results = get_top_funds(mode=mode, fund_type=fund_type, top_n=top_n)
    return {"count": len(results), "mode": mode, "results": results}


@router.get("/funds/rank")
def api_rank_all(
    mode: str = Query("buy", pattern=r"^(buy|aip)$"),
    fund_type: Optional[str] = None,
    refresh: bool = False,
):
    """全量排名"""
    if refresh:
        update_signals()
    results = rank_all_funds(mode=mode, fund_type_filter=fund_type)
    return {"count": len(results), "results": results}


# ---- 基金详情 ----

@router.get("/funds/{code}")
def api_fund_detail(code: str):
    """单只基金详情"""
    data = get_fund_detail_with_score(code)
    if not data.get("basic"):
        raise HTTPException(404, "基金不存在")
    return data


@router.get("/funds/{code}/score")
def api_fund_score(code: str, mode: str = Query("buy", pattern=r"^(buy|aip)$")):
    """实时计算单只基金评分"""
    if mode == "buy":
        score = score_one_fund_buy(code)
    else:
        score = score_one_fund_aip(code)
    return {"code": code, "mode": mode, **score}


# ---- 回测 ----

@router.get("/backtest")
def api_backtest(
    start_date: str = Query("2022-01-01"),
    end_date: str = Query("2025-12-31"),
    mode: str = Query("buy", pattern=r"^(buy|aip)$"),
    rebalance_months: int = Query(3, ge=1, le=12),
    top_n: int = Query(10, ge=1, le=50),
):
    """执行回测"""
    result = run_backtest(
        start_date=start_date,
        end_date=end_date,
        mode=mode,
        rebalance_months=rebalance_months,
        top_n=top_n,
    )
    return result


@router.get("/backtest/aip")
def api_aip_backtest(
    start_date: str = Query("2022-01-01"),
    end_date: str = Query("2025-12-31"),
    monthly_amount: float = Query(1000, ge=100),
    top_n: int = Query(5, ge=1, le=20),
):
    """定投回测"""
    result = run_aip_backtest(
        start_date=start_date,
        end_date=end_date,
        monthly_amount=monthly_amount,
        top_n=top_n,
    )
    return result


# ---- 定投时机顾问（买卖时刻推荐）----

@router.get("/aip/timing/{code}")
def api_aip_timing(code: str, cost_nav: float = Query(None, description="持仓成本净值（可选，用于止盈计算）")):
    """单只基金完整时机分析：买入/卖出信号 + 定投倍数 + 止盈建议"""
    result = get_timing_signals(code, cost_nav=cost_nav)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/aip/opportunities")
def api_aip_opportunities(
    min_score: float = Query(60, ge=0, le=100, description="最小时机评分"),
    top_n: int = Query(20, ge=1, le=100),
):
    """全市场定投机会扫描：返回当前适合定投的基金"""
    results = scan_opportunities(min_timing_score=min_score, top_n=top_n)
    return {"count": len(results), "min_timing_score": min_score, "opportunities": results}


@router.post("/aip/portfolio/check")
def api_aip_portfolio_check(holdings: List[dict] = Body(..., description="持仓列表")):
    """持仓诊断：分析每只基金的当前建议（加仓/持有/减仓/止盈）"""
    result = check_portfolio(holdings)
    return result


# ---- 数据刷新 ----

@router.post("/admin/refresh")
def api_refresh_data():
    """拉取最新净值 + 更新技术信号（耗时较长，建议收盘后调用）"""
    from engine.rank import refresh_all_data
    refresh_all_data()
    return {"status": "ok", "message": "数据刷新完成"}


# ---- 配置 ----

@router.get("/config/weights")
def api_get_weights():
    """获取当前权重配置"""
    return {
        "mode": "指数型基金",
        "risk_free_rate": RISK_FREE_RATE,
        "buy": {
            "dim_weights": SCORE_WEIGHTS_BUY,
            "sub_weights": SUB_WEIGHTS_BUY,
        },
        "aip": {
            "dim_weights": SCORE_WEIGHTS_AIP,
            "sub_weights": SUB_WEIGHTS_AIP,
        },
    }


# ---- 概览统计 ----

@router.get("/stats")
def api_stats():
    """系统概览统计"""
    conn = get_connection()
    fund_count = conn.execute("SELECT COUNT(*) FROM fund_basic").fetchone()[0]
    nav_count = conn.execute("SELECT COUNT(*) FROM fund_nav").fetchone()[0]
    latest_score_date = conn.execute(
        "SELECT MAX(calc_date) FROM fund_score"
    ).fetchone()[0]
    backtest_count = conn.execute("SELECT COUNT(*) FROM backtest_record").fetchone()[0]
    conn.close()
    return {
        "fund_count": fund_count,
        "nav_records": nav_count,
        "latest_score_date": latest_score_date,
        "backtest_count": backtest_count,
    }
