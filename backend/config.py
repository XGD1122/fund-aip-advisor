import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
DB_PATH = os.path.join(DATA_DIR, "fund.db")

# ============================================================
# 基金类型范围 — 仅指数型
# ============================================================
FUND_TYPES = ["指数型-股票", "指数型-债券", "指数型"]  # 覆盖各类指数基金子类型
FUND_TYPE_FILTER = "指数型"  # LIKE 匹配，包含所有指数型子类

# ============================================================
# 一笔买入模式 — 五维度权重（针对指数基金优化）
# 估值权重提升、技术权重降低、新增跟踪误差维度
# ============================================================
SCORE_WEIGHTS_BUY = {
    "valuation": 0.25,       # 估值：指数基金最怕买贵，从15%提升到25%
    "return_": 0.22,         # 收益：适度降低，从30%→22%
    "risk": 0.18,            # 风控：从12%→18%，更重视下行保护
    "technical": 0.15,       # 技术：从30%→15%，指数基金技术信号弱
    "fundamental": 0.10,     # 基本面：费率/规模/跟踪误差
    "tracking": 0.10,        # 跟踪误差：指数基金核心指标（新增）
}

# 子指标权重 — 一笔买入
# 注意：同维度内子权重之和 = 该维度总权重，保证每项子权重直接对应%贡献
SUB_WEIGHTS_BUY = {
    # 收益维度 (22%)：降低短期，提升长期
    "return_1m": 0.03, "return_3m": 0.05, "return_6m": 0.05,
    "return_1y": 0.06, "return_3y": 0.03,
    # 估值维度 (25%)：PE分位为核心
    "pe_percentile": 0.15,   # 指数PE分位 → 权重提升
    "nav_deviation": 0.06,   # 净值偏离MA120
    "drawdown_state": 0.04,  # 近期回撤状态
    # 风控维度 (18%)
    "max_drawdown": 0.08, "sharpe": 0.04, "volatility": 0.04, "calmar": 0.02,
    # 基本面维度 (10%)
    "fund_scale": 0.03, "fund_age": 0.03, "fee_rate": 0.04,
    # 技术维度 (15%)：从30%大幅降低
    "ma_trend": 0.06, "macd_signal": 0.03, "rsi": 0.03, "bollinger": 0.03,
    # 跟踪误差维度 (10%)：指数基金新增
    "tracking_error": 0.10,
}

# ============================================================
# 定投模式 — 六维度权重（定投核心：估值 + 趋势 + 波动率）
# ============================================================
SCORE_WEIGHTS_AIP = {
    "valuation": 0.30,       # 估值：定投最怕高位开始，权重30%
    "trend": 0.20,           # 长期趋势：MA60/MA120斜率
    "volatility": 0.15,      # 波动率：定投靠波动摊薄成本
    "risk": 0.12,            # 风控
    "return_": 0.10,         # 收益：定投不追短期，降权
    "tracking": 0.08,        # 跟踪误差
    "fundamental": 0.05,     # 基本面
}

# 子指标权重 — 定投
SUB_WEIGHTS_AIP = {
    # 估值 (30%)
    "pe_percentile": 0.18, "nav_deviation": 0.08, "drawdown_state": 0.04,
    # 长期趋势 (20%)
    "ma60_slope": 0.10, "ma120_slope": 0.10,
    # 波动率 (15%)：定投需要适度波动（区间最优，非线性）
    "volatility_aip": 0.15,
    # 风控 (12%)
    "max_drawdown": 0.07, "sharpe": 0.05,
    # 收益 (10%)
    "return_1y": 0.06, "return_3y": 0.04,
    # 跟踪误差 (8%)
    "tracking_error": 0.08,
    # 基本面 (5%)
    "fund_scale": 0.02, "fund_age": 0.02, "fee_rate": 0.01,
}

# ============================================================
# 维度→指标映射（按模式区分，修复AIP维度缺失Bug）
# ============================================================
def get_dim_indicator_map(mode: str = "buy") -> dict:
    """根据模式返回维度→子指标列表的映射"""
    if mode == "aip":
        return {
            "valuation": ["pe_percentile", "nav_deviation", "drawdown_state"],
            "trend": ["ma60_slope", "ma120_slope"],
            "volatility": ["volatility_aip"],
            "risk": ["max_drawdown", "sharpe"],
            "return_": ["return_1y", "return_3y"],
            "tracking": ["tracking_error"],
            "fundamental": ["fund_scale", "fund_age", "fee_rate"],
        }
    else:  # buy
        return {
            "return_": ["return_1m", "return_3m", "return_6m", "return_1y", "return_3y"],
            "valuation": ["pe_percentile", "nav_deviation", "drawdown_state"],
            "risk": ["max_drawdown", "sharpe", "volatility", "calmar"],
            "technical": ["ma_trend", "macd_signal", "rsi", "bollinger"],
            "fundamental": ["fund_scale", "fund_age", "fee_rate"],
            "tracking": ["tracking_error"],
        }

# ============================================================
# 指数基金专属参数
# ============================================================
# PE分位阈值（用于风险标签）
PE_PERCENTILE_HIGH = 85       # ≥85% = 高位警告
PE_PERCENTILE_WARN = 80       # ≥80% = 偏高
PE_PERCENTILE_LOW = 20        # ≤20% = 低位机会
PE_PERCENTILE_FAIR = 40       # ≤40% = 偏低

# 跟踪误差阈值（年化）
TRACKING_ERROR_MAX = 0.04     # >4% 年化跟踪误差 → 严重扣分
TRACKING_ERROR_WARN = 0.02    # >2% → 开始扣分

# 短期涨幅过热警告
SURGE_3M_WARNING = 0.20       # 近3月涨超20% → 过热信号
MA_DEVIATION_WARNING = 0.20   # 偏离MA120超20% → 高位信号

# ============================================================
# 定投时机信号参数（买卖时刻推荐）
# ============================================================
# -- 买入信号触发阈值 --
BUY_PE_PERCENTILE = 20           # PE分位 ≤ 20% → 估值低位买入信号
BUY_OVERSOLD_DRAWDOWN = 0.15     # 距60日高点回撤 >15% → 超跌信号
BUY_OVERSOLD_RSI = 30            # RSI < 30 → 超卖
BUY_MA_CROSSOVER_DAYS = 5        # MA5上穿MA20 检查窗口
BUY_MA120_SUPPORT_DEVIATION = 0.03  # 净值偏离MA120 <3% → 均线支撑

# -- 卖出信号触发阈值 --
SELL_PE_PERCENTILE = 85          # PE分位 ≥ 85% → 估值高位卖出信号
SELL_TREND_BREAK_SLOPE = -0.05   # MA120近20日斜率 < -5% → 趋势破位
SELL_SURGE_3M = 0.25             # 近3月涨幅 >25% → 短期过热
SELL_OVERBOUGHT_RSI = 75         # RSI > 75 → 超买
SELL_MACD_DEAD_CROSS = True      # MACD死叉 → 技术见顶

# -- 定投额度倍数 --
AIP_MULTIPLIER_DOUBLE = 2.0      # PE分位≤20%且买入信号 → 加倍
AIP_MULTIPLIER_INCREASE = 1.5    # PE分位≤40% → 增投
AIP_MULTIPLIER_NORMAL = 1.0      # 正常定投
AIP_MULTIPLIER_REDUCE = 0.5      # PE分位≥80%或趋势转坏 → 减半
AIP_MULTIPLIER_PAUSE = 0.0       # PE分位≥85%且高位警告 → 暂停
AIP_NORMAL_PE_UPPER = 70         # 正常定投PE分位上界

# -- 止盈参数 --
STOP_PROFIT_PARTIAL = 0.30       # 累计收益 >30% → 建议卖出1/3
STOP_PROFIT_FULL = 0.50          # 累计收益 >50% 且 PE分位 >70% → 建议全部止盈
STOP_PROFIT_PE_THRESHOLD = 70    # 全部止盈需要的PE分位条件

# -- 时机综合评分权重 --
TIMING_WEIGHTS = {
    "valuation": 0.35,            # 估值权重最高
    "trend": 0.25,                # 趋势
    "technical": 0.20,            # 技术信号
    "risk": 0.20,                 # 风险状态
}

# ============================================================
# 通用参数
# ============================================================
RISK_FREE_RATE = 0.017        # 当前中国10年期国债收益率 ~1.7%
TOP_N_DEFAULT = 20
REQUEST_DELAY_MIN = 0.5       # 最小请求间隔（秒）
REQUEST_DELAY_MAX = 1.5       # 最大请求间隔（秒），避免请求过快被限流
TRAIN_TEST_SPLIT_DATE = "2024-01-01"
NAV_MAX_STALE_DAYS = 90       # 净值过期天数：超过此天数无更新的基金视为已停售，排除出排名
NAV_MIN_RECORDS = 60          # 最少净值记录数：不足此数量的基金数据不充分，排除出排名
