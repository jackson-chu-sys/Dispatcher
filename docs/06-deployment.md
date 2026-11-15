# 06 · 部署（试用 / 上线）

**适用：v0.2+** ｜ 最后更新：2026-11-15

Dispatcher 是**协同型**系统：乘客叫车 → 司机接单 → 调度看同一张地图，价值全在
**所有人连同一个后端**。因此试用要给"别人"用，必须在公网部署**一份**，大家访问同一网址；
不能各自下载部署（各跑一份数据不互通，演示不出协同）。

---

## 0. 三种部署形态对比

| 形态 | 依赖 NAS？ | 成本 | 运维 | 适合 |
|---|---|---|---|---|
| 本地 NAS（现状） | 是 | 0 | 看门狗已配 | 局域网内演示 |
| **PaaS 托管**（Render/Zeabur/Fly） | 否 | 免费档~低价 | 几乎零 | **试用首选** |
| 云服务器（阿里云/腾讯云轻量） | 否 | ~¥30-60/月 | 自己管 | 接近上线 |

---

## 1. PaaS 托管（推荐试用，最省事）

把本仓库连到 PaaS，自动用根目录 `Dockerfile` 构建，给一个公网 HTTPS 网址。

通用步骤：
1. 注册平台 → New Service / 新建项目 → 连本 GitHub 仓库（jackson-chu-sys/Dispatcher）。
2. 构建类型选 **Dockerfile**（仓库根目录已有）。
3. 配环境变量（见下方「环境变量」），**`DEMO_MODE=1`**。
4. 健康检查路径填 `/health`，内部端口 `8010`（Dockerfile EXPOSE 的端口）。
5. 部署，得到公网网址，分享 `/login`。

平台备注：
- **Zeabur**：国内团队、支持支付宝、对中文友好，免费/低价档可用。
- **Render**：有免费档（闲置会休眠，首次访问慢十几秒）；付费档不休眠。
- **Fly.io / Railway**：需海外信用卡，按量计费很便宜。

> ⚠️ **持久化**：PaaS 免费档的文件系统常是临时的，容器重启 `data/dispatcher.db` 可能丢。
> 试用可接受（重启自动重新播种演示数据）；要留存数据需挂平台的持久卷（Persistent Disk/Volume），
> 把卷挂到 `/app/data`。

---

## 2. 云服务器一键部署

在云服务器（Ubuntu/Debian）上：

```bash
git clone https://github.com/jackson-chu-sys/Dispatcher.git
cd Dispatcher
cp .env.example .env && vim .env        # 填高德 key（见下）；试用保持 DEMO_MODE=1
sudo bash deploy/cloud-deploy.sh        # 自动装 Docker、构建、起服务（默认 8000 端口）
```

脚本会打印公网访问地址。**记得在云控制台安全组放行对应端口**。
数据持久化在 `./data`；每日备份见 `scripts/backup_db.py`（可加 cron）。

---

## 3. 环境变量（.env / PaaS 控制台）

| 变量 | 必填 | 说明 |
|---|---|---|
| `AMAP_JS_KEY` | 建议 | 高德 Web端(JS API) key；不填地图降级为自绘示意图 |
| `AMAP_SECURITY_CODE` | 配合上 | JS key 的安全密钥 |
| `DEMO_MODE` | 试用=1 | 登录页列出演示账号一键登录；**正式上线必须=0** |
| `DISPATCHER_PASSWORD` | 否 | 调度口令；留空首启随机生成（DEMO 模式登录页会显示） |
| `WECOM_WEBHOOK_URL` | 否 | 企业微信群机器人 webhook；留空通知待命 |
| `NOTIFY_ENABLED` | 否 | 通知开关，默认 1 |

> 🔑 **高德 key 的坑（重要）**：高德 Web端 JS key 在控制台可设「域名白名单」。
> 复用 Where2Go 的 key 部署到**新域名/新 IP** 时，若开了白名单，地图会报
> `INVALID_USER_DOMAIN` 而加载失败。两种解法：
> 1. 登录[高德控制台](https://console.amap.com) → 应用管理 → 该 key → 把新域名加进白名单；
> 2. 或新建一个不设白名单的 JS key 专供本试用。
> （安全密钥 `AMAP_SECURITY_CODE` 必须与 JS key 配套，否则报 `INVALID_USER_SCODE`。）

---

## 4. 安全提醒（试用 → 上线）

- 试用用 `DEMO_MODE=1` 方便别人点开就玩；**正式上线务必置 0**，否则任何人都能一键进调度端。
- DEMO 模式登录页会显示调度口令，仅限内网/可信试用环境。
- 司机登录是手机号无密码（内网信任模型，见决策 D11）；上线前换短信验证码（R4）。
- 公网暴露前确认：改 `DISPATCHER_PASSWORD`、评估是否要 HTTPS（PaaS 自带；云服务器建议套 Nginx+Caddy 或云厂商证书）。
