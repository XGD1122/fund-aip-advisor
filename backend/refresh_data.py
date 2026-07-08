"""独立数据刷新脚本 — 供 Windows 计划任务每日调用"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import init_db
from engine.top20 import refresh_daily

if __name__ == "__main__":
    init_db()
    refresh_daily()
    print("数据刷新完成")
