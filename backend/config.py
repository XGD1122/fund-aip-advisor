import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "data")
DB_PATH = os.path.join(DATA_DIR, "fund.db")

# ============================================================
# 基金筛选
# ============================================================
FUND_TYPE_FILTER = "指数型"

# ============================================================
# 数据拉取参数
# ============================================================
REQUEST_DELAY_MIN = 0.05
REQUEST_DELAY_MAX = 0.2
NAV_MAX_STALE_DAYS = 90
NAV_MIN_RECORDS = 60

# ============================================================
# 评分阈值
# ============================================================
FLAT_LINE_THRESHOLD = 0.0001       # 横盘基金：日均绝对值 < 0.01%
PROFITABILITY_1Y_MIN = 0.02        # 1年最低收益 2%
TOP_N_DEFAULT = 20
RISK_FREE_RATE = 0.017
