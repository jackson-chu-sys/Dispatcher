# Dispatcher

班车 / 电动车 (shuttle bus & scooter) 调度系统 —— 车辆、司机、线路、班次、实时位置与派单。

> **当前阶段：阶段 1 · DEMO v0.1 可跑（2026-11-11）**
> 乘客叫车 → 司机接单/到站上报 → 调度端看车在哪，主链路已跑通。
> 所有项目文档在 [`docs/`](docs/)，与代码同仓库。

## 快速开始

```bash
cd /mnt/projects/Dispatcher
./run.sh                                   # 起服务（默认 8010）
.venv/bin/python scripts/reset_demo.py     # 重置演示数据
```

- 调度端 `http://<nas-ip>:8010/dispatcher`
- 司机端 `http://<nas-ip>:8010/driver`
- 乘客端 `http://<nas-ip>:8010/rider`

Docker：`docker compose up -d --build`（宿主端口 8010，数据卷 `./data`，`TENCENT_MAP_KEY` 走环境变量）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 文档地图与写作约定 |
| [docs/01-requirements.md](docs/01-requirements.md) | 需求（v2 定稿）：痛点、角色、叫车流程、验收标准、Q1–Q11 回答记录 |
| [docs/02-architecture.md](docs/02-architecture.md) | 架构 as-built：数据模型、接口清单、地图双实现、已知限制 |
| [docs/03-roadmap.md](docs/03-roadmap.md) | 阶段 0/1/2/3 与里程碑进度 |
| [docs/04-decisions.md](docs/04-decisions.md) | 决策记录 D1–D12（含小程序、地图、SQLite、轮询的取舍） |
| [docs/05-demo-guide.md](docs/05-demo-guide.md) | DEMO 怎么打开、三分钟演示脚本、命令、已知问题 |

## 技术栈

FastAPI + SQLite（单文件，WAL）+ 原生 JS 静态页，无前端构建；地图支持腾讯位置服务，无 key 时降级为自绘 SVG 示意图。

## License

AGPL-3.0，见 [LICENSE](LICENSE)。
