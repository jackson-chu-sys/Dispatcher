#!/usr/bin/env bash
# start.sh —— 一键启动 Dispatcher 试用版（macOS / Linux）
# 双击或终端执行：bash start.sh
set -uo pipefail

cd "$(dirname "$0")"
PORT="${COMPOSE_HOST_PORT:-8000}"

say()  { printf '\n\033[1;36m%s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m  ✗ %s\033[0m\n\n' "$1"; exit 1; }

say "Dispatcher 班车调度 DEMO · 一键启动"

# ---------- 1. 检查 Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  die "未检测到 Docker。请先按 INSTALL.md 第 1 步安装 Docker，再重新运行本脚本。"
fi
ok "已安装 Docker：$(docker --version 2>/dev/null | head -1)"

if ! docker info >/dev/null 2>&1; then
  die "Docker 没有运行。请先启动 Docker Desktop（或 Linux 上执行 sudo systemctl start docker），等它就绪后重新运行本脚本。"
fi
ok "Docker 正在运行"

# 兼容 docker compose (v2) 与 docker-compose (v1)
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  die "未检测到 docker compose。Docker Desktop 自带；Linux 请按 INSTALL.md 安装 docker-compose-plugin。"
fi
ok "compose 命令：$DC"

# ---------- 2. 准备 .env ----------
if [ ! -f .env ]; then
  cp .env.example .env
  # 试用包默认开启演示账号一键登录
  if grep -q '^DEMO_MODE=' .env; then
    sed -i.bak 's/^DEMO_MODE=.*/DEMO_MODE=1/' .env && rm -f .env.bak
  else
    printf 'DEMO_MODE=1\n' >> .env
  fi
  ok "已生成配置文件 .env（演示模式已开启）"
  warn "地图默认为「示意图」。想用真实地图：免费申请高德 key 填入 .env，详见 INSTALL.md 第 4 步。"
else
  ok "已存在配置文件 .env（沿用你的设置）"
fi

# ---------- 3. 端口占用检查 ----------
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  warn "端口 $PORT 已被其他程序占用，本次改用 $((PORT+1))"
  PORT=$((PORT+1))
fi
export COMPOSE_HOST_PORT="$PORT"

# ---------- 4. 构建并启动 ----------
say "正在构建并启动容器（首次约需 1-3 分钟，请耐心等待）…"
if ! $DC up -d --build; then
  die "启动失败。请把上面红色报错截图发给开发者，或查看日志：$DC logs --tail=50"
fi

# ---------- 5. 等待就绪 ----------
say "等待服务就绪…"
READY=0
for i in $(seq 1 60); do
  if curl -sf -m 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 2
done

if [ "$READY" != "1" ]; then
  warn "服务未在 2 分钟内就绪。查看日志：$DC logs --tail=50"
fi

# ---------- 6. 打印访问方式 ----------
LANIP="$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') | head -1 )"
[ -z "$LANIP" ] && LANIP="<本机局域网IP>"

cat <<EOF

============================================================
  启动完成 🎉

  本机访问（推荐先在本机打开）：
    登录页    http://127.0.0.1:${PORT}/login
    调度端    http://127.0.0.1:${PORT}/dispatcher
    乘客端    http://127.0.0.1:${PORT}/rider      （免登录）

  同一 WiFi 下手机/他人访问：
    http://${LANIP}:${PORT}/login
    乘客端    http://${LANIP}:${PORT}/rider

  登录方式：登录页已开启「演示账号一键登录」，
            点任一司机或调度员按钮即可进入，无需输入。

  停止服务：bash stop.sh
  重置演示数据：$DC exec dispatcher python scripts/reset_demo.py --force
============================================================

EOF

# macOS 自动打开浏览器
if [ "$(uname)" = "Darwin" ]; then
  open "http://127.0.0.1:${PORT}/login" 2>/dev/null || true
fi
