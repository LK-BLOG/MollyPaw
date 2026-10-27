@echo off
setlocal
echo ====================================
echo  MollyPaw Builder - Beta 0.0.0.2.1
echo ====================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+
    goto fail
)

REM Local build uses .venv. In CI the runner's python already has everything,
REM so skip the venv (creating one would just waste a minute).
set "PY=python"
if defined CI goto deps
if not exist .venv\Scripts\python.exe python -m venv .venv
set "PY=.venv\Scripts\python.exe"

:deps
echo [1/3] Installing dependencies...
if defined CI goto deps_skipped
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    goto fail
)
goto deps_done
:deps_skipped
echo       skipped (CI mode: the workflow already installed them)
:deps_done

echo.
echo [2/3] Building executable with PyInstaller...
%PY% -m PyInstaller ^
    --name MollyPaw ^
    --onefile ^
    --windowed ^
    --noconfirm ^
    --clean ^
    --icon "assets\logo.ico" ^
    --add-data "frontend;frontend" ^
    --add-data "assets;assets" ^
    --add-data "agent;agent" ^
    --add-data "pet.py;." ^
    --exclude-module PyQt5 ^
    --exclude-module PySide6 ^
    --exclude-module aiohttp ^
    --exclude-module torch ^
    --exclude-module transformers ^
    --hidden-import pystray ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    main.py
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed
    goto fail
)

echo.
echo [3/3] Copying config files to dist...
copy /Y LICENSE dist\LICENSE >nul 2>&1
copy /Y README.md dist\README.md >nul 2>&1
copy /Y BRAND.md dist\BRAND.md >nul 2>&1
copy /Y CONTRIBUTING.md dist\CONTRIBUTING.md >nul 2>&1
copy /Y requirements.txt dist\requirements.txt >nul 2>&1
REM 以前这里还会生成 dist\config\default.json，内容是写死的
REM {"sleep":{"idle_minutes":0.5,"max_llm_calls":100}}。
REM 两个问题：一是**没有任何代码读它**（真实配置在 %APPDATA%\MollyPaw\config.json），
REM 二是它带着早就删掉的字段，会让人以为那些配置还在。直接不生成。

echo.
echo ====================================
echo  Build complete!
echo  Output: dist\MollyPaw.exe
echo ====================================
if not defined CI pause
exit /b 0

:fail
if not defined CI pause
exit /b 1
