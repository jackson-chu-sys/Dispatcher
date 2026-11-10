"""SQLite 存储层：建表 + 种子数据（DEMO 阶段单文件库，无数据库服务）。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
DB_PATH = os.environ.get("DISPATCHER_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "dispatcher.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT NOT NULL,
    kind TEXT NOT NULL,              -- 大巴 / 中巴 / 摆渡车(电动)
    seats INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'idle'   -- idle / running / off
);
CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    vehicle_id INTEGER,
    on_duty INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    direction TEXT NOT NULL DEFAULT 'loop',
    color TEXT NOT NULL DEFAULT '#2f6fed'
);
CREATE TABLE IF NOT EXISTS stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL,
    vehicle_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    depart_time TEXT NOT NULL         -- HH:MM
);
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL,
    day TEXT NOT NULL,                -- YYYY-MM-DD
    status TEXT NOT NULL DEFAULT 'waiting',  -- waiting / running / done
    current_stop_id INTEGER,
    arrived_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ride_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rider TEXT NOT NULL DEFAULT '乘客',
    from_stop_id INTEGER NOT NULL,
    to_stop_id INTEGER NOT NULL,
    people INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'waiting',  -- waiting / accepted / boarded / done / cancelled
    vehicle_id INTEGER,
    driver_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_stops_route ON stops(route_id, seq);
CREATE INDEX IF NOT EXISTS idx_trips_day ON trips(day);
"""


def now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(seed: bool = True) -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        if seed and conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 0:
            _seed(conn)
            conn.commit()
        _ensure_today_trips(conn)
        conn.commit()
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    vehicles = [
        ("粤B·D1234", "大巴", 33),
        ("粤B·D5678", "中巴", 19),
        ("摆渡车 01", "摆渡车(电动)", 8),
        ("摆渡车 02", "摆渡车(电动)", 8),
    ]
    vids = []
    for plate, kind, seats in vehicles:
        vids.append(
            conn.execute(
                "INSERT INTO vehicles(plate, kind, seats) VALUES (?,?,?)", (plate, kind, seats)
            ).lastrowid
        )

    drivers = [
        ("张伟", "13800000001"),
        ("李强", "13800000002"),
        ("王磊", "13800000003"),
        ("陈静", "13800000004"),
    ]
    dids = []
    for name, phone in drivers:
        dids.append(
            conn.execute(
                "INSERT INTO drivers(name, phone, vehicle_id) VALUES (?,?,?)", (name, phone, None)
            ).lastrowid
        )
    # 司机 ↔ 车辆 一一对应
    for did, vid in zip(dids, vids):
        conn.execute("UPDATE drivers SET vehicle_id=? WHERE id=?", (vid, did))

    route_a = conn.execute(
        "INSERT INTO routes(name, direction, color) VALUES (?,?,?)", ("园区环线 A", "loop", "#2f6fed")
    ).lastrowid
    route_b = conn.execute(
        "INSERT INTO routes(name, direction, color) VALUES (?,?,?)", ("地铁接驳 B", "loop", "#e8890c")
    ).lastrowid

    stops_a = [
        ("南门", 22.5400, 113.9300),
        ("A 栋", 22.5425, 113.9322),
        ("B 栋", 22.5452, 113.9346),
        ("食堂", 22.5470, 113.9312),
        ("西门", 22.5445, 113.9272),
    ]
    stops_b = [
        ("地铁深大站", 22.5370, 113.9352),
        ("南门", 22.5400, 113.9300),
        ("C 栋", 22.5430, 113.9280),
        ("研发中心", 22.5462, 113.9262),
    ]
    for i, (name, lat, lng) in enumerate(stops_a, 1):
        conn.execute("INSERT INTO stops(route_id, seq, name, lat, lng) VALUES (?,?,?,?,?)", (route_a, i, name, lat, lng))
    for i, (name, lat, lng) in enumerate(stops_b, 1):
        conn.execute("INSERT INTO stops(route_id, seq, name, lat, lng) VALUES (?,?,?,?,?)", (route_b, i, name, lat, lng))

    shifts = [
        (route_a, vids[0], dids[0], "08:00"),
        (route_a, vids[2], dids[2], "08:30"),
        (route_a, vids[0], dids[0], "12:00"),
        (route_a, vids[1], dids[1], "17:30"),
        (route_b, vids[1], dids[1], "08:15"),
        (route_b, vids[3], dids[3], "12:30"),
        (route_b, vids[3], dids[3], "18:00"),
    ]
    conn.executemany(
        "INSERT INTO shifts(route_id, vehicle_id, driver_id, depart_time) VALUES (?,?,?,?)", shifts
    )
    conn.execute("INSERT INTO events(ts, kind, detail) VALUES (?,?,?)", (now_iso(), "seed", "初始化演示数据"))


def _ensure_today_trips(conn: sqlite3.Connection) -> None:
    """每天为每个班次生成一条 trip（幂等）。"""
    day = today_str()
    rows = conn.execute("SELECT id FROM shifts").fetchall()
    for r in rows:
        exists = conn.execute(
            "SELECT id FROM trips WHERE shift_id=? AND day=?", (r["id"], day)
        ).fetchone()
        if exists:
            continue
        first_stop = conn.execute(
            "SELECT s.id FROM stops s JOIN shifts sh ON sh.route_id=s.route_id WHERE sh.id=? ORDER BY s.seq LIMIT 1",
            (r["id"],),
        ).fetchone()
        conn.execute(
            "INSERT INTO trips(shift_id, day, status, current_stop_id, updated_at) VALUES (?,?,?,?,?)",
            (r["id"], day, "waiting", first_stop["id"] if first_stop else None, now_iso()),
        )


def log_event(conn: sqlite3.Connection, kind: str, detail: str) -> None:
    conn.execute("INSERT INTO events(ts, kind, detail) VALUES (?,?,?)", (now_iso(), kind, detail))
