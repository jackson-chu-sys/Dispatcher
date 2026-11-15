#!/usr/bin/env bash
# stop.sh —— 停止 Dispatcher 容器（数据保留在 ./data，不丢失）
cd "$(dirname "$0")"
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
else echo "未检测到 docker compose"; exit 1; fi

echo "正在停止 Dispatcher…"
$DC down
echo "已停止。数据仍保留在 ./data 目录，下次 bash start.sh 会接着用。"
