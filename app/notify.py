"""通知分发：企业微信群机器人（零认证）+ 预留服务号/小程序通道。

设计原则：
- 不阻塞业务：常规通知在后台 daemon 线程发送。
- 失败不影响主流程：吞异常、记日志。
- 未配置 webhook 时静默跳过（send 直接 return False）。
- 去重/限流：同一 dedup_key 在 TTL 内只发一次，避免刷屏。

配置（.env / 环境变量）：
  NOTIFY_ENABLED      1/0，默认 1
  WECOM_WEBHOOK_URL   企业微信群机器人 webhook，多个用逗号分隔
  RIDE_TIMEOUT_SEC    叫车超时未接单告警阈值（秒），默认 180
  LATE_MIN            发车晚点告警阈值（分钟），默认 5
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from . import db

_LOCK = threading.Lock()
_DEDUP: dict[str, float] = {}
_DEDUP_TTL = 300


_CONF_CACHE: dict | None = None


def _db_conf() -> dict:
    """台账界面保存的通知配置（缓存 60s，避免每次通知都查库）。"""
    global _CONF_CACHE
    now = time.time()
    if _CONF_CACHE and now - _CONF_CACHE.get("_t", 0) < 60:
        return _CONF_CACHE
    try:
        conn = db.connect()
        try:
            conf = {r["key"]: r["value"] for r in
                    conn.execute("SELECT key, value FROM config WHERE key LIKE 'notify.%'")}
        finally:
            conn.close()
    except Exception:
        conf = {}
    conf["_t"] = now
    _CONF_CACHE = conf
    return conf


def invalidate_conf() -> None:
    global _CONF_CACHE
    _CONF_CACHE = None


def _cfg() -> dict:
    conf = _db_conf()
    enabled = conf.get("notify.enabled", os.environ.get("NOTIFY_ENABLED", "1"))
    urls = [u.strip() for u in
            (conf.get("notify.wecom_webhook") or os.environ.get("WECOM_WEBHOOK_URL", "")).split(",")
            if u.strip()]
    return {
        "enabled": str(enabled).strip() not in ("0", "false", "False", ""),
        "wecom": urls,
    }


def is_configured() -> bool:
    return bool(_cfg()["wecom"])


def _post_all(urls: list[str], markdown: str) -> dict:
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": markdown}}).encode()
    sent, errors = 0, []
    for url in urls:
        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=8) as r:
                resp = json.loads(r.read().decode() or "{}")
                if resp.get("errcode") == 0:
                    sent += 1
                else:
                    errors.append(resp)
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append(str(e))
    return {"sent": sent, "errors": errors}


def send_wecom(markdown: str, *, dedup_key: str | None = None, dedup_ttl: int = _DEDUP_TTL) -> bool:
    """异步发送（后台线程），不阻塞调用方。返回是否已排队发送。"""
    cfg = _cfg()
    if not cfg["enabled"] or not cfg["wecom"]:
        return False
    if dedup_key:
        now = time.time()
        with _LOCK:
            last = _DEDUP.get(dedup_key, 0.0)
            if now - last < dedup_ttl:
                return False
            _DEDUP[dedup_key] = now
            # 简单清理过期键，防内存增长
            if len(_DEDUP) > 2000:
                for k in [k for k, t in _DEDUP.items() if now - t > dedup_ttl * 2]:
                    _DEDUP.pop(k, None)
    threading.Thread(target=_safe_post, args=(cfg["wecom"], markdown), daemon=True).start()
    return True


def _safe_post(urls: list[str], markdown: str) -> None:
    try:
        res = _post_all(urls, markdown)
        if res["errors"]:
            print(f"[notify] wecom errors: {res['errors'][:2]}")
    except Exception as e:                                   # pragma: no cover
        print(f"[notify] unexpected send error: {e}")


def send_wecom_sync(markdown: str) -> dict:
    """同步发送（测试接口用），返回真实结果。"""
    cfg = _cfg()
    if not cfg["enabled"]:
        return {"configured": False, "sent": 0, "errors": ["通知已关闭（notify.enabled=0）"]}
    if not cfg["wecom"]:
        return {"configured": False, "sent": 0, "errors": ["未配置 webhook（台账页「通知设置」或 WECOM_WEBHOOK_URL）"]}
    res = _post_all(cfg["wecom"], markdown)
    return {"configured": True, **res}


# ---------------------------------------------------------------- 业务通知封装

def notify_new_ride(ride_id: int, rider: str, people: int, from_name: str, to_name: str) -> None:
    send_wecom(
        f'🚐 <font color="info">新叫车</font> #{ride_id}\n'
        f'>乘客：{rider}（{people} 人）\n'
        f'>行程：{from_name} → {to_name}\n'
        f'>请司机尽快接单',
        dedup_key=f"new:{ride_id}", dedup_ttl=3600)


def notify_ride_timeout(ride_id: int, rider: str, people: int, from_name: str, to_name: str,
                        waited_min: int) -> None:
    send_wecom(
        f'⚠️ <font color="warning">叫车超时未接单</font> #{ride_id}\n'
        f'>乘客：{rider}（{people} 人）\n'
        f'>行程：{from_name} → {to_name}\n'
        f'>已等待 <font color="warning">{waited_min} 分钟</font>，请调度尽快指派',
        dedup_key=f"timeout:{ride_id}", dedup_ttl=600)


def notify_late(route_name: str, depart_time: str, plate: str, driver_name: str,
                started_hhmm: str, delay: int, trip_id: int) -> None:
    send_wecom(
        f'⏰ <font color="comment">班次晚点</font>\n'
        f'>{route_name} {depart_time}（{plate}/{driver_name}）\n'
        f'>实际发车 {started_hhmm}，晚 {delay} 分钟',
        dedup_key=f"late:{trip_id}", dedup_ttl=3600)


def notify_no_start(route_name: str, depart_time: str, plate: str, driver_name: str,
                    overdue: int, trip_id: int) -> None:
    send_wecom(
        f'❗ <font color="warning">班次未发车</font>\n'
        f'>{route_name} {depart_time}（{plate}/{driver_name}）\n'
        f'>已过 {overdue} 分钟仍未发车，请核查',
        dedup_key=f"nostart:{trip_id}", dedup_ttl=1800)


def notify_test() -> dict:
    return send_wecom_sync(
        f'✅ <font color="info">Dispatcher 通知测试成功</font>\n'
        f'>时间：{db.now_iso()}\n>通道：企业微信群机器人')


# ---------------------------------------------------------------- 后台巡检

def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _to_min(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return -1


def scan_once() -> None:
    """扫描超时叫车 + 晚点/未发车班次，触发通知（带去重）。"""
    if not is_configured():
        return
    conf = _db_conf()
    timeout = int(conf.get("notify.ride_timeout_sec",
                           os.environ.get("RIDE_TIMEOUT_SEC", "180")) or 180)
    late_min = int(conf.get("notify.late_min", os.environ.get("LATE_MIN", "5")) or 5)
    conn = db.connect()
    try:
        now_dt = datetime.fromisoformat(db.now_iso())
        nowmin = now_dt.hour * 60 + now_dt.minute

        # 1) 超时未接单的叫车
        for r in _rows(conn, """SELECT rr.id, rr.rider, rr.people, rr.created_at,
                                       fs.name AS from_name, ts.name AS to_name
                                FROM ride_requests rr
                                JOIN stops fs ON fs.id=rr.from_stop_id
                                JOIN stops ts ON ts.id=rr.to_stop_id
                                WHERE rr.status='waiting'"""):
            try:
                waited = (now_dt - datetime.fromisoformat(r["created_at"])).total_seconds()
            except Exception:
                continue
            if waited >= timeout:
                notify_ride_timeout(r["id"], r["rider"], r["people"], r["from_name"],
                                    r["to_name"], int(waited // 60))

        # 2) 晚点 / 未发车班次（仅当天、未结束）
        day = db.today_str()
        for t in _rows(conn, """SELECT t.id, t.status, t.started_at, sh.depart_time,
                                       r.name AS route_name, v.plate, d.name AS driver_name
                                FROM trips t JOIN shifts sh ON sh.id=t.shift_id
                                JOIN routes r ON r.id=sh.route_id
                                JOIN vehicles v ON v.id=sh.vehicle_id
                                JOIN drivers d ON d.id=sh.driver_id
                                WHERE t.day=? AND t.status<>'done'""", (day,)):
            dep = _to_min(t["depart_time"])
            if dep < 0:
                continue
            if t["status"] == "waiting":
                overdue = nowmin - dep
                # 仅对“刚过点不久”的告警，避免演示/历史数据刷屏（>120min 视为历史）
                if late_min <= overdue <= 120:
                    notify_no_start(t["route_name"], t["depart_time"], t["plate"],
                                    t["driver_name"], overdue, t["id"])
            elif t["status"] == "running" and t["started_at"]:
                delay = _to_min(t["started_at"][11:16]) - dep
                if delay >= late_min:
                    notify_late(t["route_name"], t["depart_time"], t["plate"],
                                t["driver_name"], t["started_at"][11:16], delay, t["id"])
    finally:
        conn.close()


async def watchdog_loop(interval: int = 30) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(scan_once)
        except Exception as e:                               # pragma: no cover
            print(f"[notify] watchdog error: {e}")
