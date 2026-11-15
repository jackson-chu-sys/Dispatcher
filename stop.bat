@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在停止 Dispatcher...
docker compose down
echo.
echo 已停止。数据仍保留在 .\data 目录，下次双击 start.bat 会接着用。
echo.
pause
