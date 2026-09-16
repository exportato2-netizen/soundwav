@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Soundwav

set "SETUP_ONLY=0"
if /I "%~1"=="--setup-only" set "SETUP_ONLY=1"

cls
echo.
echo ============================================================
echo   Soundwav - Inicio automatico
echo ============================================================
echo.

if not exist "app.py" (
    echo [ERROR] Falta app.py en esta carpeta.
    pause
    exit /b 1
)
if not exist "requirements.txt" (
    echo [ERROR] Falta requirements.txt en esta carpeta.
    pause
    exit /b 1
)

set "PY_CMD="
set "PY_VERSION=3.14.7"
set "MIN_PY=3.11"
set "NEW_VENV=0"

call :detect_python
if defined PY_CMD goto :python_ready

echo [1/4] No se encontro Python %MIN_PY% o superior.
echo       Intentando instalar Python automaticamente...
echo.
call :install_python
if errorlevel 1 goto :python_install_error

call :detect_python
if not defined PY_CMD goto :python_install_error

echo.
echo Python instalado correctamente.
echo.

:python_ready
echo [1/4] Python compatible detectado.
!PY_CMD! --version

if not exist ".venv\Scripts\python.exe" (
    echo [2/4] Creando entorno local...
    !PY_CMD! -m venv .venv
    if errorlevel 1 goto :error
    set "NEW_VENV=1"
) else (
    echo [2/4] Entorno local ya existente.
)

rem Si el entorno quedo ligado a un Python eliminado o incompatible, recrearlo.
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo       El entorno local es antiguo o esta danado. Recreando...
    rmdir /s /q ".venv" >nul 2>&1
    !PY_CMD! -m venv .venv
    if errorlevel 1 goto :error
    set "NEW_VENV=1"
)

if "!NEW_VENV!"=="1" (
    echo [3/4] Instalando componentes por primera vez...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
    if errorlevel 1 goto :error
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto :error
) else (
    ".venv\Scripts\python.exe" -c "import yt_dlp, imageio_ffmpeg" >nul 2>&1
    if errorlevel 1 (
        echo [3/4] Faltan componentes. Reparando instalacion...
        ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
        if errorlevel 1 goto :error
    ) else (
        echo [3/4] Componentes listos. No se actualizan automaticamente.
    )
)

if "!SETUP_ONLY!"=="1" (
    echo.
    echo Preparacion completada.
    exit /b 0
)

echo.
echo [4/4] Abriendo la aplicacion...
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto :error
exit /b 0

:detect_python
set "PY_CMD="

where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=py -3"
        exit /b 0
    )
)

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=python"
        exit /b 0
    )
)

where python3 >nul 2>&1
if not errorlevel 1 (
    python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY_CMD=python3"
        exit /b 0
    )
)

for %%P in (
    "%LocalAppData%\Programs\Python\Python314\python.exe"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python314\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
) do (
    if exist "%%~P" (
        "%%~P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PY_CMD="%%~P""
            exit /b 0
        )
    )
)

exit /b 1

:install_python
rem Metodo 1: WinGet. Instala la rama 3.14 actual disponible.
where winget >nul 2>&1
if not errorlevel 1 (
    echo Intentando instalar Python 3.14 con WinGet...
    winget install --id Python.Python.3.14 -e --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
    if not errorlevel 1 exit /b 0
    echo.
    echo WinGet no pudo completar la instalacion. Probando instalador oficial...
    echo.
)

rem Metodo 2: instalador oficial de respaldo.
where powershell >nul 2>&1
if errorlevel 1 exit /b 1

set "PY_ARCH=amd64"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PY_ARCH=arm64"
if /I "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "PY_ARCH=arm64"

set "PY_FILE=python-%PY_VERSION%-%PY_ARCH%.exe"
set "PY_INSTALLER=%TEMP%\%PY_FILE%"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/%PY_FILE%"

echo Descargando Python %PY_VERSION% desde python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing '%PY_URL%' -OutFile '%PY_INSTALLER%'; if ((Get-Item '%PY_INSTALLER%').Length -lt 10000000) { throw 'El instalador descargado parece incompleto' }; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
if errorlevel 1 exit /b 1
if not exist "%PY_INSTALLER%" exit /b 1

echo Instalando Python %PY_VERSION% para el usuario actual...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 Shortcuts=0
set "INSTALL_RESULT=!errorlevel!"
del /q "%PY_INSTALLER%" >nul 2>&1
if not "!INSTALL_RESULT!"=="0" exit /b !INSTALL_RESULT!
exit /b 0

:python_install_error
echo.
echo [ERROR] No se pudo instalar automaticamente Python %MIN_PY% o superior.
echo.
echo Comprueba la conexion a Internet y que Windows permita ejecutar
 echo WinGet o PowerShell. Luego vuelve a ejecutar launcher.bat.
echo.
pause
exit /b 1

:error
echo.
echo [ERROR] No se pudo iniciar la aplicacion.
echo Revisa el mensaje anterior. Si falta algun componente, ejecuta ACTUALIZAR.bat.
echo.
pause
exit /b 1
