"""Start the review window on 127.0.0.1 only (FR-6.1). No LAN binding exists in this phase."""

from __future__ import annotations

import errno
import logging
import socket
import threading
import webbrowser

import uvicorn

from nabu import pipeline
from nabu.config import Config
from nabu.server.app import create_app
from nabu.server.documents import DocumentService
from nabu.store.paths import StorePaths
from nabu.store.store import Store

log = logging.getLogger("nabu.server")
HOST = "127.0.0.1"


def find_free_port(preferred: int, tries: int = 20) -> int:
    """Preferred port, else the next free one (FR-6.1)."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError as e:
                if e.errno not in (errno.EADDRINUSE, errno.EACCES, 10048, 10013):
                    raise
    raise OSError(f"no free port between {preferred} and {preferred + tries - 1}")


def readers_factory(cfg: Config, store: Store):  # type: ignore[no-untyped-def]
    """What is installed, built on first use. The OCR engine loads its models once; the model
    client and translation memory are read fresh for each document."""
    cache: dict[str, object] = {}
    lock = threading.Lock()

    def readers() -> pipeline.Readers:
        from nabu.lang.memory import TranslationMemory
        from nabu.model.client import ModelClient
        from nabu.ocr import engine

        with lock:
            if "ocr" not in cache:
                cache["ocr"] = engine.detect(store.paths.ocr_langs_dir, cfg.ocr_engine)
        return pipeline.Readers(ocr=cache["ocr"],  # type: ignore[arg-type]
                                model=ModelClient(cfg) if cfg.model else None,
                                memory=TranslationMemory(store.translations()))
    return readers


def serve(cfg: Config, paths: StorePaths, open_browser: bool = True) -> None:
    from nabu.doctor import report

    port = find_free_port(cfg.ui_port)
    holder: dict[str, uvicorn.Server] = {}

    def quit_server() -> None:
        holder["server"].should_exit = True

    documents = DocumentService(cfg, readers_factory(cfg, Store(paths)))
    app, _token = create_app(port, on_quit=quit_server, documents=documents,
                             doctor_report=lambda: report(cfg, paths),
                             upload_limit_mb=cfg.upload_limit_mb)
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", access_log=False,
                            server_header=False, date_header=False, proxy_headers=False)
    server = uvicorn.Server(config)
    holder["server"] = server

    url = f"http://{HOST}:{port}/"
    log.info("review window at %s", url)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.run()
    finally:
        documents.close_all()  # FR-11.3: released when the window stops
