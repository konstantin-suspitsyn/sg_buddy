"""Точка входа: `uv run sgbuddy [--native] [--port N]`."""

from __future__ import annotations

import argparse

from nicegui import ui

from .app import FAVICON, build


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sgbuddy",
        description="SG Buddy — настройка и генерация sqlc-запросов и .proto по DDL-схеме",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--native", action="store_true", help="отдельное окно вместо вкладки браузера"
    )
    parser.add_argument("--no-show", action="store_true", help="не открывать браузер")
    args = parser.parse_args()

    build()

    ui.run(
        title="SG Buddy",
        port=args.port,
        native=args.native,
        show=not args.no_show,
        reload=False,
        favicon=FAVICON,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
