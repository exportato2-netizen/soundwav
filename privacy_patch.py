#!/usr/bin/env python3
"""Arranque reforzado: WAV final sin metadatos ni rastros de origen en nombre/ruta."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import app

VERSION = "1.2"


def _state_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return base / "soundwav"


def _clean_component(value: Any, fallback: str) -> str:
    text = app.safe_text(value, fallback)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if text.upper() in reserved:
        text = f"_{text}"
    return text[:150]


def _clean_destination(source: Path, info: dict[str, Any]) -> Path:
    folder_source = info.get("playlist_title") or info.get("album") or info.get("uploader")
    folder = _clean_component(folder_source, "Descargas")
    title = _clean_component(info.get("title"), "Pista")

    index = info.get("playlist_index") or info.get("track_number")
    prefix = ""
    try:
        if index is not None and int(index) > 0:
            prefix = f"{int(index):03d} - "
    except (TypeError, ValueError):
        pass

    target_dir = app.DOWNLOAD_ROOT / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{prefix}{title}.wav"


def convert_to_wav_clean(source: Path, info: dict[str, Any], bit_depth: int, _keep_original: bool = False) -> Path:
    """Reescribe siempre el audio y deja el WAV sin tags/chunks de metadatos."""
    if app.STATE.cancel_requested:
        raise RuntimeError("Descarga cancelada")

    destination = _clean_destination(source, info)
    temp_output = destination.with_name(f".{destination.stem}.tmp.wav")
    temp_output.unlink(missing_ok=True)

    codec = "pcm_s24le" if bit_depth == 24 else "pcm_s16le"
    ffmpeg_exe = app.imageio_ffmpeg.get_ffmpeg_exe()

    with app.STATE.lock:
        app.STATE.status = "converting"
        app.STATE.message = f"Convirtiendo y eliminando metadatos ({bit_depth} bits)..."
        app.STATE.current_title = app.safe_text(info.get("title"), source.stem)

    command = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
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
        str(temp_output),
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

    while process.poll() is None:
        if app.STATE.cancel_requested:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            temp_output.unlink(missing_ok=True)
            raise RuntimeError("Descarga cancelada")
        time.sleep(0.2)

    _, stderr = process.communicate()
    with app.STATE.lock:
        app.STATE.ffmpeg_process = None

    if process.returncode != 0 or not temp_output.exists():
        temp_output.unlink(missing_ok=True)
        raise RuntimeError(
            f"FFmpeg no pudo convertir {source.name}: {app.safe_text(stderr, 'error desconocido')}"
        )

    temp_output.replace(destination)
    app.STATE.log(f"WAV limpio terminado: {destination.name}")
    return destination


class CleanWavPostProcessor(app.PostProcessor):
    """Postprocesador que conserva únicamente el WAV limpio final."""

    def __init__(self, downloader: Any, bit_depth: int, _keep_original: bool = False) -> None:
        super().__init__(downloader)
        self.bit_depth = bit_depth

    def run(self, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        source_name = app.safe_text(info.get("filepath") or info.get("_filename"))
        if not source_name:
            source_name = app.safe_text(self._downloader.prepare_filename(info))
        source = Path(source_name)

        try:
            destination = convert_to_wav_clean(source, info, self.bit_depth)
        except Exception as exc:
            if app.STATE.cancel_requested:
                raise app.yt_dlp.utils.DownloadCancelled("Cancelado por el usuario") from exc
            with app.STATE.lock:
                app.STATE.failed += 1
            raise app.yt_dlp.utils.PostProcessingError(str(exc)) from exc

        if source != destination:
            source.unlink(missing_ok=True)
            if source.parent != destination.parent:
                try:
                    source.parent.rmdir()
                except OSError:
                    pass

        with app.STATE.lock:
            app.STATE.completed += 1
            app.STATE.percent = 100.0
            app.STATE.status = "downloading"
            app.STATE.message = "Continuando con la playlist..."

        info["filepath"] = str(destination)
        info["_filename"] = str(destination)
        info["ext"] = "wav"
        return [], info


def apply_patch() -> None:
    app.APP_VERSION = VERSION
    app.DOWNLOAD_ROOT = Path.home() / "Music" / "WAV_Descargas"
    state_root = _state_root()
    state_root.mkdir(parents=True, exist_ok=True)
    app.ARCHIVE_FILE = state_root / "descargados.txt"
    app.LOG_FILE = state_root / "actividad.log"

    app.convert_to_wav = convert_to_wav_clean
    app.WavPostProcessor = CleanWavPostProcessor
    app.RequestHandler.server_version = f"soundwav/{VERSION}"

    app.HTML = app.HTML.replace(
        '<label class="check"><input id="keep" type="checkbox">Conservar también el archivo fuente descargado</label>\n',
        "",
    )
    app.HTML = app.HTML.replace(
        "keep_original:$('keep').checked,",
        "",
    )
    app.HTML = app.HTML.replace(";$('keep').disabled=running", "")
    app.HTML = app.HTML.replace(
        "El registro completo también queda guardado en la carpeta de descargas.",
        "Los WAV finales se guardan sin metadatos. El registro interno queda fuera de la carpeta de música.",
    )


if __name__ == "__main__":
    apply_patch()
    app.main()
