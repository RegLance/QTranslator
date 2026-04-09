@echo off
chcp 65001 >nul
title QTranslator 打包工具

echo ========================================
echo   QTranslator 一键打包工具
echo ========================================
echo.

echo 正在启动打包，请稍候...
echo.

cd /d "%~dp0"

REM 检查虚拟环境
if not exist ".venv\Scripts\python.exe" (
    echo 错误: 虚拟环境不存在，请先运行 pip install -r requirements.txt
    pause
    exit /b 1
)

REM 运行打包脚本
.venv\Scripts\python.exe build.py

echo.
echo ========================================
echo   打包完成!
echo ========================================
echo 输出文件: dist\QTranslator.exe
echo.

pause