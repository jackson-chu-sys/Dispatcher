#!/usr/bin/env bash
# cloud-deploy.sh — 在云服务器（Ubuntu/Debian）上一键部署 Dispatcher
#
# 用法（在云服务器上，代码目录内执行）：
#   sudo bash deploy/cloud-deploy.sh
#
# 做什么：
#   1. 检测并安装 Docker + compose 插件（缺失时）
#   2. 准备 .env（不存在则从 .env.example 复制，并提示填写高德 key）
#   3. docker compose up -d --build 起服务（映射宿主 8000）
#   4. 等待健康检查，打印访问地址与登录方式
#
# 前置：云服务器安全组/防火墙放行 8000 端口（或按需改 PORT）。
set -euo pipefail

cd "$(dirname "$0")/.."   # 切到项目根目录
APP_DIR="$(pwd)"
PORT="${PORT:-8000}"

echo "==> Dispatcher 部署 @ $APP_DIR (端口 $PORT)"

# ---------- 1. Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  echo "==> 安装 Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker || true
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "==> 安装 docker compose 插件..."
  apt-get update -y && apt-get install -y docker-compose-plugin || true
fi
echo "    Docker: $(docker --version)"

# ---------- 2. .env ----------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> 已生成 .env（从 .env.example）。"
  echo "    ⚠️  请编辑 .env 填入高德地图 key（AMAP_JS_KEY / AMAP_SECURITY_CODE）。"
  echo "       不填则地图降级为自绘示意图，其余功能不受影响。"
fi
# 试用部署默认开 DEMO 模式（登录页一键登录）
if ! grep -q '^DEMO_MODE=1' .env; then
  if grep -q '^DEMO_MODE=' .env; then
    sed -i 's/^DEMO_MODE=.*/DEMO_MODE=1/' .env
  else
    printf '\nDEMO_MODE=1\n' >> .env
  fi
  echo "==> 已开启 DEMO_MODE=1（登录页演示账号一键登录）"
fi

# 端口注入 compose（通过 PORT 环境变量覆盖 8000:8010 的宿主侧）
export COMPOSE_HOST_PORT="$PORT"

# ---------- 3. 起服务 ----------
echo "==> 构建并启动..."
docker compose up -d --build

# ---------- 4. 健康检查 ----------
echo "==> 等待服务就绪..."
for i in $(seq 1 30); do
  if curl -sf -m 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "    ✅ 服务已就绪"
    break
  fi
  sleep 2
  if [ "$i" = "30" ]; then
    echo "    ❌ 30 次探活失败，查看日志：docker compose logs --tail=50"
    exit 1
  fi
done

# ---------- 5. 访问信息 ----------
PUBIP="$(curl -fsSL -m 5 https://api.ipify.org 2>/dev/null || echo '<你的服务器公网IP>')"
echo ""
echo "============================================================"
echo " 部署完成 🎉"
echo ""
echo " 访问地址（确保云服务器安全组已放行 ${PORT} 端口）："
echo "   调度端  http://${PUBIP}:${PORT}/dispatcher"
echo "   司机端  http://${PUBIP}:${PORT}/driver"
echo "   乘客端  http://${PUBIP}:${PORT}/rider   （免登录）"
echo "   台账    http://${PUBIP}:${PORT}/admin"
echo "   看板    http://${PUBIP}:${PORT}/board"
echo ""
echo " 登录：DEMO 模式下登录页可直接点演示账号登录。"
echo " 数据持久化在 ./data 卷；备份见 scripts/backup_db.py。"
echo "============================================================"
