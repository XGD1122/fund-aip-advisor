"""首次数据初始化 — 克隆项目后运行一次即可
步骤: 建表 -> 拉取基金列表 -> 拉取净值 -> 计算信号
耗时: 约 30-60 分钟（取决于网络，6400+ 只基金 × 历史净值）
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import init_db
from data.fetcher import fetch_all_fund_list
from data.cleaner import save_fund_list
from config import FUND_TYPE_FILTER


def main():
    t0 = time.time()

    # 1. 建表
    print("[1/4] 创建数据库表...")
    init_db()
    print("  完成")

    # 2. 拉取基金列表（一次 API 调用，几秒）
    print("[2/4] 拉取指数型基金列表...")
    df = fetch_all_fund_list(FUND_TYPE_FILTER)
    if df.empty:
        print("  失败：未能获取基金列表，请检查网络")
        return
    print(f"  获取到 {len(df)} 只基金")

    # 3. 保存基金列表
    print("[3/4] 保存基金列表到数据库...")
    save_fund_list(df)
    print("  完成")

    # 4. 拉取净值 + 计算信号（最耗时）
    print("[4/4] 拉取历史净值 + 计算技术信号（预计 30-60 分钟）...")
    from engine.top20 import refresh_all_data
    refresh_all_data()

    elapsed = (time.time() - t0) / 60
    print(f"\n全部完成！耗时 {elapsed:.0f} 分钟")
    print(f"现在可以运行 python main.py 启动系统")


if __name__ == "__main__":
    main()
