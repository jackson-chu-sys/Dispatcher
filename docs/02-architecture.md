# 02 · 架构（as-built，v0.2：阶段1收尾 + 阶段2）

**状态：与代码一致（2026-11-11）** ｜ 变更须先改本文档

## 1. 形态

单体 FastAPI + SQLite 单文件 + 原生 JS 静态页，无构建步骤、无前端框架。

```
浏览器（调度端/台账/看板/轨迹 · 司机端 H5 · 乘客端 H5）
        │  WebSocket /ws（2s 推送）＋ REST fetch（断线降级轮询）
┌───────▼─────────────────────────┐
│ FastAPI (app/main.py)           │
│  ├─ REST API  /api/*（token 鉴权）│
│  ├─ WS 推送   /ws（Hub 广播 state）│
│  ├─ 静态页    /dispatcher /admin /board /track /driver /rider /login
│  └─ 静态资源  /static            │
├─────────────────────────────────┤
│ SQLite (data/dispatcher.db)     │  WAL，单文件，随卷持久化
└─────────────────────────────────┘
高德 JS API v2.0（浏览器直连，key 由 /api/state 下发）
```

## 2. 目录

```
Dispatcher/
├── app/
│   ├── main.py        # 全部 REST 接口 + 页面路由 + WS 广播
│   ├── notify.py      # 通知层：企业微信群机器人 + watchdog 巡检（超时/晚点/未发车）
│   └── db.py          # 建表、迁移、种子数据、每日 trip 生成
├── static/
│   ├── base.css       # 深色主题
│   ├── auth.js        # token 存取、鉴权 fetch、页面守卫、WS Live 订阅
│   ├── map.js         # 地图渲染：高德 JS v2.0 / 自绘示意图双实现
│   ├── login.html     # 司机（手机号）/ 调度员（口令）登录
│   ├── dispatcher.html  # 调度端（实时地图+ETA+班次+叫车）
│   ├── admin.html     # 台账 CRUD + 地图画线路 + 排班
│   ├── board.html     # 大屏看板（在线率/准点率/完成率）
│   ├── track.html     # 历史轨迹回放
│   ├── driver.html    # 司机端
│   └── rider.html     # 乘客端（免登录）
├── scripts/
│   └── reset_demo.py  # 清库重播种（含自增序列重置）
├── run.sh             # 本地启动（自动建 venv）
├── Dockerfile / docker-compose.yml
└── docs/
```

## 3. 数据模型

| 表 | 关键字段 | 说明 |
|---|---|---|
| `vehicles` | plate, kind, seats, status | 车牌/车型/座位 |
| `drivers` | name, phone, vehicle_id | 司机与车辆一对一 |
| `routes` | name, direction(loop), color | 线路 |
| `stops` | route_id, seq, name, lat, lng | 站点，按 seq 排序成线路 |
| `shifts` | route_id, vehicle_id, driver_id, depart_time, **duration_min** | 计划班次（HH:MM + 预计时长，用于冲突检测/ETA） |
| `trips` | shift_id, day, status, current_stop_id, arrived_at, **started_at** | **当天实际运行**；位置真相在 `current_stop_id + arrived_at`；started_at 用于准点率 |
| `ride_requests` | rider, from_stop_id, to_stop_id, people, status, vehicle_id, driver_id | 叫车单 |
| `arrivals` | trip_id, stop_id, ts | **到站明细**（每次上报追加一行，轨迹回放数据源） |
| `events` | ts, kind, detail | 事件日志，所有状态变更留痕 |
| `config` | key, value | 运行时配置（通知开关/webhook/阈值），台账页可改 |

设计要点：
- **班次是计划，行程是实际**。排班改 `shifts`；位置/状态只写 `trips`，不覆盖历史。
- **位置不建连续位置表**：到站触发的本质是"车辆当前所在的站点"，`trips.current_stop_id` 即当前位置；
  `arrivals` 只追加到站事件（回放用），与 D6 到站触发一致，数据量可控。
- 每天首次请求/启动时幂等生成当日 `trips`（`_ensure_today_trips`）。

## 4. 接口一览

鉴权：`X-Token` 头（登录签发 HMAC token，12h）。乘客端接口免登录；台账/排班仅调度员；司机只能操作自己。

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| POST | `/api/login` | 公开 | 司机=手机号 / 调度员=口令 |
| GET | `/api/me` | token | 当前用户 |
| WS | `/ws` | 公开(只读) | 2s 全量 state 推送（变更即推） |
| GET | `/api/state` | 公开(只读) | 全量状态：车辆/线路/班次/叫车单/事件/统计/地图配置 |
| GET | `/api/drivers` | token | 司机+车辆列表 |
| GET | `/api/driver/{id}` | 本人/调度 | 司机视图：今日班次（含站点/延迟）、相关叫车单（含ETA） |
| POST | `/api/driver/{id}/start` | 本人/调度 | 发车（记 started_at） |
| POST | `/api/driver/{id}/arrive` | 本人/调度 | **到站上报**（校验站点归属；写 arrivals；可带 done_after 完班） |
| POST | `/api/driver/{id}/finish` | 本人/调度 | 手动结束班次 |
| GET | `/api/rider/options` | 公开 | 线路+站点（供乘客选起终点） |
| POST | `/api/ride` | 公开 | 叫车 |
| GET | `/api/ride/{id}` | 公开 | 叫车单详情 + 接单车位置 + ETA + 已等时长 |
| POST | `/api/ride/{id}/accept` | 司机/调度 | 接单（司机只能以自己身份） |
| POST | `/api/ride/{id}/board` `/done` | token | 已接到 / 送达 |
| POST | `/api/ride/{id}/cancel` | 公开 | 取消（乘客可自助） |
| GET/POST/PUT/DELETE | `/api/vehicles` `/api/drivers` `/api/routes` `/api/stops` `/api/shifts` | 读=token / 写=调度 | 台账 CRUD；`/api/stops/batch` 地图画线路批量建站；班次写操作含**冲突检测(409)** |
| GET | `/api/dashboard` | token | 看板：在线率/准点率/完成率/叫车统计 |
| GET | `/api/trips/today` | token | 今日行程列表（回放选择用） |
| GET | `/api/trip/{id}/track` | token | 到站序列 + 线路站点（轨迹回放） |
| GET | `/api/events?limit=` | token | 事件日志（全部） |
| GET/PUT | `/api/notify/conf` | 调度 | 通知配置（开关/webhook/超时阈值/晚点阈值） |
| GET | `/api/notify/status` | 调度 | 通知通道状态 |
| POST | `/api/notify/test` | 调度 | 发送测试消息（同步返回真实结果） |
| GET | `/health` | 公开 | 看门狗探活 |

## 5. 前端实现

- 七个静态页，原生 JS + `fetch`，无框架、无打包；公共逻辑在 `auth.js`（token/守卫/Live）。
- 调度端/司机端走 **WebSocket**（`Live.start`，2s 服务端推送，断线自动降回 3–4s 轮询并重连）；
  乘客端保持 4s 轮询（免登录、页面简单）。
- **地图双实现**（`static/map.js`）：
  - `AMAP_JS_KEY` 有值 → 加载高德 JS v2.0（配 `AMAP_SECURITY_CODE` 安全密钥），画线路 `Polyline` + 站点/车辆 `Marker`（增量更新防闪烁），
    地图实例只建一次，后续推送只增量替换 overlay（线路/站点/车辆 Marker），避免重建闪烁；
  - 无 key → **自绘 SVG 示意图**（经纬度线性投影 + 网格 + 线路折线 + 车辆标签），DEMO 默认可跑。
- 颜色：线路色来自 `routes.color`；车辆标签显示车牌尾号 + 当前站。

## 6. 部署

- 当前实际以容器内进程直跑 `0.0.0.0:8000`（宿主已映射 8000；8010 宿主未开放，2026-11-11 由 FinAdvisor 让出 8000）。
- `docker-compose.yml` 为独立部署形态（`./data` 挂卷持久化，`AMAP_*` / `DISPATCHER_PASSWORD` 走环境变量或 `.env`）。
- 容器内由 cron 看门狗 `ensure-dispatcher.sh`（每 10 分钟）探活并拉起，日志在 `logs/server.log`。

## 7. 已知限制 / 阶段 2 再改

| 限制 | 影响 | 后续 |
|---|---|---|
| 司机登录无密码（仅手机号） | 内网可冒名 | 上线前换短信验证码（R4） |
| 调度员共享单口令 | 无操作归责 | 多账号 + 审计（R4） |
| ETA 为站序推算，非路径规划 | 精度有限 | 有连续 GPS 后接高德路径规划 |
| WS 广播全量 state | 数据量大时带宽涨 | 增量 diff 推送 |
| SQLite 单文件 | 并发写弱 | 量级上来迁 Postgres |
| 小程序未做 | 司机需开浏览器 | 用微信 JS-SDK 或 Taro 复用接口（R2） |
| 弱网离线补传未做 | 隧道/地库丢上报 | 本地队列 + 恢复补传 |
