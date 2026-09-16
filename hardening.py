#!/usr/bin/env python3
"""Protecciones HTTP locales para la interfaz de Soundwav."""

from __future__ import annotations

import hmac
import json
import secrets
from urllib.parse import urlparse

API_TOKEN = secrets.token_urlsafe(32)
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def apply_hardening(app: object) -> None:
    """Protege la interfaz local contra llamadas externas y DNS rebinding.

    El token solo se inserta en la página servida por la propia aplicación y no
    se escribe en logs ni archivos.
    """
    handler = app.RequestHandler
    original_get = handler.do_GET
    original_post = handler.do_POST

    def local_host(self: object) -> bool:
        raw_host = self.headers.get("Host", "")
        host = raw_host.split(":", 1)[0].lower().rstrip(".")
        return host in _ALLOWED_HOSTS

    def authorized(self: object) -> bool:
        supplied = self.headers.get("X-Soundwav-Token", "")
        return hmac.compare_digest(supplied, API_TOKEN)

    def reject(self: object) -> None:
        self.send_json({"error": "No autorizado"}, app.HTTPStatus.FORBIDDEN)

    def protected_get(self: object) -> None:
        if not local_host(self):
            reject(self)
            return
        path = urlparse(self.path).path
        if path.startswith("/api/") and not authorized(self):
            reject(self)
            return
        original_get(self)

    def protected_post(self: object) -> None:
        if not local_host(self):
            reject(self)
            return
        path = urlparse(self.path).path
        if path.startswith("/api/") and not authorized(self):
            reject(self)
            return
        original_post(self)

    marker = "async function api(path,options={}){const r=await fetch(path,options);"
    replacement = (
        "const SOUNDWAV_TOKEN=" + json.dumps(API_TOKEN) + ";\n"
        "async function api(path,options={}){"
        "options.headers={...(options.headers||{}),'X-Soundwav-Token':SOUNDWAV_TOKEN};"
        "const r=await fetch(path,options);"
    )
    if marker not in app.HTML:
        raise RuntimeError("No se pudo aplicar la protección HTTP a la interfaz")
    app.HTML = app.HTML.replace(marker, replacement, 1)
    handler.do_GET = protected_get
    handler.do_POST = protected_post
