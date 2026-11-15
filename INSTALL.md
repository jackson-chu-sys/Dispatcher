# Dispatcher 班车调度 DEMO · 安装说明

> 这是一份**写给非技术人员**的安装指南。全程只需复制粘贴几条命令、点几下鼠标，
> 不需要懂编程。预计耗时：首次约 15–25 分钟（主要花在装 Docker 和下载镜像）。
>
> 装好后，你会得到一个可在浏览器打开的「班车调度系统」，支持乘客叫车、司机接单上报、
> 调度员看地图派单。可在**本机**用，也可让**同一 WiFi 下的手机/同事**一起用。

---

## 你将得到什么

一个跑在 Docker 容器里的调度系统，打开浏览器访问 4 个页面：

| 页面 | 地址 | 给谁用 | 要不要登录 |
|---|---|---|---|
| 登录页 | `http://127.0.0.1:8000/login` | 司机 / 调度员 | — |
| 调度端 | `http://127.0.0.1:8000/dispatcher` | 调度员（电脑） | 调度员 |
| 司机端 | `http://127.0.0.1:8000/driver` | 司机（手机） | 司机 |
| 乘客端 | `http://127.0.0.1:8000/rider` | 乘客（手机） | **免登录** |

---

## 第 0 步 · 确认你的电脑系统

- **Windows 10/11**（64 位）→ 看下面「Windows 安装」
- **macOS**（苹果电脑）→ 看「macOS 安装」
- **Linux**（Ubuntu/Debian 等）→ 看「Linux 安装」

> 需要电脑能上网（下载 Docker 和镜像）。系统盘建议留 3 GB 以上空闲空间。

---

## 第 1 步 · 安装 Docker（只需做一次）

Docker 是一个"容器"运行环境，本系统跑在它里面，干净、不污染你的电脑。

### ▶ Windows 安装

1. 打开浏览器访问 **https://www.docker.com/products/docker-desktop/** ，点 **Download for Windows**。
2. 双击下载好的 `Docker Desktop Installer.exe`，一路点 **Next / Install**（默认选项即可）。
   - 若弹出"启用 WSL 2"的提示，勾选同意。
   - 安装中若要求重启电脑，请重启。
3. 重启后，从开始菜单打开 **Docker Desktop**，同意服务条款。
4. 等待左下角状态变成 **绿色 Engine running**（首次可能要 1–2 分钟）。**这一步很重要，没变绿就等。**

### ▶ macOS 安装

1. 访问 **https://www.docker.com/products/docker-desktop/** ，点 **Download for Mac**。
   - 苹果芯片（M1/M2/M3/M4）选 **Apple Chip**；老款英特尔芯片选 **Intel Chip**。
2. 打开下载的 `.dmg`，把 **Docker** 图标拖进 **Applications** 文件夹。
3. 从"启动台"或"应用程序"里打开 **Docker**，按提示输入开机密码授权。
4. 等待顶部菜单栏出现 🐳 鲸鱼图标且不再闪动（表示已就绪）。

### ▶ Linux 安装（Ubuntu / Debian）

打开"终端"，复制粘贴下面这行命令，回车，按提示输入密码（输密码时屏幕不显示是正常的）：

```bash
curl -fsSL https://get.docker.com | sudo sh
```

装完后，让当前用户免 sudo 使用 docker，然后启动：

```bash
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
```

> 执行完 `usermod` 后**注销再重新登录**（或重启）一次，免 sudo 才会生效。

### ✅ 验证 Docker 装好了

打开终端（Windows 用 **PowerShell** 或 **CMD**；macOS/Linux 用 **Terminal**），输入：

```bash
docker --version
```

看到类似 `Docker version 26.x.x` 就成功了。再测一条：

```bash
docker run --rm hello-world
```

看到 `Hello from Docker!` 字样即一切正常。

---

## 第 2 步 · 下载并解压本 DEMO

1. 把你拿到的压缩包（`dispatcher-demo-vX.X.zip` 或 `.tar.gz`）保存到电脑，例如桌面。
2. 解压它：
   - **Windows**：右键压缩包 → **全部解压缩** → 选个文件夹（如桌面）→ 解压。
   - **macOS**：双击 `.zip` 即自动解压；`.tar.gz` 双击也能解压。
   - **Linux**：`tar -xzf dispatcher-demo-vX.X.tar.gz`
3. 解压后得到一个文件夹（里面有 `start.sh`、`start.bat`、`Dockerfile` 等文件）。

---

## 第 3 步 · 一键启动

进入刚解压的文件夹，按系统选择：

### ▶ Windows
**双击 `start.bat`**。
- 若弹出蓝色"Windows 已保护你的电脑"，点 **更多信息 → 仍要运行**。
- 脚本会自动检查 Docker、构建并启动，首次需 1–3 分钟，请耐心等命令行窗口跑完。
- 完成后会自动打开浏览器进入登录页。

### ▶ macOS / Linux
打开终端，进入解压的文件夹（可以把文件夹拖进终端窗口自动得到路径），然后运行：

```bash
bash start.sh
```

脚本会自动检查 Docker、构建并启动，完成后自动打开浏览器。

### ✅ 看到这些就成功了

命令行最后会打印一段方框，里面有访问地址；浏览器会自动打开**登录页**，
页面上能看到「⚡ 演示账号 · 点击直接登录」和几个按钮（张伟/李强/调度员等）。
**点任意按钮即可登录试用，不用输入任何账号密码。**

---

## 第 4 步 ·（可选）开启真实地图

不配置时，地图显示为**自绘示意图**（线路和站点位置示意，功能完全正常，适合先试用）。
想换成真实地图（高德），按下面做——**完全免费**：

1. 访问 **https://console.amap.com** 注册并登录（用手机号即可，个人免费）。
2. 进入 **应用管理 → 我的应用 → 创建新应用**，随便起个名（如"班车调度"）。
3. 在该应用下 **添加 Key**：
   - Key 名称随便填；
   - **服务平台必须选「Web端（JS API）」**；
   - 提交后会得到一串 **Key** 和一串 **安全密钥（jscode）**。
4. 用记事本（Windows）或文本编辑（macOS）打开解压文件夹里的 `.env` 文件，
   把这两行填上你的值（等号后面直接粘贴，不要加引号和空格）：

   ```
   AMAP_JS_KEY=把你…贴这里
   AMAP_SECURITY_CODE=把你…贴这里
   ```
5. 保存 `.env`，然后重启服务让它生效：
   - Windows：双击 `stop.bat`，再双击 `start.bat`
   - macOS/Linux：终端里 `bash stop.sh` 然后 `bash start.sh`

刷新页面，地图就变成真实地图了。

---

## 第 5 步 · 让手机/同事一起用（同一 WiFi）

调度、司机、乘客要在**不同设备**上才能演示完整流程。只要这些设备和本机连**同一个 WiFi**：

1. 查本机局域网 IP：
   - **Windows**：终端输入 `ipconfig`，找 `IPv4 地址`（形如 `192.168.x.x`）。
   - **macOS**：终端输入 `ipconfig getifaddr en0`。
   - **Linux**：终端输入 `hostname -I`。
2. 在手机浏览器打开：
   - 乘客叫车：`http://192.168.x.x:8000/rider`（把 IP 换成你的）
   - 司机登录：`http://192.168.x.x:8000/login`
3. 若手机打不开，多半是**电脑防火墙**拦了。临时允许：
   - **Windows**：第一次运行 `start.bat` 弹窗时勾选"专用网络"并允许；
     或到「Windows 安全中心 → 防火墙 → 允许应用通过防火墙」里放行 Docker。
   - **macOS**：系统设置 → 网络 → 防火墙，临时关闭或放行 Docker。

---

## 常用操作

| 操作 | Windows | macOS / Linux |
|---|---|---|
| 启动 | 双击 `start.bat` | `bash start.sh` |
| 停止 | 双击 `stop.bat` | `bash stop.sh` |
| 看日志 | `docker compose logs -f` | `docker compose logs -f` |
| 重置为初始演示数据 | `docker compose exec dispatcher python scripts/reset_demo.py --force` | 同左 |

> **数据保存在哪**：你画的线路、站点、账号等都存在解压文件夹的 `data/` 里。
> 停止/重启不会丢；**删除整个文件夹才会丢**。想备份就复制 `data/` 文件夹。

---

## 遇到问题

| 现象 | 原因与解决 |
|---|---|
| 双击脚本一闪而过 | Windows 请用**右键 → 以管理员身份运行 PowerShell**，`cd` 进文件夹后运行 `.\start.bat`，才能看到报错信息 |
| 提示"Docker 没有运行" | 先启动 Docker Desktop，等它就绪（绿/鲸鱼不闪）再双击脚本 |
| 卡在"构建中"很久 | 首次要下载基础镜像，视网速 1–5 分钟；保持网络通畅，别关窗口 |
| 浏览器打开是空白/打不开 | 等 10 秒刷新；或手动访问 `http://127.0.0.1:8000/login` |
| 端口 8000 被占用 | 脚本会自动改用 8001；也可编辑 `.env` 里没有端口项，改用环境变量：`COMPOSE_HOST_PORT=8080 bash start.sh` |
| 手机打不开、电脑能打开 | 见第 5 步防火墙设置；并确认手机与电脑同一 WiFi（不是手机流量） |
| 想彻底卸载 | `bash stop.sh`（或 stop.bat）后删除整个解压文件夹；再按需卸载 Docker Desktop |

需要帮助时，请把命令行里的**红色报错**截图发给开发者。

---

## 安全与许可提示

- 本 DEMO 的"演示账号一键登录"（`DEMO_MODE=1`）**仅供本地试用**，任何人都能进调度端。
  **请勿直接把它暴露到公网正式使用**；正式上线需关闭演示模式（.env 里 DEMO_MODE=0）并配置短信验证。详见项目主页 https://github.com/jackson-chu-sys/Dispatcher 的 docs/。
- 本软件以 **AGPL-3.0** 许可开源，完整条款见同目录 `LICENSE`。
