@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Actualizar componentes - SoundCloud a WAV

if not exist ".venv\Scripts\python.exe" (
    echo No existe el entorno local. Ejecutando launcher.bat para prepararlo...
    echo.
    call launcher.bat
    exit /b %errorlevel%
)

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
echo [ERROR] No se pudo actualizar. Comprueba tu conexion a Internet.
echo.
pause
exit /b 1
