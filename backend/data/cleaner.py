import pandas as pd
import numpy as np
from models.database import get_connection


def clean_nav_data(df: pd.DataFrame) -> pd.DataFrame:
    """清洗净值数据：去重、异常值处理"""
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["code", "date"])
    df = df.dropna(subset=["unit_nav"])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["unit_nav"] = pd.to_numeric(df["unit_nav"], errors="coerce")
    df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
    df = df.dropna(subset=["unit_nav"])
    if "daily_return" in df.columns:
        df["daily_return"] = df["daily_return"].clip(-0.15, 0.15)
    return df


def save_fund_list(df: pd.DataFrame):
    """保存基金列表到数据库"""
    if df.empty:
        return
    conn = get_connection()
    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    for _, row in df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO fund_basic (code, name, fund_type, updated_at)
            VALUES (?, ?, ?, ?)
        """, (row["code"], row["name"], row["fund_type"], today))
    conn.commit()
    conn.close()


def save_nav_data(df: pd.DataFrame):
    """保存净值数据到数据库，忽略重复"""
    if df.empty:
        return
    conn = get_connection()
    for _, row in df.iterrows():
        try:
            conn.execute("""
                INSERT OR IGNORE INTO fund_nav (code, date, unit_nav, acc_nav, daily_return)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(row["code"]), str(row["date"]),
                float(row.get("unit_nav", 0) or 0),
                float(row.get("acc_nav", 0) or 0),
                float(row.get("daily_return", 0) or 0),
            ))
        except Exception:
            continue
    conn.commit()
    conn.close()
