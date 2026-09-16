@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Actualizar componentes - Soundwav

if not exist "launcher.bat" (
    echo [ERROR] Falta launcher.bat en esta carpeta.
    pause
    exit /b 1
)
if not exist "requirements.txt" (
    echo [ERROR] Falta requirements.txt en esta carpeta.
    pause
    exit /b 1
)

echo Comprobando y reparando el entorno local...
call launcher.bat --setup-only
if errorlevel 1 goto :error

echo.
echo Actualizando pip, yt-dlp e ImageIO-FFmpeg...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Actualizacion completada correctamente.
".venv\Scripts\python.exe" -c "import yt_dlp, imageio_ffmpeg; print('yt-dlp:', yt_dlp.version.__version__); print('FFmpeg:', imageio_ffmpeg.get_ffmpeg_version())"
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] No se pudo preparar o actualizar la aplicacion.
echo Comprueba tu conexion a Internet y vuelve a intentarlo.
echo.
pause
exit /b 1
