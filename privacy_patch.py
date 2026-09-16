#!/usr/bin/env python3
"""Capa de salida segura para Soundwav v1.3."""

from __future__ import annotations

import errno
import os
import re
import secrets
import shutil
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

import _core_app as app

VERSION = "1.3"
_START_GATE = threading.Lock()
_ORIGINAL_DO_POST = app.RequestHandler.do_POST


def _state_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return base / "soundwav"


STATE_ROOT = _state_root()
SESSION_TEMP_ROOT = STATE_ROOT / "temp" / f"session-{os.getpid()}-{secrets.token_hex(4)}"


def _clean_component(value: Any, fallback: str, max_length: int = 112) -> str:
    text = app.safe_text(value, fallback)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    device_name = text.split(".", 1)[0].upper()
    if device_name in reserved:
        text = f"_{text}"
    return text[:max_length].rstrip(" .") or fallback


def _remove_stale_temp_dirs(max_age_seconds: int = 172800) -> None:
    root = STATE_ROOT / "temp"
    if not root.exists():
        return
    cutoff = time.time() - max_age_seconds
    for path in root.glob("session-*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _final_destination(info: dict[str, Any], overwrite: bool) -> Path:
    folder_source = info.get("playlist_title") or info.get("album") or info.get("uploader")
    folder = _clean_component(folder_source, "Descargas", 64)
    title = _clean_component(info.get("title"), "Pista", 112)
    index = info.get("playlist_index") or info.get("track_number")
    prefix = ""
    try:
        if index is not None and int(index) > 0:
            prefix = f"{int(index):03d} - "
    except (TypeError, ValueError):
        pass

    target_dir = app.DOWNLOAD_ROOT / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{prefix}{title}.wav"
    if overwrite or not target.exists():
        return target

    stem = target.stem
    for number in range(2, 10000):
        candidate = target.with_name(f"{stem} ({number}).wav")
        if not candidate.exists():
            return candidate
    raise RuntimeError("No se pudo elegir un nombre de salida único")


def _scan_riff_chunks(path: Path) -> list[tuple[bytes, int, int]]:
    chunks: list[tuple[bytes, int, int]] = []
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise RuntimeError("El WAV temporal no tiene una cabecera RIFF/WAVE válida")
        offset = 12
        while offset + 8 <= file_size:
            handle.seek(offset)
            chunk_header = handle.read(8)
            if len(chunk_header) != 8:
                break
            chunk_id = chunk_header[:4]
            chunk_size = struct.unpack("<I", chunk_header[4:8])[0]
            data_offset = offset + 8
            end_offset = data_offset + chunk_size
            if end_offset > file_size:
                raise RuntimeError("El WAV temporal contiene un chunk truncado")
            chunks.append((chunk_id, data_offset, chunk_size))
            offset = end_offset + (chunk_size & 1)
    return chunks


def _copy_exact(source: BinaryIO, destination: BinaryIO, count: int) -> None:
    remaining = count
    while remaining:
        block = source.read(min(1024 * 1024, remaining))
        if not block:
            raise RuntimeError("El WAV temporal terminó inesperadamente")
        destination.write(block)
        remaining -= len(block)


def strip_wav_metadata(source: Path, destination: Path) -> None:
    """Reconstruye un WAV PCM conservando únicamente fmt y data."""
    chunks = _scan_riff_chunks(source)
    fmt_chunks = [chunk for chunk in chunks if chunk[0] == b"fmt "]
    data_chunks = [chunk for chunk in chunks if chunk[0] == b"data"]
    if len(fmt_chunks) != 1 or len(data_chunks) != 1:
        raise RuntimeError("El WAV temporal no contiene exactamente un chunk fmt y un chunk data")

    selected = [fmt_chunks[0], data_chunks[0]]
    riff_payload_size = 4 + sum(8 + size + (size & 1) for _, _, size in selected)
    if riff_payload_size > 0xFFFFFFFF:
        raise RuntimeError("El WAV supera el límite RIFF de 4 GiB")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("wb") as dst:
        dst.write(b"RIFF")
        dst.write(struct.pack("<I", riff_payload_size))
        dst.write(b"WAVE")
        for chunk_id, data_offset, chunk_size in selected:
            dst.write(chunk_id)
            dst.write(struct.pack("<I", chunk_size))
            src.seek(data_offset)
            _copy_exact(src, dst, chunk_size)
            if chunk_size & 1:
                dst.write(b"\x00")

    final_chunks = [chunk_id for chunk_id, _, _ in _scan_riff_chunks(destination)]
    if final_chunks != [b"fmt ", b"data"]:
        destination.unlink(missing_ok=True)
        raise RuntimeError("La verificación final de limpieza del WAV falló")


def _publish_clean_file(clean_output: Path, destination: Path, token: str) -> None:
    """Publica el WAV incluso si temp y Música están en volúmenes distintos."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(clean_output, destination)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise

    staging = destination.with_name(f".{destination.name}.{token}.tmp")
    staging.unlink(missing_ok=True)
    try:
        shutil.copyfile(clean_output, staging)
        copied_chunks = [chunk_id for chunk_id, _, _ in _scan_riff_chunks(staging)]
        if copied_chunks != [b"fmt ", b"data"]:
            raise RuntimeError("La copia al volumen de destino no superó la verificación WAV")
        os.replace(staging, destination)
        clean_output.unlink(missing_ok=True)
    finally:
        staging.unlink(missing_ok=True)


def convert_to_wav_clean(
    source: Path,
    info: dict[str, Any],
    bit_depth: int,
    _keep_original: bool = False,
    *,
    overwrite: bool = False,
) -> Path:
    if app.STATE.cancel_requested:
        raise RuntimeError("Descarga cancelada")
    if not source.exists():
        raise RuntimeError(f"No se encontró el audio descargado: {source.name}")

    SESSION_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    destination = _final_destination(info, overwrite)
    token = secrets.token_hex(8)
    ffmpeg_output = SESSION_TEMP_ROOT / f"ffmpeg-{token}.wav"
    clean_output = SESSION_TEMP_ROOT / f"clean-{token}.wav"
    codec = "pcm_s24le" if bit_depth == 24 else "pcm_s16le"
    ffmpeg_exe = app.imageio_ffmpeg.get_ffmpeg_exe()

    with app.STATE.lock:
        app.STATE.status = "converting"
        app.STATE.message = f"Convirtiendo y limpiando WAV ({bit_depth} bits)..."
        app.STATE.current_title = app.safe_text(info.get("title"), source.stem)

    command = [
        ffmpeg_exe,
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-map", "0:a:0",
        "-vn",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-fflags", "+bitexact",
        "-flags:a", "+bitexact",
        "-c:a", codec,
        "-write_bext", "0",
        "-write_peak", "off",
        str(ffmpeg_output),
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
    with app.STATE.lock:
        app.STATE.ffmpeg_process = process

    try:
        while process.poll() is None:
            if app.STATE.cancel_requested:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise RuntimeError("Descarga cancelada")
            time.sleep(0.2)

        _, stderr = process.communicate()
        if process.returncode != 0 or not ffmpeg_output.exists():
            raise RuntimeError(
                f"FFmpeg no pudo convertir {source.name}: {app.safe_text(stderr, 'error desconocido')}"
            )

        strip_wav_metadata(ffmpeg_output, clean_output)
        _publish_clean_file(clean_output, destination, token)
        app.STATE.log(f"WAV limpio verificado: {destination.name}")
        return destination
    finally:
        with app.STATE.lock:
            app.STATE.ffmpeg_process = None
        ffmpeg_output.unlink(missing_ok=True)
        clean_output.unlink(missing_ok=True)


class CleanWavPostProcessor(app.PostProcessor):
    def __init__(self, downloader: Any, bit_depth: int, _keep_original: bool = False, overwrite: bool = False) -> None:
        super().__init__(downloader)
        self.bit_depth = bit_depth
        self.overwrite = overwrite

    def run(self, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        source_name = app.safe_text(info.get("filepath") or info.get("_filename"))
        if not source_name:
            source_name = app.safe_text(self._downloader.prepare_filename(info))
        source = Path(source_name)

        try:
            destination = convert_to_wav_clean(source, info, self.bit_depth, overwrite=self.overwrite)
        except Exception as exc:
            if app.STATE.cancel_requested:
                raise app.yt_dlp.utils.DownloadCancelled("Cancelado por el usuario") from exc
            with app.STATE.lock:
                app.STATE.failed += 1
            raise app.yt_dlp.utils.PostProcessingError(str(exc)) from exc

        with app.STATE.lock:
            app.STATE.completed += 1
            app.STATE.percent = 100.0
            app.STATE.status = "downloading"
            app.STATE.message = "Continuando con la playlist..."

        info["filepath"] = str(destination)
        info["_filename"] = str(destination)
        info["ext"] = "wav"
        return ([str(source)] if source != destination else []), info


def run_download_clean(
    url: str,
    bit_depth: int,
    _keep_original: bool,
    force_redownload: bool,
    state_prepared: bool = False,
) -> None:
    if not state_prepared:
        app.STATE.reset()
    app.DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    SESSION_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    if app.STATE.cancel_requested:
        with app.STATE.lock:
            app.STATE.status = "cancelled"
            app.STATE.message = "Descarga cancelada"
            app.STATE.finished_at = time.time()
        shutil.rmtree(SESSION_TEMP_ROOT, ignore_errors=True)
        return

    def progress_hook(data: dict[str, Any]) -> None:
        if app.STATE.cancel_requested:
            raise app.yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
        status = data.get("status")
        info = data.get("info_dict") or {}
        title = app.safe_text(info.get("title"), "Procesando pista")
        if status == "downloading":
            with app.STATE.lock:
                app.STATE.status = "downloading"
                app.STATE.message = "Descargando el mejor audio disponible..."
                app.STATE.current_title = title
                app.STATE.percent = app.parse_percent(data.get("_percent_str"))
                app.STATE.speed = app.safe_text(data.get("_speed_str"))
                app.STATE.eta = app.safe_text(data.get("_eta_str"))
                playlist_count = info.get("playlist_count") or info.get("n_entries")
                if isinstance(playlist_count, int):
                    app.STATE.total = playlist_count
        elif status == "finished":
            with app.STATE.lock:
                app.STATE.status = "converting"
                app.STATE.message = "Audio descargado; preparando WAV limpio..."
                app.STATE.current_title = title
                app.STATE.percent = 100.0

    output_template = str(SESSION_TEMP_ROOT / "%(playlist_index|0)03d-%(id)s.%(ext)s")
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "yesplaylist": True,
        "noplaylist": False,
        "ignoreerrors": True,
        "continuedl": True,
        "overwrites": bool(force_redownload),
        "windowsfilenames": True,
        "trim_file_name": 120,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 5,
        "sleep_interval_requests": 0.75,
        "concurrent_fragment_downloads": 1,
        "progress_hooks": [progress_hook],
        "logger": app.UILogger(),
        "quiet": False,
        "no_warnings": False,
        "noprogress": True,
        "restrictfilenames": False,
        "writethumbnail": False,
        "writeinfojson": False,
        "writedescription": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "cachedir": False,
        "postprocessors": [],
    }
    if not force_redownload:
        options["download_archive"] = str(app.ARCHIVE_FILE)

    app.STATE.log(f"Carpeta de salida: {app.DOWNLOAD_ROOT}")
    app.STATE.log(f"Formato final: WAV PCM {bit_depth} bits, verificado sin chunks de metadatos")
    try:
        free_gb = shutil.disk_usage(app.DOWNLOAD_ROOT).free / (1024 ** 3)
        app.STATE.log(f"Espacio libre: {free_gb:.1f} GB")
    except OSError:
        pass

    try:
        with app.yt_dlp.YoutubeDL(options) as downloader:
            downloader.add_post_processor(
                CleanWavPostProcessor(downloader, bit_depth, overwrite=force_redownload),
                when="post_process",
            )
            result = downloader.download([url])

        if app.STATE.cancel_requested:
            with app.STATE.lock:
                app.STATE.status = "cancelled"
                app.STATE.message = "Descarga cancelada"
        elif (result not in (0, None) or app.STATE.had_download_errors) and app.STATE.completed == 0:
            with app.STATE.lock:
                app.STATE.status = "error"
                app.STATE.message = "No se pudo completar ninguna pista; revisa el registro"
            app.STATE.log(app.STATE.message)
        else:
            with app.STATE.lock:
                app.STATE.status = "completed"
                app.STATE.percent = 100.0
                if app.STATE.failed:
                    app.STATE.message = f"Finalizado: {app.STATE.completed} pistas, {app.STATE.failed} con error"
                elif app.STATE.had_download_errors or result not in (0, None):
                    app.STATE.message = f"Finalizado: {app.STATE.completed} pistas; hubo errores en algunas descargas"
                elif app.STATE.completed:
                    app.STATE.message = f"Playlist terminada: {app.STATE.completed} pistas WAV"
                else:
                    app.STATE.message = "No había pistas nuevas para descargar"
            app.STATE.log(app.STATE.message)

    except app.yt_dlp.utils.DownloadCancelled:
        with app.STATE.lock:
            app.STATE.status = "cancelled"
            app.STATE.message = "Descarga cancelada"
        app.STATE.log("Descarga cancelada por el usuario")
    except Exception as exc:
        if app.STATE.cancel_requested:
            with app.STATE.lock:
                app.STATE.status = "cancelled"
                app.STATE.message = "Descarga cancelada"
        else:
            with app.STATE.lock:
                app.STATE.status = "error"
                app.STATE.message = app.safe_text(exc, "Error inesperado")
            app.STATE.log(f"Error inesperado: {exc}")
            app.STATE.log(app.traceback.format_exc())
    finally:
        with app.STATE.lock:
            app.STATE.finished_at = time.time()
            app.STATE.ffmpeg_process = None
        shutil.rmtree(SESSION_TEMP_ROOT, ignore_errors=True)


def _handle_start(self: Any) -> None:
    try:
        data = self.read_json()
        if not isinstance(data, dict):
            raise ValueError("El cuerpo JSON debe ser un objeto")
        url = app.safe_text(data.get("url"))
        bit_depth = int(data.get("bit_depth", 24))
        force_redownload = bool(data.get("force_redownload", False))

        if not app.soundcloud_url_is_allowed(url):
            self.send_json({"error": "La URL debe pertenecer a SoundCloud"}, app.HTTPStatus.BAD_REQUEST)
            return
        if bit_depth not in {16, 24}:
            self.send_json({"error": "Profundidad WAV no válida"}, app.HTTPStatus.BAD_REQUEST)
            return

        with _START_GATE:
            if app.STATE.snapshot()["running"]:
                self.send_json({"error": "Ya hay una descarga en curso"}, app.HTTPStatus.CONFLICT)
                return
            app.STATE.reset()
            thread = threading.Thread(
                target=run_download_clean,
                args=(url, bit_depth, False, force_redownload, True),
                daemon=True,
                name="soundwav-download",
            )
            try:
                thread.start()
            except Exception as exc:
                with app.STATE.lock:
                    app.STATE.status = "error"
                    app.STATE.message = app.safe_text(exc, "No se pudo iniciar la descarga")
                    app.STATE.finished_at = time.time()
                self.send_json({"error": app.STATE.message}, app.HTTPStatus.INTERNAL_SERVER_ERROR)
                return

        self.send_json({"ok": True}, app.HTTPStatus.ACCEPTED)
    except (ValueError, UnicodeDecodeError) as exc:
        self.send_json({"error": f"Solicitud inválida: {exc}"}, app.HTTPStatus.BAD_REQUEST)


def _patched_do_POST(self: Any) -> None:
    path = urlparse(self.path).path
    if path == "/api/start":
        _handle_start(self)
        return
    _ORIGINAL_DO_POST(self)


def _patch_html(html: str) -> str:
    html = re.sub(
        r'<label class="check"><input id="keep" type="checkbox">.*?</label>\s*',
        "",
        html,
        count=1,
    )
    html = html.replace("keep_original:$('keep').checked,", "")
    html = html.replace(";$('keep').disabled=running", "")
    html = html.replace(
        "El registro completo también queda guardado en la carpeta de descargas.",
        "Cada WAV final se verifica con solo los chunks RIFF fmt y data. Los temporales quedan fuera de la carpeta de música.",
    )
    return html


def apply_patch() -> None:
    app.APP_NAME = "Soundwav"
    app.APP_VERSION = VERSION
    app.DOWNLOAD_ROOT = Path.home() / "Music" / "WAV_Descargas"
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _remove_stale_temp_dirs()
    app.ARCHIVE_FILE = STATE_ROOT / "descargados.txt"
    app.LOG_FILE = STATE_ROOT / "actividad.log"

    app.convert_to_wav = convert_to_wav_clean
    app.WavPostProcessor = CleanWavPostProcessor
    app.run_download = run_download_clean
    app.RequestHandler.server_version = f"soundwav/{VERSION}"
    app.RequestHandler.do_POST = _patched_do_POST
    app.HTML = _patch_html(app.HTML)


if __name__ == "__main__":
    apply_patch()
    app.main()
