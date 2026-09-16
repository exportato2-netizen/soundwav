from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import privacy_patch as privacy

_MUTEX = None
_LOCKFD = None
_JOB = None
_BROWSER = None
_APP = None
_ORIG_POST = None
_CLOSE_AT = 0.0
_LOCK = threading.RLock()


def cancel(app: Any) -> None:
    try:
        with app.STATE.lock:
            if app.STATE.status not in {"starting", "downloading", "converting", "cancelling"}:
                return
            app.STATE.cancel_requested = True
            app.STATE.status = "cancelling"
            app.STATE.message = "Cerrando..."
            process = app.STATE.ffmpeg_process
        if process and process.poll() is None:
            process.terminate()
    except Exception:
        pass


def acquire() -> bool:
    global _MUTEX, _LOCKFD
    privacy.STATE_ROOT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        handle = kernel32.CreateMutexW(None, False, "Local\\Soundwav-single-instance")
        if not handle:
            raise OSError(ctypes.get_last_error(), "No se pudo crear bloqueo de instancia")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        _MUTEX = handle
        return True

    lock_path = privacy.STATE_ROOT / "soundwav.lock"
    try:
        _LOCKFD = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        return True
    except FileExistsError:
        return False


def release() -> None:
    global _MUTEX, _LOCKFD, _JOB
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        if _JOB:
            try:
                kernel32.CloseHandle(ctypes.c_void_p(_JOB))
            except Exception:
                pass
            _JOB = None
        if _MUTEX:
            try:
                kernel32.CloseHandle(ctypes.c_void_p(_MUTEX))
            except Exception:
                pass
            _MUTEX = None

    if _LOCKFD is not None:
        try:
            os.close(_LOCKFD)
        except OSError:
            pass
        _LOCKFD = None
        try:
            (privacy.STATE_ROOT / "soundwav.lock").unlink(missing_ok=True)
        except OSError:
            pass


def browsers() -> list[Path]:
    found: list[Path] = []
    for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(key)
        if not base:
            continue
        root = Path(base)
        found.extend(
            [
                root / "Microsoft/Edge/Application/msedge.exe",
                root / "Google/Chrome/Application/chrome.exe",
            ]
        )
    return found


def attach_job(process: subprocess.Popen[Any]) -> None:
    """Hace que Windows cierre la ventana web si termina Soundwav."""
    global _JOB
    if os.name != "nt" or not hasattr(process, "_handle"):
        return

    import ctypes.wintypes as wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return

    info = ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok_limits = kernel32.SetInformationJobObject(
        ctypes.c_void_p(job), 9, ctypes.byref(info), ctypes.sizeof(info)
    )
    ok_assign = False
    if ok_limits:
        ok_assign = bool(
            kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(job), ctypes.c_void_p(int(process._handle))
            )
        )
    if not ok_limits or not ok_assign:
        kernel32.CloseHandle(ctypes.c_void_p(job))
        return
    _JOB = job


def launch(url: str) -> subprocess.Popen[Any] | None:
    if os.name != "nt":
        webbrowser.open(url, new=1)
        return None

    executable = next((candidate for candidate in browsers() if candidate.exists()), None)
    if executable is None:
        webbrowser.open(url, new=1)
        return None

    profile = privacy.STATE_ROOT / "ui-profile"
    profile.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [
            str(executable),
            f"--app={url}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    attach_job(process)
    return process


def browser_watch(server: Any, process: subprocess.Popen[Any]) -> None:
    try:
        process.wait()
    finally:
        if _APP is not None:
            cancel(_APP)
        try:
            server.shutdown()
        except Exception:
            pass


def close_watch(server: Any) -> None:
    while True:
        time.sleep(0.5)
        with _LOCK:
            deadline = _CLOSE_AT
        if deadline and time.monotonic() >= deadline:
            if _APP is not None:
                cancel(_APP)
            try:
                server.shutdown()
            except Exception:
                pass
            return


def apply(app: Any) -> None:
    global _APP, _ORIG_POST
    _APP = app
    _ORIG_POST = app.RequestHandler.do_POST

    def post(self: Any) -> None:
        global _CLOSE_AT
        path = urlparse(self.path).path
        if path == "/api/heartbeat":
            # Una recarga genera pagehide, pero la nueva página vuelve a enviar
            # heartbeat antes de vencer la gracia, evitando un cierre accidental.
            with _LOCK:
                _CLOSE_AT = 0.0
            self.send_json({"ok": True})
            return
        if path == "/api/ui-closed":
            with _LOCK:
                _CLOSE_AT = time.monotonic() + 4.0
            self.send_json({"ok": True})
            return
        _ORIG_POST(self)

    app.RequestHandler.do_POST = post
    heartbeat = """
let swHeartbeat=setInterval(()=>api('/api/heartbeat',{method:'POST'}).catch(()=>{}),1500);
window.addEventListener('pagehide',()=>{
  try{fetch('/api/ui-closed',{method:'POST',headers:{'X-Soundwav-Token':SOUNDWAV_TOKEN},keepalive:true})}catch(e){}
});
"""
    marker = "setInterval(refresh,800);refresh();"
    if marker not in app.HTML:
        raise RuntimeError("No se pudo instalar el control de cierre de la interfaz")
    app.HTML = app.HTML.replace(marker, marker + heartbeat, 1)


def run(app: Any) -> None:
    global _BROWSER
    if not acquire():
        print("Soundwav ya está abierto. Se mantiene la única ventana existente.")
        return

    temp_root = privacy.STATE_ROOT / "temp"
    if temp_root.exists():
        for path in temp_root.glob("session-*"):
            if path != privacy.SESSION_TEMP_ROOT:
                shutil.rmtree(path, ignore_errors=True)

    app.DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    server = app.create_server()
    port = int(server.server_address[1])
    url = f"http://{app.HOST}:{port}"
    print(f"Soundwav v1.4 - {url}")

    try:
        _BROWSER = launch(url)
        threading.Thread(target=close_watch, args=(server,), daemon=True).start()
        if _BROWSER is not None:
            threading.Thread(target=browser_watch, args=(server, _BROWSER), daemon=True).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cancel(app)
        try:
            server.server_close()
        except Exception:
            pass
        if _BROWSER is not None and _BROWSER.poll() is None:
            try:
                _BROWSER.terminate()
                _BROWSER.wait(timeout=3)
            except Exception:
                try:
                    _BROWSER.kill()
                except Exception:
                    pass
        _BROWSER = None
        release()
