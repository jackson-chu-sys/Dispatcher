# Dispatcher

班车 / 电动车 (shuttle bus & scooter) 调度系统 —— 车辆、司机、线路、班次、实时位置与派单。

> **当前阶段：阶段 0 · 文档骨架**
> 代码尚未开始。范围与需求正在逐步补充，所有项目文档统一存放在本仓库 `docs/` 下。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | 文档地图与写作约定 |
| [docs/01-requirements.md](docs/01-requirements.md) | 需求：角色、核心对象、功能范围、待确认问题 |
| [docs/02-architecture.md](docs/02-architecture.md) | 架构初稿：技术选型、模块划分、数据模型草图 |
| [docs/03-roadmap.md](docs/03-roadmap.md) | 路线图与里程碑 |
| [docs/04-decisions.md](docs/04-decisions.md) | 决策记录 (ADR) |

## 仓库结构

```
Dispatcher/
├── README.md            # 本文件：项目入口
├── docs/                # 所有项目文档（单一真相源）
│   ├── README.md
│   ├── 01-requirements.md
│   ├── 02-architecture.md
│   ├── 03-roadmap.md
│   └── 04-decisions.md
└── LICENSE              # AGPL-3.0
```

代码目录按 [docs/02-architecture.md](docs/02-architecture.md) 的模块划分在阶段 1 建立。

## 协作约定

- 任何方案、需求、决策先落文档，再动代码（决策 D1）。
- 文档放本仓库，不散落在聊天记录或本地笔记里。
- 需求变更走 `01-requirements.md` 的待确认问题清单，结论记入 `04-decisions.md`。

## License

AGPL-3.0，见 [LICENSE](LICENSE)。
