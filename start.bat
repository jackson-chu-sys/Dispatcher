@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
if "%COMPOSE_HOST_PORT%"=="" set COMPOSE_HOST_PORT=8000

echo.
echo ============================================
echo   Dispatcher 班车调度 DEMO - 一键启动
echo ============================================
echo.

REM ---------- 1. 检查 Docker ----------
where docker >nul 2>&1
if errorlevel 1 (
  echo   [X] 未检测到 Docker。
  echo       请先按 INSTALL.md 第 1 步安装 Docker Desktop，
  echo       安装后重启电脑，再双击本脚本。
  echo.
  pause
  exit /b 1
)
echo   [OK] 已安装 Docker

REM ---------- 2. 检查 Docker 是否在运行 ----------
docker info >nul 2>&1
if errorlevel 1 (
  echo   [X] Docker 没有运行。
  echo       请先启动 Docker Desktop，等左下角图标变绿后再双击本脚本。
  echo.
  pause
  exit /b 1
)
echo   [OK] Docker 正在运行

REM ---------- 3. 准备 .env ----------
if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  REM 试用包默认开启演示账号一键登录
  findstr /B "DEMO_MODE=" ".env" >nul
  if errorlevel 1 (
    echo DEMO_MODE=1>> ".env"
  ) else (
    powershell -Command "(Get-Content .env) -replace '^DEMO_MODE=.*','DEMO_MODE=1' | Set-Content .env"
  )
  echo   [OK] 已生成配置文件 .env（演示模式已开启）
  echo   [!]  地图默认为示意图；想用真实地图见 INSTALL.md 第 4 步（免费申请高德 key）
) else (
  echo   [OK] 已存在配置文件 .env（沿用你的设置）
)

REM ---------- 4. 构建并启动 ----------
echo.
echo   正在构建并启动容器（首次约需 1-3 分钟，请耐心等待）...
docker compose up -d --build
if errorlevel 1 (
  echo   [X] 启动失败。请把上面的报错截图发给开发者。
  echo       或查看日志：docker compose logs --tail=50
  pause
  exit /b 1
)

REM ---------- 5. 等待就绪 ----------
echo.
echo   等待服务就绪...
set READY=0
for /L %%i in (1,1,60) do (
  if !READY!==0 (
    curl -sf -m 3 "http://127.0.0.1:%COMPOSE_HOST_PORT%/health" >nul 2>&1
    if not errorlevel 1 set READY=1
    timeout /t 2 /nobreak >nul
  )
)

REM ---------- 6. 访问方式 ----------
echo.
echo ============================================================
echo   启动完成！
echo.
echo   本机访问（推荐先在本机打开）：
echo     登录页    http://127.0.0.1:%COMPOSE_HOST_PORT%/login
echo     调度端    http://127.0.0.1:%COMPOSE_HOST_PORT%/dispatcher
echo     乘客端    http://127.0.0.1:%COMPOSE_HOST_PORT%/rider   （免登录）
echo.
echo   同一 WiFi 下手机/他人访问：
echo     http://本机局域网IP:%COMPOSE_HOST_PORT%/login
echo     （局域网IP 查看：命令行运行 ipconfig，找 IPv4 地址）
echo.
echo   登录方式：登录页已开启"演示账号一键登录"，
echo             点任一司机或调度员按钮即可进入，无需输入。
echo.
echo   停止服务：双击 stop.bat
echo ============================================================
echo.

start "" "http://127.0.0.1:%COMPOSE_HOST_PORT%/login"
pause
