#!/usr/bin/env python3
"""Entrada segura de Soundwav v1.4."""

from hardening import apply_hardening
import privacy_patch as privacy
from v14_download import apply as apply_download_v14
from v14_window import apply as apply_window_v14, run as run_window_v14


def main() -> None:
    privacy.apply_patch()
    apply_download_v14(privacy.app)
    apply_window_v14(privacy.app)
    apply_hardening(privacy.app)
    run_window_v14(privacy.app)


if __name__ == "__main__":
    main()
