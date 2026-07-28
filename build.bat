@echo off
echo ====================================
echo  MollyPaw Builder - Beta 0.0.0.1
echo ====================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.9+
    pause
    exit /b 1
)

REM Install dependencies
echo [1/3] Installing dependencies...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [2/3] Building executable with PyInstaller...
pyinstaller ^
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
    --hidden-import pystray ^
    --hidden-import PIL ^
    --hidden-import PIL._tkinter_finder ^
    main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed
    pause
    exit /b 1
)

echo.
echo [3/3] Copying config files to dist...
copy /Y LICENSE dist\LICENSE >nul 2>&1
copy /Y README.md dist\README.md >nul 2>&1
copy /Y BRAND.md dist\BRAND.md >nul 2>&1
copy /Y CONTRIBUTING.md dist\CONTRIBUTING.md >nul 2>&1
copy /Y requirements.txt dist\requirements.txt >nul 2>&1
mkdir dist\config >nul 2>&1
echo {} > dist\config\default.json

echo.
echo ====================================
echo  Build complete!
echo  Output: dist\MollyPaw.exe
echo ====================================
pause
