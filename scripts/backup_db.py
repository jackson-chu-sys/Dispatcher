#!/usr/bin/env python3
"""SQLite 在线热备份（sqlite3 backup API，不锁库不影响服务）。

- 备份到 data/backups/dispatcher-YYYYMMDD-HHMMSS.db.gz
- 保留最近 N 份（默认 14），更旧的自动删除
- 备份后立即校验完整性（PRAGMA integrity_check）
- 静默成功（exit 0 无输出），异常时打印并 exit 1（便于 cron watchdog 报警）

用法：.venv/bin/python scripts/backup_db.py [--keep N]
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("DISPATCHER_DB", os.path.join(BASE, "data", "dispatcher.db"))
BACKUP_DIR = os.path.join(BASE, "data", "backups")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=14, help="保留最近 N 份备份")
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"BACKUP-SKIP: 数据库不存在 {DB}")
        return 0

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(CST).strftime("%Y%m%d-%H%M%S")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", dir=BACKUP_DIR)
    os.close(tmp_fd)
    try:
        src = sqlite3.connect(DB)
        dst = sqlite3.connect(tmp_path)
        try:
            with dst:
                src.backup(dst)          # 在线热备，不阻塞写
            # 完整性校验
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise RuntimeError(f"备份完整性校验失败: {ok}")
        finally:
            src.close()
            dst.close()

        gz_path = os.path.join(BACKUP_DIR, f"dispatcher-{ts}.db.gz")
        with open(tmp_path, "rb") as fin, gzip.open(gz_path, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # 轮换：保留最近 keep 份
    backups = sorted(f for f in os.listdir(BACKUP_DIR)
                     if f.startswith("dispatcher-") and f.endswith(".db.gz"))
    for old in backups[: max(0, len(backups) - args.keep)]:
        os.remove(os.path.join(BACKUP_DIR, old))

    size = os.path.getsize(gz_path)
    # 每天第一份备份打一行日志（cron 静默策略：常规无输出）
    marker = os.path.join(BACKUP_DIR, ".last_logged_day")
    today = datetime.now(CST).strftime("%Y-%m-%d")
    logged = open(marker).read().strip() if os.path.exists(marker) else ""
    if logged != today:
        with open(marker, "w") as f:
            f.write(today)
        print(f"BACKUP-OK: {os.path.basename(gz_path)} ({size} bytes), 现存 {len(backups)} 份")
    return 0


if __name__ == "__main__":
    sys.exit(main())
