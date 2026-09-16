#!/usr/bin/env python3
"""Entrada segura de Soundwav."""

from privacy_patch import app, apply_patch


def main() -> None:
    apply_patch()
    app.main()


if __name__ == "__main__":
    main()
