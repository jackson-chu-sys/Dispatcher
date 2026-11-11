#!/usr/bin/env python3
"""清空 DEMO 数据并重新播种（保留表结构）。

用法：.venv/bin/python scripts/reset_demo.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("DISPATCHER_DB", os.path.join(BASE, "data", "dispatcher.db"))
sys.path.insert(0, BASE)

from app import db  # noqa: E402

TABLES = ["ride_requests", "trips", "arrivals", "events", "shifts", "stops", "routes", "drivers", "vehicles"]


def main() -> None:
    if os.path.exists(DB):
        conn = sqlite3.connect(DB)
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
        # 重置自增序列，避免重新播种后 id 与旧引用错位
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        print(f"已清空 {DB}")
    db.init_db()          # 重新建表 + 播种 + 生成今日行程
    print("已重新播种演示数据")
    conn = db.connect()
    print("车辆", conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0],
          "| 班次", conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0],
          "| 站点", conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
