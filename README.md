# Dispatcher

班车 / 电动车 (shuttle bus & scooter) 调度系统 —— 车辆、司机、线路、班次、实时位置与派单。

> **当前阶段：v0.2 · 阶段 1 收尾 + 阶段 2 主体完成（2026-11-11）**
> 乘客叫车 → 司机接单/到站上报 → 调度端实时看车在哪；已加高德地图、登录鉴权、台账 CRUD、地图画线路、排班冲突检测、WebSocket 推送、ETA、大屏看板、轨迹回放。
> 所有项目文档在 [`docs/`](docs/)，与代码同仓库。

## 📦 下载试用（非技术人员看这里）

想在自己电脑上跑起来体验？两种方式：

**方式 A · 最简单（推荐）**：点本仓库右上角绿色 **`Code`** 按钮 → **`Download ZIP`**，
解压后进入文件夹，**双击 `start.bat`**（Windows）或运行 `bash start.sh`（Mac/Linux）即可。
详细图文步骤见 **[INSTALL.md](INSTALL.md)**，使用教程见 **[USER_GUIDE.md](USER_GUIDE.md)**。

**方式 B · 干净分发包**：开发者运行 `python3 scripts/make_release.py` 会在 `dist/` 生成
不含任何密钥/内部文档的试用包（`.zip` / `.tar.gz` + SHA256），可直接发给他人。

> 需要先安装 Docker（INSTALL.md 第 1 步有保姆级教程）。不配地图 key 也能用（自绘示意图模式）。
> 演示数据为示例线路（深圳南山坐标），请用「台账 → 地图画线路」录入你自己的真实线路。

---

## 快速开始

```bash
cd /mnt/projects/Dispatcher
./run.sh                                   # 起服务（默认 8000）
.venv/bin/python scripts/reset_demo.py     # 重置演示数据
```

- 调度端 `http://<nas-ip>:8000/dispatcher`
- 司机端 `http://<nas-ip>:8000/driver`
- 乘客端 `http://<nas-ip>:8000/rider`

Docker：`docker compose up -d --build`（宿主端口 8000 → 容器 8010，数据卷 `./data`，`AMAP_JS_KEY` / `AMAP_SECURITY_CODE` / `DISPATCHER_PASSWORD` 走环境变量或 `.env`）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 文档地图与写作约定 |
| [docs/01-requirements.md](docs/01-requirements.md) | 需求（v2 定稿）：痛点、角色、叫车流程、验收标准、Q1–Q11 回答记录 |
| [docs/02-architecture.md](docs/02-architecture.md) | 架构 as-built：数据模型、接口清单、地图双实现、已知限制 |
| [docs/03-roadmap.md](docs/03-roadmap.md) | 阶段 0/1/2/3 与里程碑进度 |
| [docs/04-decisions.md](docs/04-decisions.md) | 决策记录 D1–D16（含小程序、高德地图、SQLite、WebSocket、鉴权、冲突检测、ETA、轨迹的取舍） |
| [docs/05-demo-guide.md](docs/05-demo-guide.md) | DEMO 怎么打开、三分钟演示脚本、命令、已知问题 |
| [docs/06-deployment.md](docs/06-deployment.md) | 试用/上线部署：PaaS 托管、云服务器一键部署、环境变量、高德 key 域名白名单坑 |

## 技术栈

FastAPI + SQLite（单文件，WAL）+ 原生 JS 静态页，无前端构建；地图用高德 JS API v2.0（`AMAP_JS_KEY` + `AMAP_SECURITY_CODE`，见 `.env.example`），无 key 时降级为自绘 SVG 示意图；通知走企业微信群机器人（台账页可配），个人微信推送预留待 R2。

## License

AGPL-3.0，见 [LICENSE](LICENSE)。
