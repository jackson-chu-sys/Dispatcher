"""Dispatcher —— 班车/摆渡车调度后端（FastAPI + SQLite）。

角色入口：
  /dispatcher  调度端（地图/车辆/派单/班次/ETA）
  /driver      司机端（登录=手机号，班次、到站上报、接单）
  /rider       乘客端（选起终点、叫车、看车到哪，免登录）
  /admin       台账管理（车辆/司机/线路/站点/班次，地图画线路）
  /board       大屏看板（在线率/准点率/完成率）
  /track       历史轨迹回放

实时：/ws WebSocket 推送（2s），页面保留轮询兜底。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import string
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from . import notify

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")


def _load_dotenv() -> None:
    """轻量 .env 加载（无第三方依赖），已有环境变量不覆盖。"""
    p = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(p):
        return
    try:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        pass


_load_dotenv()

app = FastAPI(title="Dispatcher", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------- 地图（高德）
AMAP_JS_KEY = os.environ.get("AMAP_JS_KEY", "").strip()          # Web端(JS API) key
AMAP_SECURITY = os.environ.get("AMAP_SECURITY_CODE", "").strip()  # JS key 配套安全密钥
AMAP_WEB_KEY = os.environ.get("AMAP_WEB_KEY", "").strip()         # Web服务 key（逆地理编码，可选）

# ---------------------------------------------------------------- 登录
TOKEN_TTL_H = 12 * 3600


def _secret_path() -> str:
    return os.path.join(DATA_DIR, ".token_secret")


def _load_secret() -> bytes:
    os.makedirs(DATA_DIR, exist_ok=True)
    p = _secret_path()
    if os.path.exists(p):
        return open(p, "rb").read().strip()
    s = secrets.token_hex(32).encode()
    with open(p, "wb") as f:
        f.write(s)
    os.chmod(p, 0o600)
    return s


SECRET = _load_secret()


def _dispatcher_password() -> str:
    """调度员口令：环境变量优先，否则首启随机生成并落盘（0600）。"""
    env = os.environ.get("DISPATCHER_PASSWORD", "").strip()
    if env:
        return env
    p = os.path.join(DATA_DIR, ".dispatcher_pass")
    if os.path.exists(p):
        return open(p).read().strip()
    pw = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    with open(p, "w") as f:
        f.write(pw)
    os.chmod(p, 0o600)
    return pw


def _sign(payload: bytes) -> str:
    return hmac.new(SECRET, payload, hashlib.sha256).hexdigest()[:24]


def make_token(role: str, ident: int, name: str) -> str:
    body = json.dumps({"r": role, "i": ident, "n": name, "e": int(datetime.now().timestamp()) + TOKEN_TTL_H},
                      ensure_ascii=False).encode()
    b64 = base64.urlsafe_b64encode(body).decode()
    return f"{b64}.{_sign(b64.encode())}"


def parse_token(token: str) -> dict | None:
    try:
        b64, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(b64.encode())):
            return None
        data = json.loads(base64.urlsafe_b64decode(b64.encode()))
        if data.get("e", 0) < datetime.now().timestamp():
            return None
        return data
    except Exception:
        return None


async def current_user(request: Request) -> dict:
    tok = request.headers.get("x-token") or ""
    if not tok:
        auth = request.headers.get("authorization", "")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    user = parse_token(tok) if tok else None
    if not user:
        raise HTTPException(401, "未登录或登录已过期")
    return user


async def require_dispatcher(user: dict = Depends(current_user)) -> dict:
    if user["r"] != "dispatcher":
        raise HTTPException(403, "需要调度员权限")
    return user


async def require_driver(user: dict = Depends(current_user)) -> dict:
    if user["r"] not in ("driver", "dispatcher"):
        raise HTTPException(403, "需要司机权限")
    return user


class LoginIn(BaseModel):
    role: str = Field(pattern="^(driver|dispatcher)$")
    phone: str = ""
    password: str = ""


@app.post("/api/login")
def api_login(body: LoginIn):
    conn = db.connect()
    try:
        if body.role == "driver":
            phone = body.phone.strip()
            if not phone:
                raise HTTPException(400, "请输入手机号")
            d = db_row(conn, "SELECT * FROM drivers WHERE phone=? AND on_duty=1", (phone,))
            if not d:
                raise HTTPException(401, "手机号未登记或已停用")
            return {"ok": True, "token": make_token("driver", d["id"], d["name"]),
                    "user": {"role": "driver", "id": d["id"], "name": d["name"], "phone": phone,
                             "vehicle_id": d["vehicle_id"]}}
        pw = body.password.strip()
        if not pw or not hmac.compare_digest(pw, _dispatcher_password()):
            raise HTTPException(401, "口令错误")
        return {"ok": True, "token": make_token("dispatcher", 0, "调度员"),
                "user": {"role": "dispatcher", "id": 0, "name": "调度员"}}
    finally:
        conn.close()


@app.get("/api/me")
def api_me(user: dict = Depends(current_user)):
    return {"user": {"role": user["r"], "id": user["i"], "name": user["n"]}}


# ---------------------------------------------------------------- 工具

def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def db_row(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def _stops_by_route(conn) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for s in rows(conn, "SELECT * FROM stops ORDER BY route_id, seq"):
        out.setdefault(s["route_id"], []).append(s)
    return out


def _to_min(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return -1


def _eta_minutes(route_stops: list[dict], cur_stop_id: int | None, to_stop_id: int,
                 duration_min: int) -> int | None:
    """按站点序号推算到达终点还需几分钟（同线路才有意义）。"""
    if not route_stops or not cur_stop_id:
        return None
    ids = [s["id"] for s in route_stops]
    if cur_stop_id not in ids or to_stop_id not in ids:
        return None
    n = len(ids)
    ci, ti = ids.index(cur_stop_id), ids.index(to_stop_id)
    segs = (ti - ci) % n if n > 1 else 0
    if segs == 0:
        return 0
    per = max(1.0, (duration_min or 45) / max(1, n - 1 if n > 1 else 1))
    return max(1, round(segs * per))


def _vehicles_state(conn) -> list[dict]:
    """车辆当前位置取自今天最近一条 trip 的 current_stop（到站触发）。"""
    day = db.today_str()
    out = []
    for v in rows(conn, "SELECT * FROM vehicles ORDER BY id"):
        row = db_row(
            conn,
            """SELECT t.id AS trip_id, t.current_stop_id, t.arrived_at, t.started_at, t.status AS trip_status,
                      sh.id AS shift_id, sh.route_id, sh.depart_time, sh.driver_id, sh.duration_min,
                      r.name AS route_name, r.color,
                      st.name AS stop_name, st.seq AS stop_seq, st.lat, st.lng
               FROM shifts sh
               JOIN trips t ON t.shift_id = sh.id AND t.day = ?
               JOIN routes r ON r.id = sh.route_id
               LEFT JOIN stops st ON st.id = t.current_stop_id
               WHERE sh.vehicle_id = ?
               ORDER BY t.arrived_at DESC, sh.depart_time DESC LIMIT 1""",
            (day, v["id"]),
        )
        driver = db_row(conn, "SELECT name, phone FROM drivers WHERE vehicle_id=?", (v["id"],))
        rec = {
            **v,
            "driver": driver["name"] if driver else None,
            "route_id": row["route_id"] if row else None,
            "route_name": row["route_name"] if row else None,
            "color": row["color"] if row else "#888",
            "trip_id": row["trip_id"] if row else None,
            "shift_id": row["shift_id"] if row else None,
            "depart_time": row["depart_time"] if row else None,
            "duration_min": row["duration_min"] if row else 45,
            "stop_name": row["stop_name"] if row else None,
            "stop_seq": row["stop_seq"] if row else None,
            "stop_id": row["current_stop_id"] if row else None,
            "lat": row["lat"] if row else None,
            "lng": row["lng"] if row else None,
            "arrived_at": row["arrived_at"] if row else None,
        }
        out.append(rec)
    return out


def build_state(conn, with_events: int = 12) -> dict:
    day = db.today_str()
    routes = rows(conn, "SELECT * FROM routes ORDER BY id")
    stops = _stops_by_route(conn)
    for r in routes:
        r["stops"] = stops.get(r["id"], [])
    rides = rows(
        conn,
        """SELECT rr.*, fs.name AS from_name, ts.name AS to_name, v.plate, d.name AS driver_name,
                  d.phone AS driver_phone
           FROM ride_requests rr
           JOIN stops fs ON fs.id = rr.from_stop_id
           JOIN stops ts ON ts.id = rr.to_stop_id
           LEFT JOIN vehicles v ON v.id = rr.vehicle_id
           LEFT JOIN drivers d ON d.id = rr.driver_id
           WHERE rr.status IN ('waiting','accepted','boarded')
           ORDER BY rr.created_at""",
    )
    vehicles = _vehicles_state(conn)
    # ETA：叫车单终点相对接单车当前位置
    vmap = {v["id"]: v for v in vehicles}
    for r in rides:
        r["eta_min"] = None
        v = vmap.get(r["vehicle_id"]) if r["vehicle_id"] else None
        if v and v["route_id"]:
            r["eta_min"] = _eta_minutes(stops.get(v["route_id"], []), v["stop_id"],
                                        r["to_stop_id"], v["duration_min"])
        waited = (datetime.fromisoformat(db.now_iso()) - datetime.fromisoformat(r["created_at"])).total_seconds()
        r["waited_sec"] = int(max(0, waited))
    shifts = rows(
        conn,
        """SELECT sh.*, r.name AS route_name, r.color, v.plate, d.name AS driver_name,
                  t.id AS trip_id, t.status AS trip_status, t.current_stop_id, t.arrived_at, t.started_at,
                  st.name AS stop_name, st.seq AS stop_seq
           FROM shifts sh
           JOIN routes r ON r.id = sh.route_id
           JOIN vehicles v ON v.id = sh.vehicle_id
           JOIN drivers d ON d.id = sh.driver_id
           JOIN trips t ON t.shift_id = sh.id AND t.day = ?
           LEFT JOIN stops st ON st.id = t.current_stop_id
           ORDER BY sh.depart_time""",
        (day,),
    )
    for s in shifts:
        s["delay_min"] = None
        if s["started_at"] and s["depart_time"]:
            s["delay_min"] = _to_min(s["started_at"][11:16]) - _to_min(s["depart_time"])
    events = rows(conn, "SELECT * FROM events ORDER BY id DESC LIMIT ?", (with_events,))
    stats = {
        "vehicles_total": len(vehicles),
        "vehicles_online": sum(1 for v in vehicles if v["arrived_at"]),
        "rides_waiting": sum(1 for r in rides if r["status"] == "waiting"),
        "rides_active": len(rides),
        "shifts_total": len(shifts),
        "shifts_running": sum(1 for s in shifts if s["trip_status"] == "running"),
        "shifts_done": sum(1 for s in shifts if s["trip_status"] == "done"),
    }
    return {
        "now": db.now_iso(),
        "day": day,
        "map": {"provider": "amap" if AMAP_JS_KEY else "schematic",
                "js_key": AMAP_JS_KEY, "security_code": AMAP_SECURITY},
        "stats": stats,
        "vehicles": vehicles,
        "routes": routes,
        "rides": rides,
        "shifts": shifts,
        "events": events,
    }


@app.get("/api/state")
def api_state():
    conn = db.connect()
    try:
        return build_state(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------- WebSocket 推送

class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.dirty = False

    async def add(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def drop(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    def bump(self) -> None:
        """状态变更（写操作后调用），下一 tick 立即广播。"""
        self.dirty = True


hub = Hub()


async def _broadcaster() -> None:
    last = ""
    while True:
        await asyncio.sleep(2)
        if not hub.clients:
            hub.dirty = False
            continue
        try:
            conn = db.connect()
            try:
                state = build_state(conn)
            finally:
                conn.close()
            payload = json.dumps(state, ensure_ascii=False, default=str)
            if not hub.dirty and payload == last:
                continue
            last, hub.dirty = payload, False
            dead = []
            for ws in list(hub.clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                hub.drop(ws)
        except Exception as e:                                    # pragma: no cover
            print("WS broadcast error:", e)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    loop = asyncio.get_event_loop()
    loop.create_task(_broadcaster())
    loop.create_task(notify.watchdog_loop(30))
    if notify.is_configured():
        print("[notify] 企业微信群机器人通知已启用")
    else:
        print("[notify] 未配置 WECOM_WEBHOOK_URL，通知功能待命")
    if AMAP_JS_KEY:
        print("[map] 高德 JS key 已配置")
    else:
        print("[map] 未配置 AMAP_JS_KEY → 前端走示意图")


@app.websocket("/ws")
async def ws_state(ws: WebSocket):
    await hub.add(ws)
    try:
        while True:
            await ws.receive_text()          # 客户端心跳/指令，忽略内容
    except WebSocketDisconnect:
        pass
    finally:
        hub.drop(ws)


# ---------------------------------------------------------------- 司机端

@app.get("/api/driver/{driver_id}")
def api_driver(driver_id: int, user: dict = Depends(current_user)):
    if user["r"] == "driver" and user["i"] != driver_id:
        raise HTTPException(403, "只能查看自己的班次")
    conn = db.connect()
    try:
        d = db_row(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        v = db_row(conn, "SELECT * FROM vehicles WHERE id=?", (d["vehicle_id"],))
        day = db.today_str()
        shifts = rows(
            conn,
            """SELECT sh.*, r.name AS route_name, r.color, t.id AS trip_id, t.status AS trip_status,
                      t.current_stop_id, t.started_at, st.name AS stop_name, st.seq AS stop_seq
               FROM shifts sh
               JOIN routes r ON r.id = sh.route_id
               JOIN trips t ON t.shift_id = sh.id AND t.day = ?
               LEFT JOIN stops st ON st.id = t.current_stop_id
               WHERE sh.driver_id = ?
               ORDER BY sh.depart_time""",
            (day, driver_id),
        )
        stops_map = _stops_by_route(conn)
        for s in shifts:
            s["shift_id"] = s["id"]
            s["stops"] = stops_map.get(s["route_id"], [])
        rides = rows(
            conn,
            """SELECT rr.*, fs.name AS from_name, ts.name AS to_name,
                       fs.seq AS from_seq, ts.seq AS to_seq, fs.route_id AS from_route
               FROM ride_requests rr
               JOIN stops fs ON fs.id = rr.from_stop_id
               JOIN stops ts ON ts.id = rr.to_stop_id
               WHERE rr.status IN ('waiting','accepted','boarded')
                 AND (rr.driver_id IS NULL OR rr.driver_id = ?)
               ORDER BY rr.created_at""",
            (driver_id,),
        )
        vstate = None
        if v:
            for rec in _vehicles_state(conn):
                if rec["id"] == v["id"]:
                    vstate = rec
                    break
        for r in rides:
            r["eta_min"] = None
            if vstate and vstate["route_id"]:
                r["eta_min"] = _eta_minutes(stops_map.get(vstate["route_id"], []),
                                            vstate["stop_id"], r["to_stop_id"], vstate["duration_min"])
        return {"driver": d, "vehicle": v, "vehicle_state": vstate, "day": day,
                "shifts": shifts, "rides": rides}
    finally:
        conn.close()


class ArriveIn(BaseModel):
    stop_id: int
    shift_id: int | None = None
    done_after: bool = False     # 末站到站即结束班次


def _current_trip(conn, driver_id: int, shift_id: int | None = None):
    """司机的当前班次行程：显式指定 > 正在跑的 > 今天最早未完成的。"""
    day = db.today_str()
    if shift_id:
        return db_row(
            conn,
            """SELECT t.*, sh.route_id, sh.duration_min FROM trips t JOIN shifts sh ON sh.id=t.shift_id
               WHERE t.shift_id=? AND t.day=?""",
            (shift_id, day),
        )
    return db_row(
        conn,
        """SELECT t.*, sh.route_id, sh.duration_min FROM trips t JOIN shifts sh ON sh.id=t.shift_id
           WHERE sh.driver_id=? AND t.day=? AND t.status<>'done'
           ORDER BY CASE WHEN t.status='running' THEN 0 ELSE 1 END, sh.depart_time
           LIMIT 1""",
        (driver_id, day),
    )


@app.get("/api/drivers")
def api_drivers(user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        return rows(
            conn,
            """SELECT d.id, d.name, d.phone, d.vehicle_id, d.on_duty, v.plate, v.kind, v.seats
               FROM drivers d LEFT JOIN vehicles v ON v.id = d.vehicle_id ORDER BY d.id""",
        )
    finally:
        conn.close()


@app.post("/api/driver/{driver_id}/arrive")
def api_arrive(driver_id: int, body: ArriveIn, user: dict = Depends(require_driver)):
    """到站上报：更新行程位置 + 写 arrivals 明细（供轨迹回放）。"""
    if user["r"] == "driver" and user["i"] != driver_id:
        raise HTTPException(403, "只能上报自己的到站")
    conn = db.connect()
    try:
        d = db_row(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        trip = _current_trip(conn, driver_id, body.shift_id)
        if not trip:
            raise HTTPException(404, "今日没有可用班次")
        stop = db_row(conn, "SELECT * FROM stops WHERE id=?", (body.stop_id,))
        if not stop:
            raise HTTPException(404, "站点不存在")
        if stop["route_id"] != trip["route_id"]:
            raise HTTPException(400, "该站点不属于当前班次线路")
        now = db.now_iso()
        conn.execute(
            "UPDATE trips SET current_stop_id=?, arrived_at=?, status='running', updated_at=? WHERE id=?",
            (body.stop_id, now, now, trip["id"]),
        )
        conn.execute("INSERT INTO arrivals(trip_id, stop_id, ts) VALUES (?,?,?)", (trip["id"], body.stop_id, now))
        conn.execute("UPDATE vehicles SET status='running' WHERE id=?", (d["vehicle_id"],))
        db.log_event(conn, "arrive", f"{d['name']} 到达 {stop['name']}")
        # 司机勾选"末站完成班次"时收尾
        finished = False
        if body.done_after:
            conn.execute("UPDATE trips SET status='done', updated_at=? WHERE id=?", (now, trip["id"]))
            conn.execute("UPDATE vehicles SET status='idle' WHERE id=?", (d["vehicle_id"],))
            db.log_event(conn, "trip_done", f"{d['name']} 完成班次 #{trip['shift_id']}")
            finished = True
        conn.commit()
        hub.bump()
        return {"ok": True, "trip_id": trip["id"], "stop": stop["name"], "at": now, "finished": finished}
    finally:
        conn.close()


class StartIn(BaseModel):
    shift_id: int | None = None


@app.post("/api/driver/{driver_id}/start")
def api_start(driver_id: int, body: StartIn | None = None, user: dict = Depends(require_driver)):
    if user["r"] == "driver" and user["i"] != driver_id:
        raise HTTPException(403, "只能操作自己的班次")
    conn = db.connect()
    try:
        d = db_row(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        trip = _current_trip(conn, driver_id, body.shift_id if body else None)
        if not trip:
            raise HTTPException(404, "今日没有可用班次")
        now = db.now_iso()
        conn.execute(
            "UPDATE trips SET status='running', started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?",
            (now, now, trip["id"]),
        )
        conn.execute("UPDATE vehicles SET status='running' WHERE id=?", (d["vehicle_id"],))
        db.log_event(conn, "start", f"{d['name']} 发车（班次 #{trip['shift_id']}）")
        conn.commit()
        hub.bump()
        return {"ok": True, "trip_id": trip["id"], "started_at": now}
    finally:
        conn.close()


@app.post("/api/driver/{driver_id}/finish")
def api_finish(driver_id: int, body: StartIn | None = None, user: dict = Depends(require_driver)):
    """手动结束当前班次。"""
    if user["r"] == "driver" and user["i"] != driver_id:
        raise HTTPException(403, "只能操作自己的班次")
    conn = db.connect()
    try:
        d = db_row(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
        if not d:
            raise HTTPException(404, "司机不存在")
        trip = _current_trip(conn, driver_id, body.shift_id if body else None)
        if not trip:
            raise HTTPException(404, "今日没有可用班次")
        now = db.now_iso()
        conn.execute("UPDATE trips SET status='done', updated_at=? WHERE id=?", (now, trip["id"]))
        conn.execute("UPDATE vehicles SET status='idle' WHERE id=?", (d["vehicle_id"],))
        db.log_event(conn, "trip_done", f"{d['name']} 完成班次 #{trip['shift_id']}")
        conn.commit()
        hub.bump()
        return {"ok": True, "trip_id": trip["id"]}
    finally:
        conn.close()


# ---------------------------------------------------------------- 乘客端（免登录）

@app.get("/api/rider/options")
def api_rider_options():
    conn = db.connect()
    try:
        routes = rows(conn, "SELECT * FROM routes ORDER BY id")
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
            if not db_row(conn, "SELECT id FROM stops WHERE id=?", (sid,)):
                raise HTTPException(404, "站点不存在")
        now = db.now_iso()
        cur = conn.execute(
            """INSERT INTO ride_requests(rider, from_stop_id, to_stop_id, people, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (body.rider, body.from_stop_id, body.to_stop_id, max(1, body.people), now, now),
        )
        db.log_event(conn, "ride_new", f"{body.rider} 叫车 #{cur.lastrowid}")
        conn.commit()
        hub.bump()
        ride_id = cur.lastrowid
        names = {row["id"]: row["name"] for row in
                 rows(conn, "SELECT id, name FROM stops WHERE id IN (?,?)",
                      (body.from_stop_id, body.to_stop_id))}
    finally:
        conn.close()
    notify.notify_new_ride(ride_id, body.rider, max(1, body.people),
                           names.get(body.from_stop_id, "?"), names.get(body.to_stop_id, "?"))
    return {"ok": True, "ride_id": ride_id}


def _ride_detail(conn, ride_id: int) -> dict:
    ride = db_row(
        conn,
        """SELECT rr.*, fs.name AS from_name, ts.name AS to_name, fs.lat AS from_lat, fs.lng AS from_lng,
                  fs.route_id AS from_route, ts.lat AS to_lat, ts.lng AS to_lng,
                  v.plate, v.kind, d.name AS driver_name, d.phone AS driver_phone
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
    eta = None
    if ride["vehicle_id"]:
        vehicle = db_row(
            conn,
            """SELECT v.id, v.plate, v.kind, st.id AS stop_id, st.name AS stop_name, st.seq AS stop_seq,
                      st.lat, st.lng, t.arrived_at, sh.route_id, sh.duration_min
               FROM vehicles v
               LEFT JOIN trips t ON t.id = (
                    SELECT t2.id FROM trips t2 JOIN shifts sh2 ON sh2.id=t2.shift_id
                    WHERE sh2.vehicle_id=v.id AND t2.day=? ORDER BY t2.arrived_at DESC LIMIT 1)
               LEFT JOIN shifts sh ON sh.id = t.shift_id
               LEFT JOIN stops st ON st.id = t.current_stop_id
               WHERE v.id=?""",
            (db.today_str(), ride["vehicle_id"]),
        )
        if vehicle and vehicle["route_id"]:
            rstops = rows(conn, "SELECT * FROM stops WHERE route_id=? ORDER BY seq", (vehicle["route_id"],))
            eta = _eta_minutes(rstops, vehicle["stop_id"], ride["to_stop_id"], vehicle["duration_min"])
    ride["eta_min"] = eta
    if ride["created_at"]:
        ride["waited_sec"] = int(max(0, (datetime.fromisoformat(db.now_iso())
                                        - datetime.fromisoformat(ride["created_at"])).total_seconds()))
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


def _transition(ride_id: int, new_status: str, driver_id: int | None = None, note: str = "",
                actor: str = ""):
    conn = db.connect()
    try:
        ride = db_row(conn, "SELECT * FROM ride_requests WHERE id=?", (ride_id,))
        if not ride:
            raise HTTPException(404, "叫车单不存在")
        if driver_id is not None:
            d = db_row(conn, "SELECT * FROM drivers WHERE id=?", (driver_id,))
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
        suffix = f"（{actor}）" if actor else ""
        db.log_event(conn, new_status, f"叫车 #{ride_id} → {new_status} {note}{suffix}".strip())
        conn.commit()
        hub.bump()
        return _ride_detail(conn, ride_id)
    finally:
        conn.close()


@app.post("/api/ride/{ride_id}/accept")
def api_accept(ride_id: int, body: AcceptIn, user: dict = Depends(require_driver)):
    if user["r"] == "driver" and user["i"] != body.driver_id:
        raise HTTPException(403, "只能以自己身份接单")
    return _transition(ride_id, "accepted", body.driver_id, "接单", actor=user["n"])


@app.post("/api/ride/{ride_id}/board")
def api_board(ride_id: int, user: dict = Depends(current_user)):
    return _transition(ride_id, "boarded", note="已接到乘客", actor=user["n"])


@app.post("/api/ride/{ride_id}/done")
def api_done(ride_id: int, user: dict = Depends(current_user)):
    return _transition(ride_id, "done", note="送达", actor=user["n"])


@app.post("/api/ride/{ride_id}/cancel")
def api_cancel(ride_id: int):
    """乘客可自助取消（免登录），调度/司机也可取消。"""
    return _transition(ride_id, "cancelled", note="取消")


# ---------------------------------------------------------------- 台账 CRUD

class VehicleIn(BaseModel):
    plate: str = Field(min_length=1, max_length=20)
    kind: str = Field(default="摆渡车(电动)", max_length=20)
    seats: int = Field(default=8, ge=0, le=200)
    status: str = Field(default="idle", pattern="^(idle|running|off)$")


class DriverIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    phone: str = Field(default="", max_length=20)
    vehicle_id: int | None = None
    on_duty: int = Field(default=1, ge=0, le=1)


class RouteIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    direction: str = Field(default="loop", pattern="^(loop|oneway)$")
    color: str = Field(default="#2f6fed", max_length=16)


class StopIn(BaseModel):
    route_id: int
    name: str = Field(min_length=1, max_length=30)
    lat: float
    lng: float
    seq: int | None = None          # 缺省排到末尾


class StopsBatch(BaseModel):
    route_id: int
    stops: list[StopIn]             # 地图画线路时一次提交全部站点


class ShiftIn(BaseModel):
    route_id: int
    vehicle_id: int
    driver_id: int
    depart_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration_min: int = Field(default=45, ge=5, le=480)


def _check_shift_conflict(conn, s: ShiftIn, exclude_id: int | None = None) -> None:
    """同车 / 同司机时间区间重叠 → 409（验收标准第 4 条）。"""
    start = _to_min(s.depart_time)
    if start < 0:
        raise HTTPException(400, "发车时间格式应为 HH:MM")
    end = start + s.duration_min
    q = """SELECT sh.id, sh.depart_time, sh.duration_min, r.name AS route_name,
                  v.plate, d.name AS driver_name
           FROM shifts sh JOIN routes r ON r.id=sh.route_id
           JOIN vehicles v ON v.id=sh.vehicle_id JOIN drivers d ON d.id=sh.driver_id
           WHERE (sh.vehicle_id=? OR sh.driver_id=?)"""
    args: list = [s.vehicle_id, s.driver_id]
    if exclude_id:
        q += " AND sh.id<>?"
        args.append(exclude_id)
    for o in rows(conn, q, tuple(args)):
        os_, oe = _to_min(o["depart_time"]), _to_min(o["depart_time"]) + (o["duration_min"] or 45)
        if os_ < end and start < oe:
            raise HTTPException(409, (
                f"排班冲突：{o['depart_time']}–{('%02d:%02d' % divmod(oe, 60))} "
                f"{o['route_name']}（车 {o['plate']} / 司机 {o['driver_name']}）与本班重叠"))


@app.get("/api/vehicles")
def api_vehicles(user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        return rows(conn, "SELECT * FROM vehicles ORDER BY id")
    finally:
        conn.close()


@app.post("/api/vehicles")
def api_vehicle_create(body: VehicleIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if db_row(conn, "SELECT id FROM vehicles WHERE plate=?", (body.plate,)):
            raise HTTPException(409, "车牌已存在")
        cur = conn.execute("INSERT INTO vehicles(plate, kind, seats, status) VALUES (?,?,?,?)",
                           (body.plate, body.kind, body.seats, body.status))
        db.log_event(conn, "crud", f"{user['n']} 新增车辆 {body.plate}")
        conn.commit(); hub.bump()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/vehicles/{vid}")
def api_vehicle_update(vid: int, body: VehicleIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM vehicles WHERE id=?", (vid,)):
            raise HTTPException(404, "车辆不存在")
        dup = db_row(conn, "SELECT id FROM vehicles WHERE plate=? AND id<>?", (body.plate, vid))
        if dup:
            raise HTTPException(409, "车牌已存在")
        conn.execute("UPDATE vehicles SET plate=?, kind=?, seats=?, status=? WHERE id=?",
                     (body.plate, body.kind, body.seats, body.status, vid))
        db.log_event(conn, "crud", f"{user['n']} 修改车辆 {body.plate}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/vehicles/{vid}")
def api_vehicle_delete(vid: int, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        v = db_row(conn, "SELECT * FROM vehicles WHERE id=?", (vid,))
        if not v:
            raise HTTPException(404, "车辆不存在")
        if db_row(conn, "SELECT id FROM shifts WHERE vehicle_id=?", (vid,)):
            raise HTTPException(409, "该车辆已排班，先删除相关班次")
        conn.execute("UPDATE drivers SET vehicle_id=NULL WHERE vehicle_id=?", (vid,))
        conn.execute("DELETE FROM vehicles WHERE id=?", (vid,))
        db.log_event(conn, "crud", f"{user['n']} 删除车辆 {v['plate']}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/routes")
def api_routes(user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        out = rows(conn, "SELECT * FROM routes ORDER BY id")
        stops = _stops_by_route(conn)
        for r in out:
            r["stops"] = stops.get(r["id"], [])
        return out
    finally:
        conn.close()


@app.post("/api/routes")
def api_route_create(body: RouteIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO routes(name, direction, color) VALUES (?,?,?)",
                           (body.name, body.direction, body.color))
        db.log_event(conn, "crud", f"{user['n']} 新增线路 {body.name}")
        conn.commit(); hub.bump()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/routes/{rid}")
def api_route_update(rid: int, body: RouteIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM routes WHERE id=?", (rid,)):
            raise HTTPException(404, "线路不存在")
        conn.execute("UPDATE routes SET name=?, direction=?, color=? WHERE id=?",
                     (body.name, body.direction, body.color, rid))
        db.log_event(conn, "crud", f"{user['n']} 修改线路 {body.name}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/routes/{rid}")
def api_route_delete(rid: int, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        r = db_row(conn, "SELECT * FROM routes WHERE id=?", (rid,))
        if not r:
            raise HTTPException(404, "线路不存在")
        if db_row(conn, "SELECT id FROM shifts WHERE route_id=?", (rid,)):
            raise HTTPException(409, "该线路已排班，先删除相关班次")
        if db_row(conn, "SELECT id FROM ride_requests WHERE from_stop_id IN (SELECT id FROM stops WHERE route_id=?) "
                        "AND status IN ('waiting','accepted','boarded')", (rid,)):
            raise HTTPException(409, "该线路有进行中的叫车单")
        conn.execute("DELETE FROM stops WHERE route_id=?", (rid,))
        conn.execute("DELETE FROM routes WHERE id=?", (rid,))
        db.log_event(conn, "crud", f"{user['n']} 删除线路 {r['name']}（含站点）")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/drivers")
def api_driver_create(body: DriverIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if body.phone and db_row(conn, "SELECT id FROM drivers WHERE phone=?", (body.phone,)):
            raise HTTPException(409, "手机号已登记")
        cur = conn.execute("INSERT INTO drivers(name, phone, vehicle_id, on_duty) VALUES (?,?,?,?)",
                           (body.name, body.phone, body.vehicle_id, body.on_duty))
        db.log_event(conn, "crud", f"{user['n']} 新增司机 {body.name}")
        conn.commit(); hub.bump()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/drivers/{did}")
def api_driver_update(did: int, body: DriverIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM drivers WHERE id=?", (did,)):
            raise HTTPException(404, "司机不存在")
        if body.phone and db_row(conn, "SELECT id FROM drivers WHERE phone=? AND id<>?", (body.phone, did)):
            raise HTTPException(409, "手机号已登记")
        conn.execute("UPDATE drivers SET name=?, phone=?, vehicle_id=?, on_duty=? WHERE id=?",
                     (body.name, body.phone, body.vehicle_id, body.on_duty, did))
        db.log_event(conn, "crud", f"{user['n']} 修改司机 {body.name}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/drivers/{did}")
def api_driver_delete(did: int, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        d = db_row(conn, "SELECT * FROM drivers WHERE id=?", (did,))
        if not d:
            raise HTTPException(404, "司机不存在")
        if db_row(conn, "SELECT id FROM shifts WHERE driver_id=?", (did,)):
            raise HTTPException(409, "该司机已排班，先删除相关班次")
        conn.execute("DELETE FROM drivers WHERE id=?", (did,))
        db.log_event(conn, "crud", f"{user['n']} 删除司机 {d['name']}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/stops")
def api_stop_create(body: StopIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM routes WHERE id=?", (body.route_id,)):
            raise HTTPException(404, "线路不存在")
        seq = body.seq
        if seq is None:
            m = db_row(conn, "SELECT MAX(seq) AS m FROM stops WHERE route_id=?", (body.route_id,))
            seq = (m["m"] or 0) + 1
        cur = conn.execute("INSERT INTO stops(route_id, seq, name, lat, lng) VALUES (?,?,?,?,?)",
                           (body.route_id, seq, body.name, body.lat, body.lng))
        db.log_event(conn, "crud", f"{user['n']} 新增站点 {body.name}")
        conn.commit(); hub.bump()
        return {"ok": True, "id": cur.lastrowid, "seq": seq}
    finally:
        conn.close()


@app.post("/api/stops/batch")
def api_stops_batch(body: StopsBatch, user: dict = Depends(require_dispatcher)):
    """地图画线路：一次写入整条线路的站点（按提交顺序编号）。"""
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM routes WHERE id=?", (body.route_id,)):
            raise HTTPException(404, "线路不存在")
        base = db_row(conn, "SELECT MAX(seq) AS m FROM stops WHERE route_id=?", (body.route_id,))["m"] or 0
        ids = []
        for i, s in enumerate(body.stops, 1):
            cur = conn.execute("INSERT INTO stops(route_id, seq, name, lat, lng) VALUES (?,?,?,?,?)",
                               (body.route_id, base + i, s.name, s.lat, s.lng))
            ids.append(cur.lastrowid)
        db.log_event(conn, "crud", f"{user['n']} 批量生成 {len(ids)} 个站点（线路 #{body.route_id}）")
        conn.commit(); hub.bump()
        return {"ok": True, "ids": ids}
    finally:
        conn.close()


@app.put("/api/stops/{sid}")
def api_stop_update(sid: int, body: StopIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM stops WHERE id=?", (sid,)):
            raise HTTPException(404, "站点不存在")
        seq = body.seq
        if seq is None:
            seq = db_row(conn, "SELECT seq FROM stops WHERE id=?", (sid,))["seq"]
        conn.execute("UPDATE stops SET route_id=?, seq=?, name=?, lat=?, lng=? WHERE id=?",
                     (body.route_id, seq, body.name, body.lat, body.lng, sid))
        db.log_event(conn, "crud", f"{user['n']} 修改站点 {body.name}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/stops/{sid}")
def api_stop_delete(sid: int, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        s = db_row(conn, "SELECT * FROM stops WHERE id=?", (sid,))
        if not s:
            raise HTTPException(404, "站点不存在")
        if db_row(conn, "SELECT id FROM ride_requests WHERE (from_stop_id=? OR to_stop_id=?) "
                        "AND status IN ('waiting','accepted','boarded')", (sid, sid)):
            raise HTTPException(409, "该站点有进行中的叫车单")
        conn.execute("DELETE FROM stops WHERE id=?", (sid,))
        conn.execute("""UPDATE stops SET seq=seq-1 WHERE route_id=? AND seq>?""", (s["route_id"], s["seq"]))
        db.log_event(conn, "crud", f"{user['n']} 删除站点 {s['name']}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- 班次（含冲突检测）

@app.get("/api/shifts")
def api_shifts(user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        return rows(conn, """SELECT sh.*, r.name AS route_name, r.color, v.plate, d.name AS driver_name
                             FROM shifts sh JOIN routes r ON r.id=sh.route_id
                             JOIN vehicles v ON v.id=sh.vehicle_id JOIN drivers d ON d.id=sh.driver_id
                             ORDER BY sh.depart_time, sh.id""")
    finally:
        conn.close()


@app.post("/api/shifts")
def api_shift_create(body: ShiftIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        for tbl, key in (("routes", "route_id"), ("vehicles", "vehicle_id"), ("drivers", "driver_id")):
            if not db_row(conn, f"SELECT id FROM {tbl} WHERE id=?", (getattr(body, key),)):
                raise HTTPException(404, f"{tbl} 不存在")
        if not db_row(conn, "SELECT id FROM stops WHERE route_id=?", (body.route_id,)):
            raise HTTPException(400, "该线路还没有站点，先在地图上画线路")
        _check_shift_conflict(conn, body)
        cur = conn.execute(
            "INSERT INTO shifts(route_id, vehicle_id, driver_id, depart_time, duration_min) VALUES (?,?,?,?,?)",
            (body.route_id, body.vehicle_id, body.driver_id, body.depart_time, body.duration_min))
        db.log_event(conn, "crud", f"{user['n']} 排班 #{cur.lastrowid} {body.depart_time}")
        conn.commit()
        db.init_db(seed=False)          # 为今天补 trip
        hub.bump()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


@app.put("/api/shifts/{sid}")
def api_shift_update(sid: int, body: ShiftIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM shifts WHERE id=?", (sid,)):
            raise HTTPException(404, "班次不存在")
        _check_shift_conflict(conn, body, exclude_id=sid)
        conn.execute("UPDATE shifts SET route_id=?, vehicle_id=?, driver_id=?, depart_time=?, duration_min=? WHERE id=?",
                     (body.route_id, body.vehicle_id, body.driver_id, body.depart_time, body.duration_min, sid))
        db.log_event(conn, "crud", f"{user['n']} 改班次 #{sid} → {body.depart_time}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/shifts/{sid}")
def api_shift_delete(sid: int, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        if not db_row(conn, "SELECT id FROM shifts WHERE id=?", (sid,)):
            raise HTTPException(404, "班次不存在")
        conn.execute("DELETE FROM trips WHERE shift_id=?", (sid,))
        conn.execute("DELETE FROM shifts WHERE id=?", (sid,))
        db.log_event(conn, "crud", f"{user['n']} 删除班次 #{sid}")
        conn.commit(); hub.bump()
        return {"ok": True}
    finally:
        conn.close()


# ---------------------------------------------------------------- 看板 & 轨迹

@app.get("/api/dashboard")
def api_dashboard(user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        day = db.today_str()
        vehicles = _vehicles_state(conn)
        trips = rows(conn, """SELECT t.*, sh.depart_time, sh.duration_min FROM trips t
                              JOIN shifts sh ON sh.id=t.shift_id WHERE t.day=?""", (day,))
        rides = rows(conn, "SELECT * FROM ride_requests WHERE substr(created_at,1,10)=?", (day,))
        on_time = late = 0
        for t in trips:
            if not t["started_at"] or not t["depart_time"]:
                continue
            delay = _to_min(t["started_at"][11:16]) - _to_min(t["depart_time"])
            if delay <= 5:
                on_time += 1
            else:
                late += 1
        started = on_time + late
        done_rides = [r for r in rides if r["status"] == "done"]
        cancelled = [r for r in rides if r["status"] == "cancelled"]
        arrivals_today = db_row(conn, """SELECT COUNT(*) AS c FROM arrivals a JOIN trips t ON t.id=a.trip_id
                                         WHERE t.day=?""", (day,))["c"]
        total = len(vehicles)
        online = sum(1 for v in vehicles if v["arrived_at"])
        return {
            "day": day,
            "now": db.now_iso(),
            "vehicles": {"total": total, "online": online,
                         "online_rate": round(online / total * 100) if total else 0},
            "shifts": {"total": len(trips),
                       "done": sum(1 for t in trips if t["status"] == "done"),
                       "running": sum(1 for t in trips if t["status"] == "running"),
                       "waiting": sum(1 for t in trips if t["status"] == "waiting"),
                       "completion_rate": round(sum(1 for t in trips if t["status"] == "done") / len(trips) * 100)
                       if trips else 0},
            "punctuality": {"started": started, "on_time": on_time, "late": late,
                            "rate": round(on_time / started * 100) if started else 0},
            "rides": {"total": len(rides), "done": len(done_rides), "cancelled": len(cancelled),
                      "waiting": sum(1 for r in rides if r["status"] == "waiting"),
                      "active": sum(1 for r in rides if r["status"] in ("waiting", "accepted", "boarded"))},
            "arrivals_today": arrivals_today,
            "fleet": vehicles,
        }
    finally:
        conn.close()


@app.get("/api/trips/today")
def api_trips_today(user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        out = rows(conn, """SELECT t.id, t.shift_id, t.day, t.status, t.started_at, t.arrived_at,
                                    t.current_stop_id, sh.depart_time, sh.duration_min,
                                    r.name AS route_name, r.color, v.plate, d.name AS driver_name,
                                    st.name AS stop_name
                             FROM trips t JOIN shifts sh ON sh.id=t.shift_id
                             JOIN routes r ON r.id=sh.route_id
                             JOIN vehicles v ON v.id=sh.vehicle_id
                             JOIN drivers d ON d.id=sh.driver_id
                             LEFT JOIN stops st ON st.id=t.current_stop_id
                             WHERE t.day=? ORDER BY sh.depart_time""", (db.today_str(),))
        for t in out:
            t["delay_min"] = None
            if t["started_at"] and t["depart_time"]:
                t["delay_min"] = _to_min(t["started_at"][11:16]) - _to_min(t["depart_time"])
        return out
    finally:
        conn.close()


@app.get("/api/trip/{trip_id}/track")
def api_trip_track(trip_id: int, user: dict = Depends(current_user)):
    """位置明细：该 trip 的到站序列（回放用）。"""
    conn = db.connect()
    try:
        trip = db_row(conn, """SELECT t.*, sh.depart_time, sh.route_id, r.name AS route_name, r.color,
                                      v.plate, d.name AS driver_name
                               FROM trips t JOIN shifts sh ON sh.id=t.shift_id
                               JOIN routes r ON r.id=sh.route_id
                               JOIN vehicles v ON v.id=sh.vehicle_id
                               JOIN drivers d ON d.id=sh.driver_id WHERE t.id=?""", (trip_id,))
        if not trip:
            raise HTTPException(404, "行程不存在")
        pts = rows(conn, """SELECT a.id, a.ts, s.id AS stop_id, s.name, s.seq, s.lat, s.lng
                            FROM arrivals a JOIN stops s ON s.id=a.stop_id
                            WHERE a.trip_id=? ORDER BY a.id""", (trip_id,))
        route_stops = rows(conn, "SELECT * FROM stops WHERE route_id=? ORDER BY seq", (trip["route_id"],))
        return {"trip": trip, "points": pts, "route_stops": route_stops}
    finally:
        conn.close()


@app.get("/api/events")
def api_events(limit: int = 200, user: dict = Depends(current_user)):
    conn = db.connect()
    try:
        return rows(conn, "SELECT * FROM events ORDER BY id DESC LIMIT ?", (min(1000, max(1, limit)),))
    finally:
        conn.close()


# ---------------------------------------------------------------- 页面

def _page(name: str):
    path = os.path.join(STATIC_DIR, name)
    if not os.path.exists(path):
        return JSONResponse({"error": "页面未找到"}, status_code=404)
    return FileResponse(path)


@app.get("/")
def index():
    return RedirectResponse("/dispatcher")


@app.get("/dispatcher", include_in_schema=False)
def page_dispatcher():
    return _page("dispatcher.html")


@app.get("/driver", include_in_schema=False)
def page_driver():
    return _page("driver.html")


@app.get("/rider", include_in_schema=False)
def page_rider():
    return _page("rider.html")


@app.get("/admin", include_in_schema=False)
def page_admin():
    return _page("admin.html")


@app.get("/board", include_in_schema=False)
def page_board():
    return _page("board.html")


@app.get("/track", include_in_schema=False)
def page_track():
    return _page("track.html")


@app.get("/login", include_in_schema=False)
def page_login():
    return _page("login.html")


@app.get("/health")
def health():
    return {"ok": True, "now": db.now_iso(), "version": app.version,
            "map": "amap" if AMAP_JS_KEY else "schematic",
            "notify": "wecom" if notify.is_configured() else "off"}


@app.get("/api/notify/status")
def api_notify_status(user: dict = Depends(require_dispatcher)):
    return {"enabled": notify._cfg()["enabled"], "configured": notify.is_configured(),
            "channels": {"wecom": "已配置" if notify.is_configured() else "未配置（台账界面或 WECOM_WEBHOOK_URL）",
                         "mp_template": "预留（等 R2 认证主体）",
                         "miniprogram": "预留（等 R2 认证主体）"}}


class NotifyConfIn(BaseModel):
    enabled: bool = True
    wecom_webhook: str = ""
    ride_timeout_sec: int = Field(default=180, ge=30, le=3600)
    late_min: int = Field(default=5, ge=1, le=60)


@app.get("/api/notify/conf")
def api_notify_conf(user: dict = Depends(require_dispatcher)):
    conf = notify._db_conf()
    return {
        "enabled": conf.get("notify.enabled", "1") not in ("0", "false"),
        "wecom_webhook": conf.get("notify.wecom_webhook", ""),
        "ride_timeout_sec": int(conf.get("notify.ride_timeout_sec", "180")),
        "late_min": int(conf.get("notify.late_min", "5")),
    }


@app.put("/api/notify/conf")
def api_notify_conf_update(body: NotifyConfIn, user: dict = Depends(require_dispatcher)):
    conn = db.connect()
    try:
        kv = {
            "notify.enabled": "1" if body.enabled else "0",
            "notify.wecom_webhook": body.wecom_webhook.strip(),
            "notify.ride_timeout_sec": str(body.ride_timeout_sec),
            "notify.late_min": str(body.late_min),
        }
        for k, v in kv.items():
            conn.execute("INSERT INTO config(key, value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        db.log_event(conn, "crud", f"{user['n']} 更新通知配置")
        conn.commit()
    finally:
        conn.close()
    notify.invalidate_conf()
    return {"ok": True}


@app.post("/api/notify/test")
def api_notify_test(user: dict = Depends(require_dispatcher)):
    return notify.notify_test()
