from __future__ import annotations
import ctypes, os, shutil, subprocess, threading, time, webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import privacy_patch as privacy

_MUTEX=None; _LOCKFD=None; _BROWSER=None; _APP=None; _ORIG_POST=None; _CLOSE_AT=0.0; _LOCK=threading.RLock()

def cancel(app:Any)->None:
    try:
        with app.STATE.lock:
            if app.STATE.status not in {'starting','downloading','converting','cancelling'}:return
            app.STATE.cancel_requested=True; app.STATE.status='cancelling'; app.STATE.message='Cerrando...'; p=app.STATE.ffmpeg_process
        if p and p.poll() is None:p.terminate()
    except Exception:pass

def acquire()->bool:
    global _MUTEX,_LOCKFD
    privacy.STATE_ROOT.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        k=ctypes.WinDLL('kernel32',use_last_error=True); k.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]; k.CreateMutexW.restype=ctypes.c_void_p
        h=k.CreateMutexW(None,False,'Local\\Soundwav-v14-single-instance')
        if not h:raise OSError(ctypes.get_last_error(),'No se pudo crear bloqueo de instancia')
        if ctypes.get_last_error()==183:k.CloseHandle(ctypes.c_void_p(h));return False
        _MUTEX=h;return True
    p=privacy.STATE_ROOT/'soundwav-v14.lock'
    try:_LOCKFD=os.open(p,os.O_CREAT|os.O_EXCL|os.O_RDWR);return True
    except FileExistsError:return False

def release()->None:
    global _MUTEX,_LOCKFD
    if os.name=='nt' and _MUTEX:
        try:ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(_MUTEX))
        except Exception:pass
        _MUTEX=None
    if _LOCKFD is not None:
        try:os.close(_LOCKFD)
        except OSError:pass
        _LOCKFD=None
        try:(privacy.STATE_ROOT/'soundwav-v14.lock').unlink(missing_ok=True)
        except OSError:pass

def browsers()->list[Path]:
    out=[]
    for key in ('PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA'):
        if not os.environ.get(key):continue
        r=Path(os.environ[key]);out += [r/'Microsoft/Edge/Application/msedge.exe',r/'Google/Chrome/Application/chrome.exe']
    return out

def launch(url:str)->subprocess.Popen[Any]|None:
    if os.name!='nt':webbrowser.open(url,new=1);return None
    exe=next((p for p in browsers() if p.exists()),None)
    if exe is None:webbrowser.open(url,new=1);return None
    profile=privacy.STATE_ROOT/'ui-profile-v14';profile.mkdir(parents=True,exist_ok=True)
    return subprocess.Popen([str(exe),f'--app={url}',f'--user-data-dir={profile}','--no-first-run','--no-default-browser-check'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def browser_watch(server:Any,p:subprocess.Popen[Any])->None:
    try:p.wait()
    finally:
        if _APP is not None:cancel(_APP)
        try:server.shutdown()
        except Exception:pass

def close_watch(server:Any)->None:
    while True:
        time.sleep(.5)
        with _LOCK:t=_CLOSE_AT
        if t and time.monotonic()>=t:
            try:server.shutdown()
            except Exception:pass
            return

def apply(app:Any)->None:
    global _APP,_ORIG_POST
    _APP=app; _ORIG_POST=app.RequestHandler.do_POST
    def post(self):
        global _CLOSE_AT
        path=urlparse(self.path).path
        if path=='/api/heartbeat':
            with _LOCK:_CLOSE_AT=0.0
            return self.send_json({'ok':True})
        if path=='/api/ui-closed':
            cancel(app)
            with _LOCK:_CLOSE_AT=time.monotonic()+3
            return self.send_json({'ok':True})
        return _ORIG_POST(self)
    app.RequestHandler.do_POST=post
    heartbeat="\nlet swHeartbeat=setInterval(()=>api('/api/heartbeat',{method:'POST'}).catch(()=>{}),2000);window.addEventListener('pagehide',()=>{try{fetch('/api/ui-closed',{method:'POST',headers:{'X-Soundwav-Token':SOUNDWAV_TOKEN},keepalive:true})}catch(e){}});"
    app.HTML=app.HTML.replace('setInterval(refresh,800);refresh();','setInterval(refresh,800);refresh();'+heartbeat)

def run(app:Any)->None:
    global _BROWSER
    if not acquire():print('Soundwav ya está abierto. No se creó una segunda ventana.');return
    temp=privacy.STATE_ROOT/'temp'
    if temp.exists():
        for p in temp.glob('session-*'):
            if p!=privacy.SESSION_TEMP_ROOT:shutil.rmtree(p,ignore_errors=True)
    app.DOWNLOAD_ROOT.mkdir(parents=True,exist_ok=True);server=app.create_server();port=int(server.server_address[1]);url=f'http://{app.HOST}:{port}'
    print(f'Soundwav v1.4 - {url}')
    try:
        _BROWSER=launch(url);threading.Thread(target=close_watch,args=(server,),daemon=True).start()
        if _BROWSER is not None:threading.Thread(target=browser_watch,args=(server,_BROWSER),daemon=True).start()
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        cancel(app)
        try:server.server_close()
        except Exception:pass
        if _BROWSER is not None and _BROWSER.poll() is None:
            try:_BROWSER.terminate();_BROWSER.wait(timeout=3)
            except Exception:
                try:_BROWSER.kill()
                except Exception:pass
        _BROWSER=None;release()
