#!/usr/bin/env python3
"""Interfaz local para descargar playlists públicas de SoundCloud y convertirlas a WAV."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import imageio_ffmpeg
    import yt_dlp
    from yt_dlp.postprocessor.common import PostProcessor
except ImportError as exc:
    print(f"Falta una dependencia: {exc}")
    print("Ejecuta launcher.bat para instalar todo automáticamente.")
    input("Presiona Enter para cerrar...")
    raise SystemExit(1)

APP_NAME = "SoundCloud Playlist a WAV"
APP_VERSION = "1.1"
HOST = "127.0.0.1"
PREFERRED_PORT = 8765
DOWNLOAD_ROOT = Path.home() / "Music" / "SoundCloud_WAV"
ARCHIVE_FILE = DOWNLOAD_ROOT / ".descargados.txt"
LOG_FILE = DOWNLOAD_ROOT / "actividad.log"


def safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).replace("\x00", "").strip() or fallback


def soundcloud_url_is_allowed(raw_url: str) -> bool:
    try:
        parsed = urlparse(raw_url.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return (
        host == "soundcloud.com"
        or host.endswith(".soundcloud.com")
        or host == "snd.sc"
        or host == "on.soundcloud.com"
        or host == "soundcloud.app.goo.gl"
    )


@dataclass
class JobState:
    status: str = "idle"
    message: str = "Listo para comenzar"
    percent: float = 0.0
    current_title: str = ""
    speed: str = ""
    eta: str = ""
    completed: int = 0
    failed: int = 0
    had_download_errors: bool = False
    total: int | None = None
    logs: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    ffmpeg_process: subprocess.Popen[str] | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def reset(self) -> None:
        with self.lock:
            self.status = "starting"
            self.message = "Preparando descarga..."
            self.percent = 0.0
            self.current_title = ""
            self.speed = ""
            self.eta = ""
            self.completed = 0
            self.failed = 0
            self.had_download_errors = False
            self.total = None
            self.logs = []
            self.cancel_requested = False
            self.started_at = time.time()
            self.finished_at = None
            self.ffmpeg_process = None

    def log(self, text: str) -> None:
        text = safe_text(text)
        if not text:
            return
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {text}"
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-300:]
        try:
            DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d')} {line}\n")
        except OSError:
            pass

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": self.status,
                "message": self.message,
                "percent": round(self.percent, 2),
                "current_title": self.current_title,
                "speed": self.speed,
                "eta": self.eta,
                "completed": self.completed,
                "failed": self.failed,
                "had_download_errors": self.had_download_errors,
                "total": self.total,
                "logs": list(self.logs),
                "download_dir": str(DOWNLOAD_ROOT),
                "running": self.status in {"starting", "downloading", "converting", "cancelling"},
            }


STATE = JobState()


class UILogger:
    def debug(self, message: str) -> None:
        # yt-dlp usa debug también para información normal con prefijo [download].
        if message.startswith("[debug]"):
            return
        STATE.log(message)

    def info(self, message: str) -> None:
        STATE.log(message)

    def warning(self, message: str) -> None:
        STATE.log(f"Aviso: {message}")

    def error(self, message: str) -> None:
        with STATE.lock:
            STATE.had_download_errors = True
        STATE.log(f"Error: {message}")


def parse_percent(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value)))
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", safe_text(value))
    return max(0.0, min(100.0, float(match.group(1)))) if match else 0.0


def metadata_args(info: dict[str, Any]) -> list[str]:
    title = safe_text(info.get("title"), "Sin título")
    artist = safe_text(info.get("artist") or info.get("uploader") or info.get("creator"), "")
    album = safe_text(info.get("playlist_title") or info.get("album"), "SoundCloud")
    track = info.get("playlist_index") or info.get("track_number")
    args = ["-metadata", f"title={title}", "-metadata", f"album={album}"]
    if artist:
        args.extend(["-metadata", f"artist={artist}"])
    if track:
        args.extend(["-metadata", f"track={track}"])
    return args


def convert_to_wav(source: Path, info: dict[str, Any], bit_depth: int, keep_original: bool) -> Path:
    if STATE.cancel_requested:
        raise RuntimeError("Descarga cancelada")

    destination = source.with_suffix(".wav")
    if source.suffix.lower() == ".wav":
        STATE.log(f"Ya está en WAV: {source.name}")
        return source

    codec = "pcm_s24le" if bit_depth == 24 else "pcm_s16le"
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    with STATE.lock:
        STATE.status = "converting"
        STATE.message = f"Convirtiendo a WAV {bit_depth} bits..."
        STATE.current_title = safe_text(info.get("title"), source.stem)

    STATE.log(f"Convirtiendo: {source.name} → {destination.name}")

    command = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-map_metadata",
        "0",
        "-c:a",
        codec,
        *metadata_args(info),
        str(destination),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    with STATE.lock:
        STATE.ffmpeg_process = process

    while process.poll() is None:
        if STATE.cancel_requested:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            destination.unlink(missing_ok=True)
            raise RuntimeError("Descarga cancelada")
        time.sleep(0.2)

    _, stderr = process.communicate()
    with STATE.lock:
        STATE.ffmpeg_process = None

    if process.returncode != 0 or not destination.exists():
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg no pudo convertir {source.name}: {safe_text(stderr, 'error desconocido')}")

    STATE.log(f"WAV terminado: {destination.name}")
    return destination


class WavPostProcessor(PostProcessor):
    """Convierte cada pista descargada antes de que yt-dlp la archive como completada."""

    def __init__(self, downloader: Any, bit_depth: int, keep_original: bool) -> None:
        super().__init__(downloader)
        self.bit_depth = bit_depth
        self.keep_original = keep_original

    def run(self, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        source_name = safe_text(info.get("filepath") or info.get("_filename"))
        if not source_name:
            source_name = safe_text(self._downloader.prepare_filename(info))
        source = Path(source_name)

        try:
            destination = convert_to_wav(source, info, self.bit_depth, self.keep_original)
        except Exception as exc:
            if STATE.cancel_requested:
                raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario") from exc
            with STATE.lock:
                STATE.failed += 1
            raise yt_dlp.utils.PostProcessingError(str(exc)) from exc

        with STATE.lock:
            STATE.completed += 1
            STATE.percent = 100.0
            STATE.status = "downloading"
            STATE.message = "Continuando con la playlist..."

        info["filepath"] = str(destination)
        info["_filename"] = str(destination)
        info["ext"] = "wav"
        files_to_delete: list[str] = []
        if not self.keep_original and source != destination:
            files_to_delete.append(str(source))
        return files_to_delete, info


def run_download(url: str, bit_depth: int, keep_original: bool, force_redownload: bool) -> None:
    STATE.reset()
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    def progress_hook(data: dict[str, Any]) -> None:
        if STATE.cancel_requested:
            raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")

        status = data.get("status")
        info = data.get("info_dict") or {}
        title = safe_text(info.get("title"), "Procesando pista")

        if status == "downloading":
            with STATE.lock:
                STATE.status = "downloading"
                STATE.message = "Descargando el mejor audio disponible..."
                STATE.current_title = title
                STATE.percent = parse_percent(data.get("_percent_str"))
                STATE.speed = safe_text(data.get("_speed_str"))
                STATE.eta = safe_text(data.get("_eta_str"))
                playlist_count = info.get("playlist_count") or info.get("n_entries")
                if isinstance(playlist_count, int):
                    STATE.total = playlist_count

        elif status == "finished":
            details = []
            if fmt := safe_text(info.get("format_id")):
                details.append(fmt)
            if ext := safe_text(info.get("ext")):
                details.append(ext.upper())
            if codec := safe_text(info.get("acodec")):
                details.append(codec)
            if info.get("abr"):
                details.append(f"{info.get('abr')} kb/s")
            if info.get("asr"):
                details.append(f"{info.get('asr')} Hz")
            if details:
                STATE.log("Fuente seleccionada: " + " · ".join(details))
            with STATE.lock:
                STATE.status = "converting"
                STATE.message = "Audio descargado; preparando WAV..."
                STATE.current_title = title
                STATE.percent = 100.0

    output_template = str(
        DOWNLOAD_ROOT
        / "%(playlist_title,album,uploader|SoundCloud)s"
        / "%(playlist_index|0)03d - %(title)s [%(id)s].%(ext)s"
    )

    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "yesplaylist": True,
        "noplaylist": False,
        "ignoreerrors": True,
        "continuedl": True,
        "overwrites": bool(force_redownload),
        "windowsfilenames": True,
        "trim_file_name": 140,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 5,
        "sleep_interval_requests": 0.75,
        "concurrent_fragment_downloads": 1,
        "progress_hooks": [progress_hook],
        "logger": UILogger(),
        "quiet": False,
        "no_warnings": False,
        "noprogress": True,
        "restrictfilenames": False,
        "writethumbnail": False,
        "postprocessors": [],
    }
    if not force_redownload:
        options["download_archive"] = str(ARCHIVE_FILE)

    STATE.log("Analizando la URL de SoundCloud...")
    STATE.log(f"Carpeta de salida: {DOWNLOAD_ROOT}")
    STATE.log(f"Formato final: WAV PCM {bit_depth} bits")
    try:
        free_gb = shutil.disk_usage(DOWNLOAD_ROOT).free / (1024 ** 3)
        STATE.log(f"Espacio libre: {free_gb:.1f} GB")
    except OSError:
        pass

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.add_post_processor(
                WavPostProcessor(downloader, bit_depth, keep_original),
                when="post_process",
            )
            result = downloader.download([url])

        if STATE.cancel_requested:
            with STATE.lock:
                STATE.status = "cancelled"
                STATE.message = "Descarga cancelada"
        elif (result not in (0, None) or STATE.had_download_errors) and STATE.completed == 0:
            with STATE.lock:
                STATE.status = "error"
                STATE.message = "No se pudo completar ninguna pista; revisa el registro"
            STATE.log(STATE.message)
        else:
            with STATE.lock:
                STATE.status = "completed"
                STATE.percent = 100.0
                if STATE.failed:
                    STATE.message = f"Finalizado: {STATE.completed} pistas, {STATE.failed} con error de conversión"
                elif STATE.had_download_errors or result not in (0, None):
                    STATE.message = f"Finalizado: {STATE.completed} pistas; hubo errores en algunas descargas"
                elif STATE.completed:
                    STATE.message = f"Playlist terminada: {STATE.completed} pistas WAV"
                else:
                    STATE.message = "No había pistas nuevas para descargar"
            STATE.log(STATE.message)

    except yt_dlp.utils.DownloadCancelled:
        with STATE.lock:
            STATE.status = "cancelled"
            STATE.message = "Descarga cancelada"
        STATE.log("Descarga cancelada por el usuario")
    except Exception as exc:
        if STATE.cancel_requested:
            with STATE.lock:
                STATE.status = "cancelled"
                STATE.message = "Descarga cancelada"
        else:
            with STATE.lock:
                STATE.status = "error"
                STATE.message = safe_text(exc, "Error inesperado")
            STATE.log(f"Error inesperado: {exc}")
            STATE.log(traceback.format_exc())
    finally:
        with STATE.lock:
            STATE.finished_at = time.time()
            STATE.ffmpeg_process = None


def open_download_folder() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(DOWNLOAD_ROOT)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(DOWNLOAD_ROOT)])
    else:
        subprocess.Popen(["xdg-open", str(DOWNLOAD_ROOT)])


HTML = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SoundCloud Playlist a WAV</title>
<style>
:root{color-scheme:dark;--bg:#0b0b12;--card:#171721;--soft:#232334;--accent:#ff5500;--text:#f5f5f7;--muted:#aaaabd;--ok:#46d17d;--danger:#ff5a6f}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:radial-gradient(circle at top,#28203a 0,#0b0b12 42%);color:var(--text);min-height:100vh;padding:34px 18px}
main{max-width:840px;margin:auto}.brand{display:flex;gap:16px;align-items:center;margin-bottom:22px}.logo{width:58px;height:58px;border-radius:18px;background:linear-gradient(145deg,#ff8a00,#ff3500);display:grid;place-items:center;font-size:31px;box-shadow:0 12px 35px #ff550044}h1{font-size:clamp(27px,5vw,42px);margin:0}p{color:var(--muted);line-height:1.55}.card{background:#171721e8;border:1px solid #ffffff14;border-radius:22px;padding:24px;box-shadow:0 24px 70px #0008;backdrop-filter:blur(16px)}label{display:block;font-weight:700;margin:0 0 9px}.urlrow{display:flex;gap:10px}.urlrow input{flex:1}input,select{width:100%;border:1px solid #ffffff1a;background:#0f0f17;color:var(--text);border-radius:12px;padding:14px;font-size:16px;outline:none}input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px #ff550025}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:17px}.check{display:flex;align-items:center;gap:9px;font-weight:500;color:var(--muted);margin-top:15px}.check input{width:18px;height:18px;accent-color:var(--accent)}button{border:0;border-radius:12px;padding:13px 18px;font-weight:800;font-size:15px;cursor:pointer;transition:.18s transform,.18s opacity;background:var(--soft);color:var(--text)}button:hover{transform:translateY(-1px)}button:disabled{opacity:.45;cursor:not-allowed;transform:none}.primary{background:linear-gradient(135deg,#ff7b00,#ff3d00);margin-top:20px;width:100%;font-size:17px;padding:15px}.danger{background:#3a1920;color:#ff9baa}.toolbar{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}.status{margin-top:20px;border-top:1px solid #ffffff12;padding-top:20px}.statushead{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.statusname{font-size:19px;font-weight:800}.pill{font-size:12px;font-weight:800;text-transform:uppercase;background:var(--soft);padding:7px 10px;border-radius:999px;color:var(--muted)}.bar{height:11px;border-radius:99px;background:#09090e;overflow:hidden;margin:15px 0}.bar>div{height:100%;width:0;background:linear-gradient(90deg,#ff8b00,#ff3d00);transition:width .25s}.stats{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:14px}.current{margin:12px 0 0;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.log{margin-top:17px;height:220px;overflow:auto;background:#09090f;border:1px solid #ffffff0e;border-radius:12px;padding:13px;font:12px/1.55 Consolas,monospace;color:#c8c8d5;white-space:pre-wrap}.note{font-size:13px;margin:16px 2px 0}.hidden{display:none}@media(max-width:650px){.grid{grid-template-columns:1fr}.urlrow{display:block}.card{padding:18px}}
</style>
</head>
<body><main>
<div class="brand"><div class="logo">☁</div><div><h1>SoundCloud → WAV</h1><p style="margin:4px 0 0">Playlists completas · selecciona automáticamente la mejor fuente disponible</p></div></div>
<div class="card">
<label for="url">URL de playlist o pista pública</label>
<div class="urlrow"><input id="url" type="url" placeholder="https://soundcloud.com/.../sets/..." autocomplete="off"><button id="paste">Pegar</button></div>
<div class="grid"><div><label for="depth">Formato WAV de salida</label><select id="depth"><option value="24" selected>PCM 24 bits — más margen, archivo mayor</option><option value="16">PCM 16 bits — menor tamaño y muy compatible</option></select></div><div><label>Carpeta de salida</label><input id="folder" readonly></div></div>
<label class="check"><input id="keep" type="checkbox">Conservar también el archivo fuente descargado</label>
<label class="check"><input id="force" type="checkbox">Ignorar historial y volver a descargar todo</label>
<button class="primary" id="start">Descargar playlist</button>
<div class="toolbar"><button id="open">Abrir carpeta</button><button id="copylog">Copiar registro</button><button class="danger hidden" id="cancel">Cancelar descarga</button><button id="close">Cerrar aplicación</button></div>
<section class="status">
<div class="statushead"><div><div class="statusname" id="message">Listo para comenzar</div><div class="current" id="current"></div></div><span class="pill" id="state">idle</span></div>
<div class="bar"><div id="progress"></div></div>
<div class="stats"><span id="percent">0%</span><span id="count">0 pistas</span><span id="speed"></span><span id="eta"></span></div>
<div class="log" id="log">La actividad aparecerá aquí.</div>
</section>
<p class="note">La salida WAV evita una nueva compresión con pérdida. Elegir 24 bits no recupera detalle que la fuente de SoundCloud ya haya perdido. El registro completo también queda guardado en la carpeta de descargas.</p>
</div></main>
<script>
const $=id=>document.getElementById(id);let running=false;
async function api(path,options={}){const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw new Error(data.error||'Error');return data}
$('paste').onclick=async()=>{try{$('url').value=await navigator.clipboard.readText()}catch{$('url').focus()}};
$('open').onclick=()=>api('/api/open',{method:'POST'}).catch(e=>alert(e.message));
$('copylog').onclick=async()=>{try{await navigator.clipboard.writeText($('log').textContent||'');$('copylog').textContent='Copiado';setTimeout(()=>$('copylog').textContent='Copiar registro',1200)}catch{alert('No se pudo copiar el registro.')}};
$('close').onclick=async()=>{if(running)return alert('Cancela o espera a que termine la descarga antes de cerrar.');try{await api('/api/shutdown',{method:'POST'});document.body.innerHTML='<main><div class="card"><h1>Aplicación cerrada</h1><p>Ya puedes cerrar esta pestaña.</p></div></main>'}catch(e){alert(e.message)}};
$('start').onclick=async()=>{const url=$('url').value.trim();if(!url)return alert('Pega una URL de SoundCloud.');try{await api('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,bit_depth:Number($('depth').value),keep_original:$('keep').checked,force_redownload:$('force').checked})});await refresh()}catch(e){alert(e.message)}};
$('cancel').onclick=async()=>{try{await api('/api/cancel',{method:'POST'});await refresh()}catch(e){alert(e.message)}};
function esc(s){return String(s??'')}
async function refresh(){try{const s=await api('/api/status');running=s.running;$('folder').value=s.download_dir;$('message').textContent=s.message;$('state').textContent=s.status;$('current').textContent=s.current_title||'';$('progress').style.width=`${s.percent}%`;$('percent').textContent=`${Math.round(s.percent)}%`;const base=s.total?`${s.completed}/${s.total} pistas`:`${s.completed} pistas`;$('count').textContent=s.failed?`${base} · ${s.failed} error(es)`:base;$('speed').textContent=s.speed?`Velocidad: ${s.speed}`:'';$('eta').textContent=s.eta?`Faltan: ${s.eta}`:'';$('log').textContent=s.logs.length?s.logs.join('\n'):'La actividad aparecerá aquí.';$('log').scrollTop=$('log').scrollHeight;$('start').disabled=running;$('url').disabled=running;$('depth').disabled=running;$('keep').disabled=running;$('force').disabled=running;$('close').disabled=running;$('cancel').classList.toggle('hidden',!running)}catch(e){console.error(e)}}
setInterval(refresh,800);refresh();
</script></body></html>'''


class RequestHandler(BaseHTTPRequestHandler):
    server_version = f"SoundCloudWAV/{APP_VERSION}"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")

    def send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 100_000:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/":
            body = HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self.send_json(STATE.snapshot())
        else:
            self.send_json({"error": "No encontrado"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/start":
            try:
                data = self.read_json()
                url = safe_text(data.get("url"))
                bit_depth = int(data.get("bit_depth", 24))
                keep_original = bool(data.get("keep_original", False))
                force_redownload = bool(data.get("force_redownload", False))

                if STATE.snapshot()["running"]:
                    self.send_json({"error": "Ya hay una descarga en curso"}, HTTPStatus.CONFLICT)
                    return
                if not soundcloud_url_is_allowed(url):
                    self.send_json({"error": "La URL debe pertenecer a SoundCloud"}, HTTPStatus.BAD_REQUEST)
                    return
                if bit_depth not in {16, 24}:
                    self.send_json({"error": "Profundidad WAV no válida"}, HTTPStatus.BAD_REQUEST)
                    return

                thread = threading.Thread(
                    target=run_download,
                    args=(url, bit_depth, keep_original, force_redownload),
                    daemon=True,
                    name="soundcloud-download",
                )
                thread.start()
                self.send_json({"ok": True}, HTTPStatus.ACCEPTED)
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json({"error": f"Solicitud inválida: {exc}"}, HTTPStatus.BAD_REQUEST)

        elif self.path == "/api/cancel":
            with STATE.lock:
                if STATE.status not in {"starting", "downloading", "converting", "cancelling"}:
                    self.send_json({"error": "No hay una descarga activa"}, HTTPStatus.CONFLICT)
                    return
                STATE.cancel_requested = True
                STATE.status = "cancelling"
                STATE.message = "Cancelando..."
                process = STATE.ffmpeg_process
            if process and process.poll() is None:
                process.terminate()
            self.send_json({"ok": True})

        elif self.path == "/api/open":
            try:
                open_download_folder()
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        elif self.path == "/api/shutdown":
            if STATE.snapshot()["running"]:
                self.send_json({"error": "Hay una descarga activa"}, HTTPStatus.CONFLICT)
                return
            self.send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True, name="server-shutdown").start()
        else:
            self.send_json({"error": "No encontrado"}, HTTPStatus.NOT_FOUND)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server() -> LocalServer:
    last_error: OSError | None = None
    for port in range(PREFERRED_PORT, PREFERRED_PORT + 20):
        try:
            return LocalServer((HOST, port), RequestHandler)
        except OSError as exc:
            last_error = exc
    try:
        return LocalServer((HOST, 0), RequestHandler)
    except OSError:
        if last_error:
            raise last_error
        raise


def main() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    server = create_server()
    port = int(server.server_address[1])
    url = f"http://{HOST}:{port}"
    print("=" * 64)
    print(f"{APP_NAME} v{APP_VERSION}")
    print("=" * 64)
    print(f"Interfaz: {url}")
    print(f"Descargas: {DOWNLOAD_ROOT}")
    print(f"Registro: {LOG_FILE}")
    print("Puedes cerrar desde la interfaz o presionar Ctrl+C.")
    threading.Timer(0.8, lambda: webbrowser.open(url, new=2)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
