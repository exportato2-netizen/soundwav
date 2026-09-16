from __future__ import annotations

import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import privacy_patch as privacy

VERSION = "1.4"
FRAGMENTS = 8
_ORIG_CONVERT = None
_ORIG_RESET = None
_ORIG_SNAPSHOT = None
_ORIG_POST = None
_START = threading.Lock()
_ANSI_RE = re.compile(r"\x1B(?:\[[0-?]*[ -/]*[@-~]|[@-_])")


def wav_bits(p: Path) -> int | None:
    try:
        chunks = privacy._scan_riff_chunks(p)
        fmt = next((x for x in chunks if x[0] == b"fmt "), None)
        if not fmt or fmt[2] < 16:
            return None
        with p.open("rb") as h:
            h.seek(fmt[1] + 14)
            raw = h.read(2)
        return int.from_bytes(raw, "little") if len(raw) == 2 else None
    except Exception:
        return None


def clean_wav(p: Path, bits: int | None = None) -> bool:
    try:
        ok = [x[0] for x in privacy._scan_riff_chunks(p)] == [b"fmt ", b"data"]
        return ok and (bits is None or wav_bits(p) == bits)
    except Exception:
        return False


def final_path(info: dict[str, Any]) -> Path:
    folder = privacy._clean_component(
        info.get("playlist_title") or info.get("album") or info.get("uploader"),
        "Descargas",
        64,
    )
    title = privacy._clean_component(info.get("title"), "Pista", 112)
    idx = info.get("playlist_index") or info.get("track_number")
    prefix = ""
    try:
        if idx is not None and int(idx) > 0:
            prefix = f"{int(idx):03d} - "
    except (TypeError, ValueError):
        pass
    return privacy.app.DOWNLOAD_ROOT / folder / f"{prefix}{title}.wav"


def choose_path(info: dict[str, Any], overwrite: bool) -> Path:
    target = final_path(info)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Si llegamos a convertir, el filtro ya determinó que el archivo esperado
    # falta, está sucio, tiene otra profundidad o se forzó la descarga.
    return target


def purge_file_metadata(p: Path) -> None:
    if hasattr(os, "listxattr") and hasattr(os, "removexattr"):
        try:
            for x in os.listxattr(p):
                try:
                    os.removexattr(p, x)
                except OSError:
                    pass
        except OSError:
            pass
    if os.name == "nt":
        try:
            os.remove(str(p) + ":Zone.Identifier")
        except OSError:
            pass
    try:
        now = time.time()
        os.utime(p, (now, now))
    except OSError:
        pass


def convert(
    source: Path,
    info: dict[str, Any],
    bits: int,
    keep: bool = False,
    *,
    overwrite: bool = False,
) -> Path:
    if bits not in {16, 24}:
        raise ValueError("Profundidad WAV no valida")
    p = _ORIG_CONVERT(source, info, bits, keep, overwrite=overwrite)
    purge_file_metadata(p)
    if not clean_wav(p, bits):
        p.unlink(missing_ok=True)
        raise RuntimeError(
            "El WAV final no supero la verificacion fmt/data y profundidad"
        )
    return p


def rate(v: float) -> str:
    if not v or v <= 0:
        return "--"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if v < 1024 or unit == "GB/s":
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
        v /= 1024
    return "--"


def eta(v: float | None) -> str:
    if v is None or v < 0:
        return "--"
    n = int(round(v))
    h, r = divmod(n, 3600)
    m, s = divmod(r, 60)
    return f"{h} h {m:02d} min" if h else (
        f"{m} min {s:02d} s" if m else f"{s} s"
    )


def _plain_log(value: Any) -> str:
    text = _ANSI_RE.sub("", str(value or ""))
    text = text.replace("\r", "").strip()
    return text


class CleanLogger:
    """Logger sin ANSI y con mensajes de error comprensibles para la UI."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def debug(self, message: str) -> None:
        text = _plain_log(message)
        if not text or text.startswith("[debug]"):
            return
        self.app.STATE.log(text)

    def info(self, message: str) -> None:
        text = _plain_log(message)
        if text:
            self.app.STATE.log(text)

    def warning(self, message: str) -> None:
        text = _plain_log(message)
        if not text:
            return
        if "Original download format is only available for registered users" in text:
            self.app.STATE.log(
                "El formato Original requiere una sesion de SoundCloud; "
                "se usara la mejor fuente publica disponible."
            )
            return
        self.app.STATE.log(f"Aviso: {text}")

    def error(self, message: str) -> None:
        text = _plain_log(message)
        with self.app.STATE.lock:
            self.app.STATE.had_download_errors = True
            if self.app.STATE.status in {"starting", "downloading", "converting"}:
                self.app.STATE.status = "downloading"
                self.app.STATE.message = (
                    "Una pista fallo; Soundwav continuara con las siguientes..."
                )
        if "HTTP Error 403" in text or "403: Forbidden" in text:
            self.app.STATE.log(
                "SoundCloud rechazo temporalmente una fuente de esta pista "
                "(HTTP 403). Se omite esa pista y la playlist continua."
            )
        self.app.STATE.log(f"Error: {text}")


def patch_state(app: Any) -> None:
    global _ORIG_RESET, _ORIG_SNAPSHOT
    _ORIG_RESET = app.JobState.reset
    _ORIG_SNAPSHOT = app.JobState.snapshot

    def _extras(self: Any) -> None:
        self.skipped = 0
        self.speed_text = "--"
        self.eta_text = "--"
        self._last_b = 0
        self._last_t = time.monotonic()
        self._ema = 0.0

    def reset(self: Any) -> None:
        _ORIG_RESET(self)
        with self.lock:
            _extras(self)

    def snapshot(self: Any) -> dict[str, Any]:
        d = _ORIG_SNAPSHOT(self)
        with self.lock:
            d.update(
                skipped=getattr(self, "skipped", 0),
                speed_text=getattr(self, "speed_text", "--"),
                eta_text=getattr(self, "eta_text", "--"),
            )
        return d

    app.JobState.reset = reset
    app.JobState.snapshot = snapshot

    # Inicializa solo los campos añadidos por v1.4. No llama reset() aquí:
    # hacerlo pondría el estado en "starting" antes de una descarga real.
    with app.STATE.lock:
        _extras(app.STATE)


def progress(state: Any, d: dict[str, Any]) -> None:
    b = int(d.get("downloaded_bytes") or 0)
    total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
    now = time.monotonic()
    try:
        s = float(d.get("speed") or 0)
    except Exception:
        s = 0.0

    with state.lock:
        if s <= 0 and b >= state._last_b and now > state._last_t:
            s = (b - state._last_b) / (now - state._last_t)
        if s > 0:
            state._ema = s if state._ema <= 0 else state._ema * 0.72 + s * 0.28
        state._last_b = b
        state._last_t = now
        if total > 0:
            state.percent = max(0.0, min(100.0, b * 100 / total))
        state.speed_text = rate(state._ema)
        remain = (
            (total - b) / state._ema
            if total > b and state._ema > 0
            else d.get("eta")
        )
        try:
            remain = float(remain) if remain is not None else None
        except Exception:
            remain = None
        state.eta_text = eta(remain)
        state.speed = state.speed_text
        state.eta = state.eta_text


def _infer_failed(state: Any) -> int:
    with state.lock:
        total = state.total
        completed = state.completed
        skipped = getattr(state, "skipped", 0)
        failed = state.failed
        if isinstance(total, int) and total >= 0:
            missing = max(0, total - completed - skipped)
            failed = max(failed, missing)
            state.failed = failed
        return failed


def run(
    url: str,
    bits: int,
    _keep: bool,
    force: bool,
    state_prepared: bool = False,
) -> None:
    app = privacy.app
    if not state_prepared:
        app.STATE.reset()

    try:
        if bits not in {16, 24}:
            raise ValueError("Profundidad WAV no valida")

        app.DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        privacy.SESSION_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        skipped: set[str] = set()

        def mf(info: dict[str, Any], *, incomplete: bool) -> str | None:
            n = info.get("playlist_count") or info.get("n_entries")
            if isinstance(n, int):
                with app.STATE.lock:
                    app.STATE.total = n

            if force or incomplete:
                return None

            p = final_path(info)
            if not (p.exists() and clean_wav(p, bits)):
                return None

            key = str(info.get("id") or p)
            if key not in skipped:
                skipped.add(key)
                with app.STATE.lock:
                    app.STATE.skipped += 1
                app.STATE.log(f"Ya existe WAV limpio; se omite: {p.name}")
            return "El WAV limpio ya existe"

        def hook(d: dict[str, Any]) -> None:
            if app.STATE.cancel_requested:
                raise app.yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")

            info = d.get("info_dict") or {}
            title = app.safe_text(info.get("title"), "Procesando pista")
            n = info.get("playlist_count") or info.get("n_entries")
            if isinstance(n, int):
                with app.STATE.lock:
                    app.STATE.total = n

            if d.get("status") == "downloading":
                progress(app.STATE, d)
                with app.STATE.lock:
                    app.STATE.status = "downloading"
                    app.STATE.message = "Descargando la mejor fuente disponible..."
                    app.STATE.current_title = title

            elif d.get("status") == "finished":
                parts = [
                    str(x)
                    for x in (
                        info.get("format_note"),
                        info.get("acodec"),
                        info.get("ext"),
                    )
                    if x
                ]
                if info.get("abr"):
                    parts.append(f"{info['abr']} kb/s")
                if info.get("asr"):
                    parts.append(f"{info['asr']} Hz")
                if parts:
                    app.STATE.log("Fuente seleccionada: " + " | ".join(parts))
                with app.STATE.lock:
                    app.STATE.status = "converting"
                    app.STATE.message = "Creando WAV limpio..."
                    app.STATE.current_title = title
                    app.STATE.percent = 100.0

        opts: dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": str(
                privacy.SESSION_TEMP_ROOT / "%(playlist_index|0)03d-%(id)s.%(ext)s"
            ),
            "yesplaylist": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "continuedl": True,
            "overwrites": bool(force),
            "windowsfilenames": True,
            "trim_file_name": 120,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
            "file_access_retries": 3,
            "socket_timeout": 20,
            "concurrent_fragment_downloads": FRAGMENTS,
            "sleep_interval_requests": 0,
            "progress_hooks": [hook],
            "match_filter": mf,
            "logger": CleanLogger(app),
            "quiet": False,
            "no_warnings": False,
            "noprogress": True,
            "writethumbnail": False,
            "writeinfojson": False,
            "writedescription": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "xattrs": False,
            "updatetime": False,
            "cachedir": False,
            "postprocessors": [],
            # SoundCloud puede devolver 403 al resolver una variante HLS concreta
            # aunque la misma pista tenga una fuente HTTP publica utilizable.
            # Pedimos HTTP AAC/Opus/MP3; los formatos "Original" siguen siendo
            # extraidos por yt-dlp cuando SoundCloud los ofrece.
            "extractor_args": {
                "soundcloud": {
                    "formats": ["http_aac", "http_opus", "http_mp3"],
                }
            },
        }

        app.STATE.log(
            f"WAV PCM {bits} bits; hasta {FRAGMENTS} fragmentos simultaneos "
            "cuando el protocolo lo permite"
        )
        app.STATE.log(
            "SoundCloud: se priorizan fuentes HTTP publicas estables; "
            "Original sigue disponible si SoundCloud lo ofrece."
        )
        app.STATE.log(
            "Chequeo por archivo real: solo se omite si el WAV esperado existe, "
            "esta limpio y coincide en profundidad"
        )

        with app.yt_dlp.YoutubeDL(opts) as ydl:
            ydl.add_post_processor(
                privacy.CleanWavPostProcessor(ydl, bits, overwrite=force),
                when="post_process",
            )
            result = ydl.download([url])

        failed = _infer_failed(app.STATE)
        with app.STATE.lock:
            app.STATE.current_title = ""
            app.STATE.eta_text = "0 s"
            app.STATE.eta = "0 s"

            if app.STATE.cancel_requested:
                app.STATE.status = "cancelled"
                app.STATE.message = "Descarga cancelada"
            elif (
                result not in (0, None) or app.STATE.had_download_errors
            ) and app.STATE.completed == 0 and not app.STATE.skipped:
                app.STATE.status = "error"
                app.STATE.message = (
                    f"No se pudo completar ninguna pista"
                    + (f"; {failed} fallaron" if failed else "")
                )
            else:
                app.STATE.status = "completed"
                app.STATE.percent = 100.0
                if failed:
                    app.STATE.message = (
                        f"Finalizado con errores: {app.STATE.completed} nuevas | "
                        f"{app.STATE.skipped} ya existentes | {failed} fallidas"
                    )
                elif app.STATE.completed or app.STATE.skipped:
                    app.STATE.message = (
                        f"Finalizado: {app.STATE.completed} nuevas | "
                        f"{app.STATE.skipped} ya existentes"
                    )
                else:
                    app.STATE.message = "No habia pistas nuevas para descargar"

        app.STATE.log(app.STATE.message)

    except app.yt_dlp.utils.DownloadCancelled:
        with app.STATE.lock:
            app.STATE.status = "cancelled"
            app.STATE.message = "Descarga cancelada"
            app.STATE.current_title = ""
    except Exception as e:
        with app.STATE.lock:
            app.STATE.status = (
                "cancelled" if app.STATE.cancel_requested else "error"
            )
            app.STATE.message = app.safe_text(e, "Error inesperado")
            app.STATE.current_title = ""
        app.STATE.log(f"Error: {_plain_log(e)}")
    finally:
        with app.STATE.lock:
            app.STATE.finished_at = time.time()
            app.STATE.ffmpeg_process = None
        shutil.rmtree(privacy.SESSION_TEMP_ROOT, ignore_errors=True)


def patch_html(app: Any) -> None:
    h = app.HTML
    h = h.replace(
        ".stats{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:14px}",
        ".stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));"
        "gap:10px;color:var(--muted);font-size:13px}.stats span{background:#0d0d15;"
        "border:1px solid #ffffff10;border-radius:11px;padding:10px}"
        "@media(max-width:720px){.stats{grid-template-columns:1fr 1fr}}",
    )
    h = h.replace(
        '<div class="stats"><span id="percent">0%</span><span id="count">0 pistas</span>'
        '<span id="speed"></span><span id="eta"></span></div>',
        '<div class="stats"><span id="percent">Progreso: 0%</span>'
        '<span id="count">Pistas: 0</span><span id="speed">Velocidad: --</span>'
        '<span id="eta">Restante: --</span></div>',
    )
    h = h.replace(
        "$('percent').textContent=`${Math.round(s.percent)}%`;",
        "$('percent').textContent=`Progreso: ${Math.round(s.percent)}%`;",
    )
    h = h.replace(
        "const base=s.total?`${s.completed}/${s.total} pistas`:`${s.completed} pistas`;"
        "$('count').textContent=s.failed?`${base} · ${s.failed} error(es)`:base;",
        "const done=s.completed+(s.skipped||0)+(s.failed||0);"
        "const base=s.total?`${done}/${s.total}`:`${done}`;"
        "const news=` | ${s.completed} nuevas`;"
        "const skip=s.skipped?` | ${s.skipped} existentes`:'';"
        "const errors=s.failed?` | ${s.failed} fallidas`:'';"
        "$('count').textContent=`Pistas: ${base}${news}${skip}${errors}`;",
    )
    h = h.replace(
        "$('speed').textContent=s.speed?`Velocidad: ${s.speed}`:'';"
        "$('eta').textContent=s.eta?`Faltan: ${s.eta}`:'';",
        "$('speed').textContent=`Velocidad: ${s.speed_text||'--'}`;"
        "$('eta').textContent=`Restante: ${s.eta_text||'--'}`;",
    )
    app.HTML = h


def apply(app: Any) -> None:
    global _ORIG_CONVERT, _ORIG_POST
    app.APP_VERSION = VERSION
    patch_state(app)
    _ORIG_CONVERT = privacy.convert_to_wav_clean

    privacy._final_destination = choose_path
    privacy.convert_to_wav_clean = convert
    privacy.run_download_clean = run
    app.convert_to_wav = convert
    app.run_download = run

    _ORIG_POST = app.RequestHandler.do_POST

    def post(self: Any) -> None:
        if urlparse(self.path).path != "/api/start":
            return _ORIG_POST(self)

        try:
            d = self.read_json()
            if not isinstance(d, dict):
                return self.send_json(
                    {"error": "El cuerpo JSON debe ser un objeto"},
                    app.HTTPStatus.BAD_REQUEST,
                )

            url = app.safe_text(d.get("url"))
            raw_bits = d.get("bit_depth", 24)
            raw_force = d.get("force_redownload", False)

            if isinstance(raw_bits, bool):
                return self.send_json(
                    {"error": "Profundidad WAV no valida"},
                    app.HTTPStatus.BAD_REQUEST,
                )
            try:
                bits = int(raw_bits)
            except (TypeError, ValueError):
                return self.send_json(
                    {"error": "Profundidad WAV no valida"},
                    app.HTTPStatus.BAD_REQUEST,
                )

            if not isinstance(raw_force, bool):
                return self.send_json(
                    {"error": "force_redownload debe ser booleano"},
                    app.HTTPStatus.BAD_REQUEST,
                )
            force = raw_force

            if not app.soundcloud_url_is_allowed(url):
                return self.send_json(
                    {"error": "URL de SoundCloud no valida"},
                    app.HTTPStatus.BAD_REQUEST,
                )
            if bits not in {16, 24}:
                return self.send_json(
                    {"error": "Profundidad WAV no valida"},
                    app.HTTPStatus.BAD_REQUEST,
                )

            with _START:
                if app.STATE.snapshot()["running"]:
                    return self.send_json(
                        {"error": "Ya hay una descarga en curso"},
                        app.HTTPStatus.CONFLICT,
                    )
                app.STATE.reset()
                threading.Thread(
                    target=run,
                    args=(url, bits, False, force, True),
                    daemon=True,
                    name="soundwav-download",
                ).start()

            self.send_json({"ok": True}, app.HTTPStatus.ACCEPTED)

        except Exception as e:
            self.send_json(
                {"error": f"Solicitud invalida: {_plain_log(e)}"},
                app.HTTPStatus.BAD_REQUEST,
            )

    app.RequestHandler.do_POST = post
    patch_html(app)
