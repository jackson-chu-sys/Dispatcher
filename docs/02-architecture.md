# 02 · 架构（as-built，DEMO v0.1）

**状态：与代码一致（2026-11-11）** ｜ 变更须先改本文档

## 1. 形态

单体 FastAPI + SQLite 单文件 + 原生 JS 静态页，无构建步骤、无前端框架。

```
浏览器（调度端 / 司机端 H5 / 乘客端 H5）
        │  fetch JSON + 3s 轮询
┌───────▼─────────────────────────┐
│ FastAPI (app/main.py)           │
│  ├─ REST API  /api/*            │
│  ├─ 静态页    /dispatcher /driver /rider
│  └─ 静态资源  /static            │
├─────────────────────────────────┤
│ SQLite (data/dispatcher.db)     │  WAL，单文件，随卷持久化
└─────────────────────────────────┘
```

## 2. 目录

```
Dispatcher/
├── app/
│   ├── main.py        # 全部 REST 接口 + 页面路由
│   └── db.py          # 建表、种子数据、每日 trip 生成
├── static/
│   ├── base.css       # 深色主题
│   ├── map.js         # 地图渲染：腾讯地图 / 自绘示意图双实现
│   ├── dispatcher.html
│   ├── driver.html
│   └── rider.html
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
| `shifts` | route_id, vehicle_id, driver_id, depart_time | 计划班次（HH:MM） |
| `trips` | shift_id, day, status, current_stop_id, arrived_at | **当天实际运行**；位置真相在 `current_stop_id + arrived_at` |
| `ride_requests` | rider, from_stop_id, to_stop_id, people, status, vehicle_id, driver_id | 叫车单 |
| `events` | ts, kind, detail | 事件日志，所有状态变更留痕 |

设计要点：
- **班次是计划，行程是实际**。排班改 `shifts`；位置/状态只写 `trips`，不覆盖历史。
- **位置不建位置表**：到站触发的本质是"车辆当前所在的站点"，`trips.current_stop_id` 即位置；
  连续轨迹上报（阶段 2 若要做）才需要独立的 `position_reports`。
- 每天首次请求/启动时幂等生成当日 `trips`（`_ensure_today_trips`）。

## 4. 接口一览

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/state` | 调度端全量状态：车辆位置、线路站点、班次、开放叫车单、事件、统计 |
| GET | `/api/drivers` | 司机+车辆列表（Demo 代替登录） |
| GET | `/api/driver/{id}` | 司机视图：今日班次（含站点）、相关叫车单 |
| POST | `/api/driver/{id}/start` | 发车（可带 shift_id） |
| POST | `/api/driver/{id}/arrive` | **到站上报**（stop_id + 可选 shift_id），校验站点属于该线路 |
| GET | `/api/rider/options` | 线路+站点（供乘客选起终点） |
| POST | `/api/ride` | 叫车 |
| GET | `/api/ride/{id}` | 叫车单详情 + 接单车当前位置 |
| POST | `/api/ride/{id}/accept` | 司机接单（body: driver_id） |
| POST | `/api/ride/{id}/board` `/done` `/cancel` | 已接到 / 送达 / 取消 |
| GET | `/health` | 看门狗探活 |

## 5. 前端实现

- 三个静态页，原生 JS + `fetch`，无框架、无打包。
- 调度端/司机端/乘客端均 3–4 秒轮询（神朱要求 5 秒内可见，轮询 3 秒有余量）。
- **地图双实现**（`static/map.js`）：
  - `TENCENT_MAP_KEY` 有值 → 加载腾讯地图 GL JS，画线路 `MultiPolyline` + 站点/车辆 `MultiMarker`，
    轮询时只 `setGeometries` 更新车辆层，避免地图重建闪烁；
  - 无 key → **自绘 SVG 示意图**（经纬度线性投影 + 网格 + 线路折线 + 车辆标签），DEMO 默认可跑。
- 颜色：线路色来自 `routes.color`；车辆标签显示车牌尾号 + 当前站。

## 6. 部署

- 容器内 `0.0.0.0:8010`，宿主映射 `8000:8010`（宿主仅开放 8000 端口；2026-11-11 由 FinAdvisor 让出）。
- `docker-compose.yml` 为独立部署形态（`./data` 挂卷持久化，`TENCENT_MAP_KEY` 走环境变量）。
- 容器内由 cron 看门狗 `ensure-dispatcher.sh`（每 10 分钟）探活并拉起，日志在 `logs/server.log`。

## 7. 已知限制 / 阶段 2 再改

| 限制 | 影响 | 后续 |
|---|---|---|
| 无登录鉴权，司机靠 URL/下拉切换 | 任何人可操作 | 加手机号+验证码登录、角色 JWT |
| 无实时通道，靠轮询 | 3s 延迟、请求数随页面数线性增长 | 换 WebSocket/SSE multicast |
| 无 ETA 计算 | 乘客只看到"车在 X 站" | 按历史到站间隔估 ETA |
| 台账无编辑界面 | 改线路/车辆要改种子或库 | 补 CRUD 表单 + 地图上画线路（Q5） |
| SQLite 单文件 | 并发写弱 | 量级上来迁 Postgres |
| 小程序未做 | 司机需开浏览器 | 用微信 JS-SDK 或 Taro 复用接口 |
