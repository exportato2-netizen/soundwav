#!/usr/bin/env python3
"""Cargador interno protegido de Soundwav."""

from pathlib import Path

if __name__ == "__main__":
    from app import main as safe_main

    safe_main()
else:
    _source_path = Path(__file__).with_name("_core_app.src")
    if not _source_path.exists():
        raise RuntimeError("Falta el núcleo interno _core_app.src")
    _source = _source_path.read_text(encoding="utf-8")
    exec(compile(_source, str(_source_path), "exec"), globals(), globals())
