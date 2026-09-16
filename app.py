#!/usr/bin/env python3
"""Entrada segura de Soundwav v1.4."""

from hardening import apply_hardening
import privacy_patch as privacy
from v14_download import apply as apply_download_v14
import v14_window as window_v14


def _restore_idle_state(app: object) -> None:
    """Corrige el estado inicial para que la interfaz no arranque bloqueada."""
    with app.STATE.lock:
        app.STATE.status = "idle"
        app.STATE.message = "Listo para comenzar"
        app.STATE.percent = 0.0
        app.STATE.current_title = ""
        app.STATE.speed = ""
        app.STATE.eta = ""
        app.STATE.completed = 0
        app.STATE.failed = 0
        app.STATE.had_download_errors = False
        app.STATE.total = None
        app.STATE.cancel_requested = False
        app.STATE.started_at = None
        app.STATE.finished_at = None
        app.STATE.ffmpeg_process = None
        if hasattr(app.STATE, "skipped"):
            app.STATE.skipped = 0
        if hasattr(app.STATE, "speed_text"):
            app.STATE.speed_text = "--"
        if hasattr(app.STATE, "eta_text"):
            app.STATE.eta_text = "--"


def _style_start_button(app: object) -> None:
    html = app.HTML
    html = html.replace(
        "background:linear-gradient(135deg,#ff7b00,#ff3d00);margin-top:20px;width:100%;font-size:17px;padding:15px",
        "background:linear-gradient(135deg,#35d46f,#159447);margin-top:20px;width:100%;font-size:17px;padding:15px;box-shadow:0 10px 28px #18b95a35",
        1,
    )
    html = html.replace(">Descargar playlist</button>", ">Iniciar descarga</button>", 1)
    app.HTML = html


def _neutral_browser_watch(server: object, process: object) -> None:
    """No apaga Soundwav solo porque el proceso lanzador de Chromium termine."""
    try:
        process.wait()
    except Exception:
        pass


def main() -> None:
    privacy.apply_patch()
    apply_download_v14(privacy.app)
    _restore_idle_state(privacy.app)
    _style_start_button(privacy.app)

    # Chromium puede entregar la ventana a otro proceso y cerrar el proceso
    # lanzador inmediatamente. El cierre real queda gobernado por heartbeat.
    window_v14.browser_watch = _neutral_browser_watch
    window_v14.apply(privacy.app)
    apply_hardening(privacy.app)
    window_v14.run(privacy.app)


if __name__ == "__main__":
    main()
