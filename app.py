#!/usr/bin/env python3
"""Entrada segura de Soundwav."""

from hardening import apply_hardening
import privacy_patch as privacy


def _install_runtime_guards() -> None:
    original_download = privacy.run_download_clean

    def guarded_download(*args: object, **kwargs: object) -> None:
        try:
            privacy.app.DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
            privacy.SESSION_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            with privacy.app.STATE.lock:
                privacy.app.STATE.status = "error"
                privacy.app.STATE.message = f"No se pudo preparar la carpeta de trabajo: {exc}"
                privacy.app.STATE.finished_at = privacy.time.time()
                privacy.app.STATE.ffmpeg_process = None
            privacy.app.STATE.log(privacy.app.STATE.message)
            return
        original_download(*args, **kwargs)

    privacy.run_download_clean = guarded_download
    privacy.app.run_download = guarded_download


def main() -> None:
    privacy.apply_patch()
    _install_runtime_guards()
    apply_hardening(privacy.app)
    privacy.app.main()


if __name__ == "__main__":
    main()
