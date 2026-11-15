#!/usr/bin/env python3
"""清空 DEMO 数据并重新播种（保留表结构）。

⚠️ 防呆（2026-11-15 神朱误删事故后加）：
  - 清库前**自动备份**当前 DB 到 data/backups/（gzip），万一误删可恢复。
  - 若检测到**非种子数据**（站点/线路/班次被改过，或含真实坐标），默认**拒绝执行**，
    必须显式加 --force 才清。这样测试用的 reset 不会误伤真实运营数据。

用法：
  .venv/bin/python scripts/reset_demo.py            # 干净种子库直接重置
  .venv/bin/python scripts/reset_demo.py --force     # 有真实数据也强制重置（已自动备份）
  .venv/bin/python scripts/reset_demo.py --dry-run   # 只检测不执行
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("DISPATCHER_DB", os.path.join(BASE, "data", "dispatcher.db"))
BACKUP_DIR = os.path.join(BASE, "data", "backups")
sys.path.insert(0, BASE)

from app import db  # noqa: E402

TABLES = ["ride_requests", "trips", "arrivals", "events", "shifts", "stops", "routes", "drivers", "vehicles"]

# 种子数据的指纹（与 app/db.py 的 _seed 一致）：用于判断库是否"纯净"
SEED_STOP_NAMES = {
    "南门", "A 栋", "B 栋", "食堂", "西门",
    "地铁深大站", "C 栋", "研发中心",
}
SEED_VEHICLE_PLATES = {"粤B·D1234", "粤B·D5678", "摆渡车 01", "摆渡车 02"}


def auto_backup() -> str | None:
    """清库前自动 gzip 备份，返回备份路径（无库则 None）。"""
    if not os.path.exists(DB):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(db.CST).strftime("%Y%m%d-%H%M%S")
    gz = os.path.join(BACKUP_DIR, f"pre-reset-{ts}.db.gz")
    with open(DB, "rb") as fin, gzip.open(gz, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    return gz


def detect_real_data(conn: sqlite3.Connection) -> list[str]:
    """返回"疑似真实/非种子数据"的描述列表；空列表=纯净种子库。"""
    flags = []
    stop_names = {r[0] for r in conn.execute("SELECT name FROM stops")}
    extra_stops = stop_names - SEED_STOP_NAMES
    if extra_stops:
        sample = ", ".join(sorted(extra_stops)[:5])
        flags.append(f"站点超出种子集（+{len(extra_stops)} 个，如：{sample}）")
    plates = {r[0] for r in conn.execute("SELECT plate FROM vehicles")}
    if plates - SEED_VEHICLE_PLATES:
        flags.append(f"车辆超出种子集：{', '.join(sorted(plates - SEED_VEHICLE_PLATES))}")
    n_routes = conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    if n_routes != 2:
        flags.append(f"线路数={n_routes}（种子=2）")
    return flags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="即使检测到真实数据也强制重置（仍会先自动备份）")
    ap.add_argument("--dry-run", action="store_true", help="只检测不清库")
    args = ap.parse_args()

    if os.path.exists(DB):
        conn = sqlite3.connect(DB)
        flags = detect_real_data(conn)
        conn.close()
        if flags:
            print("⚠️  检测到疑似真实/非种子数据：")
            for f in flags:
                print("    -", f)
            if args.dry_run:
                print("(--dry-run，未执行)")
                return 0
            if not args.force:
                print("\n已中止：如需清库请加 --force（会先自动备份到 data/backups/）。")
                return 2
            print("\n--force 已指定，继续清库（先自动备份）……")

    gz = auto_backup()
    if gz:
        print(f"已自动备份当前库 → {os.path.relpath(gz, BASE)}")
    if args.dry_run:
        print("(--dry-run，未执行清库)")
        return 0

    if os.path.exists(DB):
        conn = sqlite3.connect(DB)
        for t in TABLES:
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        print(f"已清空 {DB}")
    db.init_db()
    print("已重新播种演示数据")
    conn = db.connect()
    print("车辆", conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0],
          "| 班次", conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0],
          "| 站点", conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0])
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
