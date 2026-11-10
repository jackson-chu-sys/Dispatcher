#!/usr/bin/env bash
# 本地启动 DEMO（开发用，带热重载）
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8010}"
HOST="${HOST:-0.0.0.0}"
RELOAD="${RELOAD:-1}"

if [ ! -x .venv/bin/uvicorn ]; then
  echo "首次运行：创建虚拟环境并安装依赖"
  uv venv .venv --python 3.13
  uv pip install --python .venv/bin/python -r requirements.txt
fi

ARGS=(--host "$HOST" --port "$PORT")
[ "$RELOAD" = "1" ] && ARGS+=(--reload)

echo "Dispatcher DEMO → http://localhost:${PORT}/dispatcher （司机端 /driver，乘客端 /rider）"
exec .venv/bin/uvicorn app.main:app "${ARGS[@]}"
