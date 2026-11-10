"""Dispatcher DEMO —— 班车/摆渡车调度后端（FastAPI + SQLite）。

角色入口：
  /dispatcher  调度端（地图/车辆/派单/班次）
  /driver      司机端（我的班次、到站上报、接单）
  /rider       乘客端（选起终点、叫车、看车到哪）
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="Dispatcher DEMO", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

MAP_KEY = os.environ.get("TENCENT_MAP_KEY", "").strip()


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------- 基础数据

def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def _stops_by_route(conn) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for s in _rows(conn, "SELECT * FROM stops ORDER BY route_id, seq"):
        out.setdefault(s["route_id"], []).append(s)
    return out


def _vehicles_state(conn) -> list[dict]:
    """车辆当前位置取自今天最近一条 trip 的 current_stop（到站触发）。"""
    day = db.today_str()
    out = []
    vehicles = _rows(conn, "SELECT * FROM vehicles ORDER BY id")
    for v in vehicles:
        row = _one(
            conn,
            """SELECT t.id AS trip_id, t.current_stop_id, t.arrived_at, t.status AS trip_status,
                      sh.id AS shift_id, sh.route_id, sh.depart_time, sh.driver_id, r.name AS route_name, r.color,
                      st.name AS stop_name, st.seq AS stop_seq, st.lat, st.lng
               FROM shifts sh
               JOIN trips t ON t.shift_id = sh.id AND t.day = ?
               JOIN routes r ON r.id = sh.route_id
               LEFT JOIN stops st ON st.id = t.current_stop_id
               WHERE sh.vehicle_id = ?
               ORDER BY t.arrived_at DESC, sh.depart_time DESC LIMIT 1""",
            (day, v["id"]),
        )
        driver = _one(conn, "SELECT name, phone FROM drivers WHERE vehicle_id=?", (v["id"],))
        out.append(
            {
                **v,
                "driver": driver["name"] if driver else None,
                "route_id": row["route_id"] if row else None,
                "route_name": row["route_name"] if row else None,
                "color": row["color"] if row else "#888",
                "trip_id": row["trip_id"] if row else None,
                "shift_id": row["shift_id"] if row else None,
                "depart_time": row["depart_time"] if row else None,
                "stop_name": row["stop_name"] if row else None,
                "stop_seq": row["stop_seq"] if row else None,
                "lat": row["lat"] if row else None,
                "lng": row["lng"] if row else None,
                "arrived_at": row["arrived_at"] if row else None,
            }
        )
    return out


@app.get("/api/state")
def api_state():
    conn = db.connect()
    try:
        day = db.today_str()
        routes = _rows(conn, "SELECT * FROM routes ORDER BY id")
        stops = _stops_by_route(conn)
        for r in routes:
            r["stops"] = stops.get(r["id"], [])
        rides = _rows(
            conn,
            """SELECT rr.*, fs.name AS from_name, ts.name AS to_name, v.plate, d.name AS driver_name
               FROM ride_requests rr
               JOIN stops fs ON fs.id = rr.from_stop_id
               JOIN stops ts ON ts.id = rr.to_stop_id
               LEFT JOIN vehicles v ON v.id = rr.vehicle_id
               LEFT JOIN drivers d ON d.id = rr.driver_id
               WHERE rr.status IN ('waiting','accepted','boarded')
               ORDER BY rr.created_at""",
        )
        shifts = _rows(
            conn,
            """SELECT sh.*, r.name AS route_name, r.color, v.plate, d.name AS driver_name,
                      t.id AS trip_id, t.status AS trip_status, t.current_stop_id, t.arrived_at,
                      st.name AS stop_name
               FROM shifts sh
               JOIN routes r ON r.id = sh.route_id
               JOIN vehicles v ON v.id = sh.vehicle_id
               JOIN drivers d ON d.id = sh.driver_id
               JOIN trips t ON t.shift_id = sh.id AND t.day = ?
               LEFT JOIN stops st ON st.id = t.current_stop_id
               ORDER BY sh.depart_time""",
            (day,),
        )
        events = _rows(conn, "SELECT * FROM events ORDER BY id DESC LIMIT 12")
        vehicles = _vehicles_state(conn)
        stats = {
            "vehicles_total": len(vehicles),
            "vehicles_online": sum(1 for v in vehicles if v["arrived_at"]),
            "rides_waiting": sum(1 for r in rides if r["status"] == "waiting"),
            "rides_active": len(rides),
            "shifts_total": len(shifts),
            "shifts_done": sum(1 for s in shifts if s["trip_status"] == "done"),
        }
        return {
            "now": db.now_iso(),
            "day": day,
            "map_key": MAP_KEY,
            "stats": stats,
            "vehicles": vehicles,
            "routes": routes,
            "rides": rides,
            "shifts": shifts,
            "events": events,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------- 司机端

@app.get("/api/driver/{driver_id}")
def api_driver(driver_id: int):
    conn = db.connect()
    try:
        d = _one(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        v = _one(conn, "SELECT * FROM vehicles WHERE id=?", (d["vehicle_id"],))
        day = db.today_str()
        shifts = _rows(
            conn,
            """SELECT sh.*, r.name AS route_name, r.color, t.id AS trip_id, t.status AS trip_status,
                      t.current_stop_id, st.name AS stop_name, st.seq AS stop_seq
               FROM shifts sh
               JOIN routes r ON r.id = sh.route_id
               JOIN trips t ON t.shift_id = sh.id AND t.day = ?
               LEFT JOIN stops st ON st.id = t.current_stop_id
               WHERE sh.driver_id = ?
               ORDER BY sh.depart_time""",
            (day, driver_id),
        )
        for s in shifts:
            s["shift_id"] = s["id"]
            s["stops"] = _rows(conn, "SELECT * FROM stops WHERE route_id=? ORDER BY seq", (s["route_id"],))
        rides = _rows(
            conn,
            """SELECT rr.*, fs.name AS from_name, ts.name AS to_name
               FROM ride_requests rr
               JOIN stops fs ON fs.id = rr.from_stop_id
               JOIN stops ts ON ts.id = rr.to_stop_id
               WHERE rr.status IN ('waiting','accepted','boarded')
                 AND (rr.driver_id IS NULL OR rr.driver_id = ?)
               ORDER BY rr.created_at""",
            (driver_id,),
        )
        return {"driver": d, "vehicle": v, "day": day, "shifts": shifts, "rides": rides}
    finally:
        conn.close()


class ArriveIn(BaseModel):
    stop_id: int
    shift_id: int | None = None


def _current_trip(conn, driver_id: int, shift_id: int | None = None):
    """司机的当前班次行程：显式指定 > 正在跑的 > 今天最早未完成的。"""
    day = db.today_str()
    if shift_id:
        return _one(
            conn,
            """SELECT t.*, sh.route_id FROM trips t JOIN shifts sh ON sh.id=t.shift_id
               WHERE t.shift_id=? AND t.day=?""",
            (shift_id, day),
        )
    return _one(
        conn,
        """SELECT t.*, sh.route_id FROM trips t JOIN shifts sh ON sh.id=t.shift_id
           WHERE sh.driver_id=? AND t.day=? AND t.status<>'done'
           ORDER BY CASE WHEN t.status='running' THEN 0 ELSE 1 END, sh.depart_time
           LIMIT 1""",
        (driver_id, day),
    )


@app.get("/api/drivers")
def api_drivers():
    conn = db.connect()
    try:
        return _rows(
            conn,
            """SELECT d.id, d.name, d.phone, d.vehicle_id, v.plate, v.kind, v.seats
               FROM drivers d LEFT JOIN vehicles v ON v.id = d.vehicle_id ORDER BY d.id""",
        )
    finally:
        conn.close()


@app.post("/api/driver/{driver_id}/arrive")
def api_arrive(driver_id: int, body: ArriveIn):
    """到站上报：把该司机当前班次的行程位置更新到指定站点。"""
    conn = db.connect()
    try:
        d = _one(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        trip = _current_trip(conn, driver_id, body.shift_id)
        if not trip:
            raise HTTPException(404, "今日没有可用班次")
        stop = _one(conn, "SELECT * FROM stops WHERE id=?", (body.stop_id,))
        if not stop:
            raise HTTPException(404, "站点不存在")
        if stop["route_id"] != trip["route_id"]:
            raise HTTPException(400, "该站点不属于当前班次线路")
        conn.execute(
            "UPDATE trips SET current_stop_id=?, arrived_at=?, status='running', updated_at=? WHERE id=?",
            (body.stop_id, db.now_iso(), db.now_iso(), trip["id"]),
        )
        conn.execute("UPDATE vehicles SET status='running' WHERE id=?", (d["vehicle_id"],))
        db.log_event(conn, "arrive", f"{d['name']} 到达 {stop['name']}")
        conn.commit()
        return {"ok": True, "trip_id": trip["id"], "stop": stop["name"], "at": db.now_iso()}
    finally:
        conn.close()


class StartIn(BaseModel):
    shift_id: int | None = None


@app.post("/api/driver/{driver_id}/start")
def api_start(driver_id: int, body: StartIn | None = None):
    conn = db.connect()
    try:
        d = _one(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        trip = _current_trip(conn, driver_id, body.shift_id if body else None)
        if not trip:
            raise HTTPException(404, "今日没有可用班次")
        conn.execute(
            "UPDATE trips SET status='running', updated_at=? WHERE id=?", (db.now_iso(), trip["id"])
        )
        db.log_event(conn, "start", f"{d['name']} 发车（班次 #{trip['shift_id']}）")
        conn.commit()
        return {"ok": True, "trip_id": trip["id"]}
    finally:
        conn.close()


# ---------------------------------------------------------------- 乘客端

@app.get("/api/rider/options")
def api_rider_options():
    conn = db.connect()
    try:
        routes = _rows(conn, "SELECT * FROM routes ORDER BY id")
        stops = _stops_by_route(conn)
        for r in routes:
            r["stops"] = stops.get(r["id"], [])
        return {"routes": routes}
    finally:
        conn.close()


class RideIn(BaseModel):
    rider: str = Field(default="乘客", max_length=20)
    from_stop_id: int
    to_stop_id: int
    people: int = 1


@app.post("/api/ride")
def api_create_ride(body: RideIn):
    if body.from_stop_id == body.to_stop_id:
        raise HTTPException(400, "起点和终点不能相同")
    conn = db.connect()
    try:
        for sid in (body.from_stop_id, body.to_stop_id):
            if not _one(conn, "SELECT id FROM stops WHERE id=?", (sid,)):
                raise HTTPException(404, "站点不存在")
        cur = conn.execute(
            """INSERT INTO ride_requests(rider, from_stop_id, to_stop_id, people, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (body.rider, body.from_stop_id, body.to_stop_id, max(1, body.people), db.now_iso(), db.now_iso()),
        )
        db.log_event(conn, "ride_new", f"{body.rider} 叫车 #{cur.lastrowid}")
        conn.commit()
        return {"ok": True, "ride_id": cur.lastrowid}
    finally:
        conn.close()


def _ride_detail(conn, ride_id: int) -> dict:
    ride = _one(
        conn,
        """SELECT rr.*, fs.name AS from_name, ts.name AS to_name, fs.lat AS from_lat, fs.lng AS from_lng,
                  v.plate, v.kind, d.name AS driver_name
           FROM ride_requests rr
           JOIN stops fs ON fs.id = rr.from_stop_id
           JOIN stops ts ON ts.id = rr.to_stop_id
           LEFT JOIN vehicles v ON v.id = rr.vehicle_id
           LEFT JOIN drivers d ON d.id = rr.driver_id
           WHERE rr.id=?""",
        (ride_id,),
    )
    if not ride:
        raise HTTPException(404, "叫车单不存在")
    vehicle = None
    if ride["vehicle_id"]:
        vehicle = _one(
            conn,
            """SELECT v.id, v.plate, v.kind, st.name AS stop_name, st.seq AS stop_seq, st.lat, st.lng,
                      t.arrived_at, sh.route_id
               FROM vehicles v
               LEFT JOIN trips t ON t.id = (
                    SELECT t2.id FROM trips t2 JOIN shifts sh2 ON sh2.id=t2.shift_id
                    WHERE sh2.vehicle_id=v.id AND t2.day=? ORDER BY t2.arrived_at DESC LIMIT 1)
               LEFT JOIN shifts sh ON sh.id = t.shift_id
               LEFT JOIN stops st ON st.id = t.current_stop_id
               WHERE v.id=?""",
            (db.today_str(), ride["vehicle_id"]),
        )
    return {"ride": ride, "vehicle": vehicle}


@app.get("/api/ride/{ride_id}")
def api_ride(ride_id: int):
    conn = db.connect()
    try:
        return _ride_detail(conn, ride_id)
    finally:
        conn.close()


class AcceptIn(BaseModel):
    driver_id: int


def _transition(ride_id: int, new_status: str, driver_id: int | None = None, note: str = ""):
    conn = db.connect()
    try:
        ride = _one(conn, "SELECT * FROM ride_requests WHERE id=?", (ride_id,))
        if not ride:
            raise HTTPException(404, "叫车单不存在")
        if driver_id is not None:
            d = _one(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
            if not d:
                raise HTTPException(404, "司机不存在")
            conn.execute(
                "UPDATE ride_requests SET status=?, driver_id=?, vehicle_id=?, updated_at=? WHERE id=?",
                (new_status, driver_id, d["vehicle_id"], db.now_iso(), ride_id),
            )
        else:
            conn.execute(
                "UPDATE ride_requests SET status=?, updated_at=? WHERE id=?",
                (new_status, db.now_iso(), ride_id),
            )
        db.log_event(conn, new_status, f"叫车 #{ride_id} → {new_status} {note}".strip())
        conn.commit()
        return _ride_detail(conn, ride_id)
    finally:
        conn.close()


@app.post("/api/ride/{ride_id}/accept")
def api_accept(ride_id: int, body: AcceptIn):
    return _transition(ride_id, "accepted", body.driver_id, "接单")


@app.post("/api/ride/{ride_id}/board")
def api_board(ride_id: int):
    return _transition(ride_id, "boarded", note="已接到乘客")


@app.post("/api/ride/{ride_id}/done")
def api_done(ride_id: int):
    return _transition(ride_id, "done", note="送达")


@app.post("/api/ride/{ride_id}/cancel")
def api_cancel(ride_id: int):
    return _transition(ride_id, "cancelled", note="取消")


# ---------------------------------------------------------------- 页面

def _page(name: str):
    path = os.path.join(STATIC_DIR, name)
    if not os.path.exists(path):
        return JSONResponse({"error": "页面未找到"}, status_code=404)
    return FileResponse(path)


@app.get("/")
def index():
    return RedirectResponse("/dispatcher")


@app.get("/dispatcher")
def page_dispatcher():
    return _page("dispatcher.html")


@app.get("/driver")
def page_driver():
    return _page("driver.html")


@app.get("/rider")
def page_rider():
    return _page("rider.html")


@app.get("/health")
def health():
    return {"ok": True, "now": db.now_iso()}
