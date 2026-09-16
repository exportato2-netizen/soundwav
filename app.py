#!/usr/bin/env python3
"""Entrada segura de Soundwav."""

from hardening import apply_hardening
from privacy_patch import app, apply_patch


def main() -> None:
    apply_patch()
    apply_hardening(app)
    app.main()


if __name__ == "__main__":
    main()
