"""独立数据刷新脚本 — 供 Windows 计划任务每日调用，无需启动 Web 服务器"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models.database import init_db
from engine.rank import refresh_all_data

if __name__ == "__main__":
    init_db()
    refresh_all_data()
    print("数据刷新完成")
