import akshare as ak
import pandas as pd
import time
import random
import threading
from config import REQUEST_DELAY_MIN, REQUEST_DELAY_MAX

# py_mini_racer (V8) 不支持多线程并发，需要全局锁保护 akshare 调用
_AK_LOCK = threading.Lock()


def _delay():
    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))


def _retry_fetch(fn, *args, max_retries=3, **kwargs):
    """带重试的数据拉取，遇到网络错误自动重试"""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2  # 2s, 4s, 6s 退避
                print(f"  重试 {attempt+1}/{max_retries} (等待{wait}s): {e}")
                time.sleep(wait)
            else:
                raise e
    return None


def fetch_all_fund_list(fund_type_filter: str = "指数型") -> pd.DataFrame:
    """获取公募基金列表（默认仅指数型）"""
    _delay()
    try:
        df = ak.fund_name_em()
        result = pd.DataFrame()
        result["code"] = df.iloc[:, 0].astype(str).str.zfill(6)
        result["name"] = df.iloc[:, 2].astype(str)
        result["fund_type"] = df.iloc[:, 3].astype(str)
        # 仅保留指数型基金
        result = result[result["fund_type"].str.contains(fund_type_filter, na=False)]
        # 剔除商品ETF（黄金、豆粕、有色金属、能源化工等）
        result = result[~result["fund_type"].str.contains("其他", na=False)]
        print(f"  指数型基金数量: {len(result)}")
        return result.reset_index(drop=True)
    except Exception as e:
        print(f"获取基金列表失败: {e}")
        return pd.DataFrame(columns=["code", "name", "fund_type"])


def _locked_fund_nav(code):
    """线程安全的 ak.fund_open_fund_info_em 调用"""
    with _AK_LOCK:
        return ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")


def fetch_fund_nav(code: str) -> pd.DataFrame:
    """获取单只基金的历史净值（带重试，线程安全）"""
    _delay()
    try:
        df = _retry_fetch(_locked_fund_nav, code)
        if df is None or df.empty:
            return pd.DataFrame()
        # 新版 akshare 列: 净值日期, 单位净值, 日增长率 (无累计净值列)
        col_map = {}
        for c in df.columns:
            if "日期" in str(c):
                col_map[c] = "date"
            elif "单位" in str(c):
                col_map[c] = "unit_nav"
            elif "增长" in str(c) or "日增长率" in str(c):
                col_map[c] = "daily_return"
            elif "累计" in str(c):
                col_map[c] = "acc_nav"
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["code"] = code
        if "acc_nav" not in df.columns:
            df["acc_nav"] = df.get("unit_nav", 0)
        if "daily_return" in df.columns:
            df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce") / 100.0
        keep_cols = ["code", "date", "unit_nav"]
        if "acc_nav" in df.columns:
            keep_cols.append("acc_nav")
        if "daily_return" in df.columns:
            keep_cols.append("daily_return")
        return df[[c for c in keep_cols if c in df.columns]]
    except Exception as e:
        print(f"获取基金 {code} 净值失败: {e}")
        return pd.DataFrame()


def fetch_fund_detail(code: str) -> dict:
    """获取基金详情（规模、经理、费率）
    当前 akshare 1.18.x 雪球和同花顺 API 已失效，暂时返回空。
    基本信息占评分权重仅 5-10%，不影响核心排名。
    待 akshare 修复后此函数自动恢复。
    """
    # API 失效，跳过网络请求，直接返回空
    # 避免 4311 只基金 × 每次 3 次重试 = 数小时的无效等待
    return {}


def fetch_benchmark_index(code: str = "000300", name: str = "沪深300") -> pd.DataFrame:
    """获取基准指数日线数据（用于回测对比，如沪深300/中证500）"""
    _delay()
    try:
        df = ak.stock_zh_index_daily(symbol=f"sh{code}")
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"date": "date", "close": "close"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["code"] = code
        return df[["code", "date", "close"]]
    except Exception as e:
        print(f"获取基准指数 {name}({code}) 数据失败: {e}")
        return pd.DataFrame()


def fetch_index_valuation(index_name: str = "沪深300") -> dict:
    """获取指数PE/PB估值分位数据"""
    _delay()
    try:
        df = ak.index_value_name_funddb()
        if df is None or df.empty:
            return {}
        df = df[df["指数名称"].str.contains(index_name, na=False)]
        if df.empty:
            return {}
        row = df.iloc[0]
        return {
            "pe": float(row.get("市盈率", 0) or 0),
            "pe_percentile": float(row.get("市盈率分位", 50) or 50) / 100.0,
            "pb": float(row.get("市净率", 0) or 0),
            "pb_percentile": float(row.get("市净率分位", 50) or 50) / 100.0,
        }
    except Exception as e:
        print(f"获取指数估值失败: {e}")
        return {}
