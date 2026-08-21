"""Интерфейс.

Оформление повторяет макет `datacomrade_frontend/design-mockup/page-template.css`:
тёмная полупрозрачная шапка, PT Sans в заголовках, JetBrains Mono в тексте.

Шаги:
1. папка со схемой — путь вводится текстом: программа поднимается локальным
   веб-сервером, и браузер каталог сам по себе отдать не может;
2. файл `.proto`, куда потом ляжет контракт;
3. `schema.json` рядом со схемой (создаём, если его нет) и разбор `schema.sql` —
   после этого слева появляется список таблиц.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

from nicegui import app, ui

from .ddl import DDLError, Table, parse_schema_file
from .proto_gen import generate as generate_proto
from .query_gen import (
    JOIN_TYPES,
    QUERY_FILENAME,
    GenerationError,
    default_query_path,
    generate,
    ident,
    is_alias,
)
from .settings import (
    ANNOTATION_KEY,
    GO_PACKAGE_KEY,
    PROTO_PACKAGE_KEY,
    COLUMN_NAME_KEY,
    COLUMN_VALUE_KEY,
    COLUMNS_KEY,
    CUSTOM_QUERY_KEY,
    CUSTOM_WHERE_KEY,
    DIRECTIONS,
    EXACT_WHERE_KEY,
    JOIN_ALIAS_KEY,
    JOIN_NAME_KEY,
    JOIN_ON_KEY,
    JOIN_TABLE_KEY,
    JOIN_TYPE_KEY,
    JOINED_COLUMNS_KEY,
    LINKS_KEY,
    MODE_KEY,
    NAME_KEY,
    ORDER_BY_KEY,
    ORDER_BY_OPTIONAL_KEY,
    PAGINATION_KEY,
    SAVE_PROTO_KEY,
    SET_KEY,
    SET_VALUE_KEY,
    SETTINGS_FILENAME,
    SHOW_KEY,
    USED_JOINS_KEY,
    WHERE_KEY,
    WHERE_OPTIONAL_KEY,
    WHERE_VALUE_KEY,
    all_entries,
    default_settings,
    ensure_directions,
    ensure_joins,
    entries_of,
    joins_of,
    migrate_crud,
    load_settings,
    save_settings,
    settings_path,
    with_paths,
)

ASSETS = Path(__file__).parent / "assets"
# NiceGUI отдаёт favicon сам, до add_static_files, поэтому нужен путь на диске.
FAVICON = ASSETS / "favicon.ico"
LOGO = "/assets/hacker_dog.png"
# Картинки лежат в пакете: программа работает без сети и без соседних репозиториев.
MASCOT = "/assets/working_dog.png"

SCHEMA_FILENAME = "schema.sql"
PROTO_SUFFIX = ".proto"

ACCENT = "#9370DB"

# Что можно делать с таблицей. Join стоит после CRUD: он не запрос, а связь,
# которую потом включают в выборку.
ACTIONS = ("Create", "Read", "Update", "Delete", "Join")

# Аннотации sqlc: INSERT возвращает строку или ничего, SELECT — строку или список.
ANNOTATIONS = ("one", "exec")
READ_ANNOTATIONS = ("one", "many")
UPDATE_ANNOTATIONS = ("exec", "one")

# Удаление: физическое стирает строку, мягкое проставляет колонки, обратное
# возвращает их к прежним значениям. Мягкое и обратное устроены одинаково —
# это `UPDATE ... SET`, — и различаются только тем, что автор пишет в значения.
HARD_DELETE = "DELETE"
SOFT_DELETE = "SOFT DELETE"
UNDELETE = "UNDELETE"
DELETE_MODES = (HARD_DELETE, SOFT_DELETE, UNDELETE)
SET_MODES = (SOFT_DELETE, UNDELETE)
ANNOTATION_HELP = "SQLC Query annotations"

JOIN_HELP = (
    "Цепочка — одна или несколько таблиц, присоединяемых по порядку. "
    "Связь «многие ко многим» собирается из двух звеньев: сперва связующая "
    "таблица, потом целевая."
)

JOIN_READ_HELP = (
    "Колонки приджойненной таблицы выходят под именем с алиасом (alias_column): "
    "двух одинаковых имён в одной выборке sqlc не примет. Этим же именем "
    "называются их параметры."
)

CUSTOM_WHERE_HELP = (
    "Своё условие WHERE. Приклеивается к остальным через AND, "
    "то есть сужает выборку, а не заменяет её."
)

ORDER_BY_HELP = (
    "«ORDER BY» — колонки сортируются всегда, в вызове их не выбирают. "
    "«ORDER BY OPTIONAL» — колонка выбирается параметром order_by (её имя строкой), "
    "направление у обеих групп общее — параметр order (ASC/DESC)."
)

# Текст — JetBrains Mono, заголовки — PT Sans. Обе подключены с Google Fonts,
# за ними идёт web-safe цепочка: без интернета шрифт подменится, но вёрстка
# останется той же — моноширинный к моноширинному, гротеск к гротеску.
STYLES = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=PT+Sans:wght@400;700&display=swap">
<style>
  :root {
    --font-text: 'JetBrains Mono', Consolas, 'Courier New', monospace;
    --font-head: 'PT Sans', Verdana, Geneva, Tahoma, sans-serif;

    --bg: #ffffff;
    --bg-soft: #f6f7f9;
    --ink: #16181d;
    --ink-dim: #5b6270;
    --ink-faint: #9aa0ab;
    --card: #ffffff;
    --rule: #e9ebef;

    --accent: #9370DB;
    --accent-soft: #f1ebfe;

    --dark-bg: rgba(16, 19, 26, 0.94);
    --dark-ink: #f3f5f9;
    --dark-rule: rgba(255, 255, 255, 0.12);

    --radius: 14px;
    --radius-sm: 8px;
  }
  body, input, textarea, select, button,
  .q-field, .q-btn, .q-item, .q-table, .q-tooltip, .q-menu {
    font-family: var(--font-text);
  }
  body {
    background: var(--bg);
    color: var(--ink);
  }
  h1, h2, h3, h4, h5, h6,
  .text-h1, .text-h2, .text-h3, .text-h4, .text-h5, .text-h6,
  .text-subtitle1, .text-subtitle2,
  .q-toolbar__title, .app-title {
    font-family: var(--font-head);
  }

  /* Шапка — цвет и правило снизу как в макете. Содержимое лежит в общем
     `.container`, как в подвале и на странице: только так собака в шапке и
     собака в подвале стоят на одной вертикали, а не каждая по своему отступу. */
  .app-header {
    background: var(--dark-bg) !important;
    backdrop-filter: blur(6px);
    border-bottom: 1px solid var(--dark-rule);
    box-shadow: none;
    color: var(--dark-ink);
    display: block;
    padding: 8px 0;
  }
  .app-title {
    font-weight: 700;
    font-size: 17px;
    letter-spacing: -0.003em;
    color: var(--dark-ink);
  }
  /* Собаки в шапке и подвале: 54x62 и 62x59 — размер натуральный, ничего не
     масштабируем. pixelated нужен, чтобы пиксель-арт не мылился при DPR > 1. */
  .app-logo {
    display: block;
    flex-shrink: 0;
    image-rendering: pixelated;
  }

  /* Подвал — того же цвета, что и шапка. Правило зеркальное: там снизу, тут сверху.

     Раскладку низа держим сами. Quasar меряет высоту подвала один раз при
     старте и вписывает запас инлайном в `q-page-container`; наблюдателя размера
     у подвала нет, поэтому картинка, добавившая высоты, в запас не попадает — и
     длинная страница уезжает под полосу. Вместо запаса делаем колонку во всю
     высоту окна: страница растягивается, подвал идёт следом обычным потоком. */
  .q-layout {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }
  .q-page-container {
    flex: 1 0 auto;
    padding-bottom: 0 !important;
  }
  .q-page {
    min-height: 0 !important;
  }
  .app-footer {
    position: static;
    background: var(--dark-bg) !important;
    backdrop-filter: blur(6px);
    border-top: 1px solid var(--dark-rule);
    box-shadow: none;
    color: var(--dark-ink);
    padding: 26px 0;
  }
  .footer-copy {
    font-size: 11px;
    letter-spacing: 0.08em;
    color: rgba(243, 245, 249, 0.6);
  }

  /* ---------- страница ---------- */

  /* Сетку по горизонтали задаёт только `.container`, поэтому боковой отступ
     NiceGUI снимаем: иначе содержимое страницы уезжает на 16px вправо от шапки
     и подвала — они лежат вне этой обёртки. Сверху и снизу, наоборот, отступ
     нужен: страница не должна упираться в тёмные полосы. Держим его здесь, а не
     классами `q-pt-*` на обёртке, — их правило `.container` перебивает. */
  .nicegui-content {
    padding: 24px 0 40px;
  }
  /* В макете полоса была 1240px с отступами 56px, но туда не влезала таблица
     полей выборки: с колонками сортировки ей нужно 782px, а оставалось 712.
     1360 и отступы 32px дают запас и на широком окне, и на 1280px — там ширину
     задаёт само окно, и `max-width` уже ничем не помогает. */
  .container {
    max-width: 1360px;
    margin: 0 auto;
    padding: 0 32px;
    width: 100%;
  }
  .eyebrow {
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent);
    font-weight: 500;
  }
  .page-title {
    font-size: 34px;
    line-height: 1.15;
    font-weight: 700;
    margin: 6px 0 10px;
    letter-spacing: -0.01em;
  }
  .page-lede {
    color: var(--ink-dim);
    font-size: 14px;
    max-width: 62ch;
  }
  .card {
    background: var(--card);
    border: 1.5px solid var(--rule);
    border-radius: var(--radius);
    padding: 24px 26px;
    width: 100%;
  }
  .field-label {
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.02em;
    color: var(--ink-dim);
  }
  .hint {
    font-size: 12px;
    color: var(--ink-faint);
  }
  .error-text {
    font-size: 13px;
    color: #ef4444;
  }
  .ok-badge {
    display: inline-block;
    background: var(--accent-soft);
    color: var(--accent);
    border-radius: var(--radius-sm);
    padding: 2px 10px;
    font-size: 12px;
    font-weight: 600;
  }
  .path-line {
    font-size: 14px;
    word-break: break-all;
  }
  /* Кнопки макета поверх Quasar. */
  .btn-primary.q-btn {
    color: #fff;
    background-color: #cf245f;
    background-image: linear-gradient(to bottom right, #fcd34d, #ef4444, #ec4899);
    border-radius: 0.25rem;
    padding: 0.625rem 1.75rem;
    font-weight: 600;
    font-size: 0.875rem;
    /* Тень тёмно-бордовая, а не розовая из макета: под градиентом кнопки
       она читается как собственная тень, а не как второй цвет заливки. */
    box-shadow: 0 10px 20px -6px rgba(128, 0, 32, 0.55);
    transition: box-shadow 0.25s ease;
  }
  .btn-primary.q-btn:hover {
    box-shadow: none;
  }
  .btn-secondary.q-btn {
    color: var(--ink);
    background: var(--card);
    border: 1.5px solid var(--rule);
    border-radius: 0;
    padding: 10px 18px;
    font-weight: 700;
    font-size: 14px;
    box-shadow: none;
  }
  .btn-secondary.q-btn:hover {
    background: #10131a;
    color: var(--dark-ink);
    border-color: #10131a;
  }
  /* Кнопка в тёмной шапке: белая заливка здесь смотрелась бы заплаткой. */
  .btn-ghost.q-btn {
    color: var(--dark-ink);
    background: transparent;
    border: 1px solid var(--dark-rule);
    border-radius: 0.25rem;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 600;
    box-shadow: none;
  }
  .btn-ghost.q-btn:hover {
    background: rgba(255, 255, 255, 0.08);
  }

  /* ---------- список таблиц ---------- */

  .sidebar {
    width: 330px;
    flex-shrink: 0;
    background: var(--card);
    border: 1.5px solid var(--rule);
    border-radius: var(--radius);
    padding: 18px;
    max-height: calc(100vh - 260px);
    overflow-y: auto;
  }
  .table-row {
    padding: 7px 9px;
    border-radius: var(--radius-sm);
  }
  .table-row.selected {
    background: var(--accent-soft);
  }
  .table-name {
    font-size: 13px;
    font-weight: 600;
    word-break: break-all;
  }
  /* Счётчики запросов по направлениям: пустые красным, заполненные акцентом. */
  .counts {
    gap: 6px;
    font-size: 11px;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .counts .on {
    color: var(--accent);
    font-weight: 600;
  }
  .counts .off {
    color: #ef4444;
  }
  /* Все свои кнопки создаём с color=None: иначе Quasar вешает на них класс
     text-primary, красит текст акцентом через adoptedStyleSheets, и перебить
     это из обычной таблицы стилей нельзя даже с !important. */
  .crud-btn.q-btn {
    min-height: 0;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 500;
    color: var(--ink-dim) !important;
    background: var(--bg);
    border: 1px solid var(--rule);
    border-radius: 4px;
    box-shadow: none;
  }
  .crud-btn.q-btn:hover {
    color: var(--accent) !important;
    border-color: var(--accent);
  }
  .crud-btn.q-btn.active {
    color: #fff !important;
    background: var(--accent);
    border-color: var(--accent);
  }
  /* Пять кнопок в узкой колонке списка: общих отступов на них не хватает —
     ряд перестаёт помещаться в карточку и последняя кнопка обрезается. */
  .crud-btn.table-btn.q-btn {
    padding: 1px 4px;
  }

  /* ---------- таблица полей в форме ---------- */

  .grid-head, .grid-row {
    display: grid;
    grid-template-columns: minmax(140px, 1fr) minmax(160px, 1fr) 180px;
    gap: 12px;
    align-items: center;
    width: 100%;
  }
  /* Пять колонок выборки: поля, показать, WHERE, WHERE OPTIONAL, EXACT WHERE. */
  .grid-head.read-grid, .grid-row.read-grid {
    grid-template-columns: minmax(130px, 1.2fr) 84px 140px 130px minmax(150px, 1fr);
  }
  /* То же плюс две колонки сортировки — у выборки списка. Ширины ужаты: семь
     колонок в ту же ширину карточки иначе не помещаются. */
  .grid-head.read-order-grid, .grid-row.read-order-grid {
    grid-template-columns:
      minmax(120px, 1.1fr) 66px 108px 118px minmax(120px, 1fr) 74px 128px;
    gap: 8px;
  }
  /* Четыре колонки физического удаления: поля, WHERE, optional, значение. */
  .grid-head.delete-grid, .grid-row.delete-grid {
    grid-template-columns: minmax(140px, 1.2fr) 80px 140px minmax(150px, 1fr);
  }
  /* Шесть колонок изменения: поля, изменения, значение, WHERE, optional, значение. */
  .grid-head.update-grid, .grid-row.update-grid {
    grid-template-columns:
      minmax(120px, 1fr) 78px minmax(130px, 1.1fr) 68px 118px minmax(130px, 1.1fr);
    gap: 8px;
  }
  .grid-head {
    padding: 6px 8px;
    border-bottom: 1.5px solid var(--rule);
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.02em;
    color: var(--ink-dim);
  }
  .grid-row {
    padding: 4px 8px;
    border-bottom: 1px solid var(--rule);
  }
  .grid-row:last-of-type {
    border-bottom: 0;
  }
  .help-icon {
    color: var(--accent);
    cursor: help;
  }

  /* ---------- добавленные запросы ---------- */

  .record {
    border: 1.5px solid var(--rule);
    border-radius: var(--radius-sm);
    padding: 12px 14px;
    margin-top: 10px;
  }
  .record.editing {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .record-row {
    display: grid;
    grid-template-columns: minmax(140px, 1fr) 1fr;
    gap: 12px;
    padding: 2px 0;
  }
  .record-value {
    font-size: 13px;
    word-break: break-all;
  }
  .crud-btn.danger.q-btn:hover {
    color: #ef4444 !important;
    border-color: #ef4444;
  }
</style>
"""


@dataclass
class Workspace:
    """Что выбрано сейчас. Программа локальная, сессия одна — состояние одно."""

    folder: Path | None = None
    schema: Path | None = None
    folder_error: str | None = None

    proto: Path | None = None
    proto_error: str | None = None
    # Шапка будущего .proto — спрашиваем сразу за путём к файлу.
    go_package: str | None = None
    go_package_error: str | None = None
    proto_package: str | None = None
    proto_package_error: str | None = None
    # Что уже лежало в schema.json выбранной папки: путь и обе шапки.
    saved_proto: Path | None = None
    saved_go_package: str | None = None
    saved_proto_package: str | None = None

    tables: list[Table] | None = None
    settings: dict | None = None
    settings_file: Path | None = None
    settings_created: bool | None = None
    prepare_error: str | None = None

    # Результат последней генерации query.sql.
    query_file: Path | None = None
    query_problems: list | None = None

    # То же для .proto. Путь к файлу отдельным полем не держим: он выбран на
    # шаге 2 и лежит в `proto`.
    proto_problems: list | None = None

    selected_table: str | None = None
    selected_action: str | None = None

    def reset(self) -> None:
        """Всё в None. Обходим поля списком, чтобы новое поле сбрасывалось само."""
        for field in fields(self):
            setattr(self, field.name, None)


workspace = Workspace()


def reset_all() -> None:
    """«Начать заново»: программа возвращается к пустому первому шагу."""
    global form, read_form, update_form, delete_form, join_form

    workspace.reset()
    form = None
    read_form = None
    update_form = None
    delete_form = None
    join_form = None
    wizard.refresh()


def _step_head(eyebrow: str, title: str, lede: str) -> None:
    with ui.column().classes("w-full gap-0 q-pt-xl q-pb-md"):
        ui.label(eyebrow).classes("eyebrow")
        ui.label(title).classes("page-title")
        ui.label(lede).classes("page-lede")


# ---------------------------------------------------------------- шаг 1: схема


def choose_folder(raw: str | None) -> None:
    """Проверяет путь и запоминает папку. Ошибку показываем, не гадаем."""
    workspace.reset()
    workspace.folder_error = _validate_folder(raw) or None
    wizard.refresh()


def _validate_folder(raw: str | None) -> str:
    text = (raw or "").strip().strip('"')
    if not text:
        return "укажите путь к папке"

    path = Path(text).expanduser()
    # Из проводника чаще копируется файл, чем каталог: путь на сам schema.sql
    # принимаем и берём его папку.
    if path.is_file():
        path = path.parent

    if not path.exists():
        return f"такого пути нет: {path}"
    if not path.is_dir():
        return f"это не папка: {path}"

    schema = path / SCHEMA_FILENAME
    if not schema.is_file():
        return f"в папке нет {SCHEMA_FILENAME}: {path}"

    workspace.folder = path
    workspace.schema = schema
    (
        workspace.saved_proto,
        workspace.saved_go_package,
        workspace.saved_proto_package,
    ) = _saved_choices(path)
    return ""


def _saved_choices(folder: Path) -> tuple[Path | None, str | None, str | None]:
    """Ответы мастера из уже лежащего в папке `schema.json`.

    Файл почти всегда остался от прошлого запуска на этой же схеме, и прежние
    ответы — лучшая подсказка, чем умолчания. Читаем мягко: битый или чужой
    файл на выборе папки спотыкаться не должен, его разберёт шаг 3.
    """
    path = settings_path(folder)
    if not path.is_file():
        return None, None, None

    try:
        data = load_settings(path)
    except (OSError, ValueError):
        return None, None, None

    def written(key: str) -> str | None:
        value = data.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    proto = written(SAVE_PROTO_KEY)
    return (
        Path(proto) if proto else None,
        written(GO_PACKAGE_KEY),
        written(PROTO_PACKAGE_KEY),
    )


# «Другая папка» — тот же сброс: путь к .proto от прежней схемы почти наверняка
# уже не тот, и тащить его дальше опаснее, чем ввести заново.
_forget_folder = reset_all


def _folder_card() -> None:
    with ui.element("div").classes("card"):
        if workspace.folder is None:
            _folder_picker()
        else:
            _folder_chosen()


def _folder_picker() -> None:
    ui.label("Папка со схемой").classes("field-label")

    with ui.row().classes("w-full items-center gap-3 no-wrap q-mt-xs"):
        path_input = (
            ui.input(placeholder=r"C:\...\tables_model")
            .props("outlined dense")
            .classes("grow")
        )
        path_input.on("keydown.enter", lambda: choose_folder(path_input.value))
        ui.button(
            "Открыть", on_click=lambda: choose_folder(path_input.value), color=None
        ).props(
            "unelevated no-caps"
        ).classes("btn-primary")

    ui.label(f"в папке должен лежать {SCHEMA_FILENAME}").classes("hint q-mt-xs")

    if workspace.folder_error:
        ui.label(workspace.folder_error).classes("error-text q-mt-sm")


def _folder_chosen() -> None:
    stat = workspace.schema.stat()
    changed = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M")

    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        ui.label("папка выбрана").classes("ok-badge")
        ui.space()
        ui.button(
            "Другая папка", on_click=_forget_folder, color=None
        ).props("flat no-caps").classes("btn-secondary")

    ui.label(str(workspace.folder)).classes("path-line q-mt-sm")
    ui.label(f"{SCHEMA_FILENAME} · {stat.st_size} байт · изменён {changed}").classes(
        "hint q-mt-xs"
    )


# ---------------------------------------------------------------- шаг 2: .proto


def default_proto_path() -> Path:
    """По умолчанию — файл по имени папки, рядом со схемой."""
    folder = workspace.folder
    return folder / f"{folder.name}{PROTO_SUFFIX}"


def choose_proto(raw: str | None) -> None:
    # Разбор схемы ждёт go-пакета: он пишется в те же настройки, и заводить их
    # дважды — сначала без него, потом с ним — незачем.
    workspace.proto = None
    workspace.proto_error = _validate_proto(raw) or None
    wizard.refresh()


def _validate_proto(raw: str | None) -> str:
    text = (raw or "").strip().strip('"')
    if not text:
        return f"укажите путь к файлу {PROTO_SUFFIX}"

    path = Path(text).expanduser()
    # Указали папку — кладём в неё файл с именем по умолчанию.
    if path.is_dir():
        path = path / f"{path.name}{PROTO_SUFFIX}"
    elif not path.suffix:
        path = path.with_suffix(PROTO_SUFFIX)
    elif path.suffix != PROTO_SUFFIX:
        return f"файл должен оканчиваться на {PROTO_SUFFIX}, а не на {path.suffix}"

    # Папку под файл не создаём молча: путь с опечаткой не должен превращаться
    # в новый каталог где-то в стороне.
    if not path.parent.is_dir():
        return f"папки нет: {path.parent}"

    workspace.proto = path
    return ""


def _forget_proto() -> None:
    workspace.proto = None
    workspace.proto_error = None
    wizard.refresh()


def _proto_card() -> None:
    with ui.element("div").classes("card"):
        if workspace.proto is None:
            _proto_picker()
        else:
            _proto_chosen()


def _proto_picker() -> None:
    ui.label("Файл контракта").classes("field-label")

    # Путь подставляем только из прежних настроек: для новой папки без schema.json
    # угадывать имя файла не нужно, поле остаётся пустым.
    suggested = workspace.saved_proto

    with ui.row().classes("w-full items-center gap-3 no-wrap q-mt-xs"):
        path_input = (
            ui.input(value=str(suggested) if suggested else "")
            .props("outlined dense")
            .classes("grow")
        )
        path_input.on("keydown.enter", lambda: choose_proto(path_input.value))
        ui.button(
            "Указать", on_click=lambda: choose_proto(path_input.value), color=None
        ).props(
            "unelevated no-caps"
        ).classes("btn-primary")

    if workspace.saved_proto is not None:
        ui.label(f"путь взят из {SETTINGS_FILENAME} — можно заменить").classes(
            "hint q-mt-xs"
        )
    else:
        ui.label(
            f"можно указать папку — файл получит имя по умолчанию, {default_proto_path().name}"
        ).classes("hint q-mt-xs")

    if workspace.proto_error:
        ui.label(workspace.proto_error).classes("error-text q-mt-sm")


def _proto_chosen() -> None:
    proto = workspace.proto
    exists = proto.is_file()

    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        ui.label("файл выбран").classes("ok-badge")
        ui.space()
        ui.button(
            "Другой файл", on_click=_forget_proto, color=None
        ).props("flat no-caps").classes("btn-secondary")

    ui.label(str(proto)).classes("path-line q-mt-sm")
    # Сгенерированные файлы затираются целиком — это факт, а не повод для
    # предупреждения: подтверждений на перезапись программа не спрашивает.
    if exists:
        stat = proto.stat()
        changed = datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M")
        ui.label(
            f"файл уже есть · {stat.st_size} байт · изменён {changed} — затрём при генерации"
        ).classes("hint q-mt-xs")
    else:
        ui.label("файла ещё нет — создадим при генерации").classes("hint q-mt-xs")


# --------------------------------------------------------- шаг 2: go-пакет


def choose_go_package(raw: str | None) -> None:
    workspace.go_package = None
    workspace.go_package_error = _validate_go_package(raw) or None
    wizard.refresh()


def _validate_go_package(raw: str | None) -> str:
    text = (raw or "").strip().strip('"')
    if not text:
        return "укажите go-пакет"
    # Значение идёт в `option go_package = "..."` как есть, поэтому пробелы и
    # кавычки внутри — это сломанный .proto, а не наша вольная трактовка.
    if any(ch.isspace() for ch in text) or '"' in text:
        return "в go-пакете не бывает пробелов и кавычек"

    workspace.go_package = text
    return ""


def _forget_go_package() -> None:
    workspace.go_package = None
    workspace.go_package_error = None
    # Настройки уже завелись на прошлых ответах — сбрасываем и разбор схемы,
    # иначе слева остался бы список таблиц от неподтверждённого шага.
    workspace.tables = None
    wizard.refresh()


def _go_package_card() -> None:
    with ui.element("div").classes("card q-mt-md"):
        if workspace.go_package is None:
            _go_package_picker()
        else:
            _go_package_chosen()


def _go_package_picker() -> None:
    ui.label("go_package").classes("field-label")

    with ui.row().classes("w-full items-center gap-3 no-wrap q-mt-xs"):
        value_input = (
            ui.input(
                value=workspace.saved_go_package or "",
                placeholder="github.com/org/repo/gen/pb;pb",
            )
            .props("outlined dense")
            .classes("grow")
        )
        value_input.on("keydown.enter", lambda: choose_go_package(value_input.value))
        ui.button(
            "Указать", on_click=lambda: choose_go_package(value_input.value), color=None
        ).props("unelevated no-caps").classes("btn-primary")

    if workspace.saved_go_package:
        ui.label(f"взят из {SETTINGS_FILENAME} — можно заменить").classes("hint q-mt-xs")
    else:
        ui.label(
            "путь импорта для сгенерированного Go-кода: пойдёт в option go_package"
        ).classes("hint q-mt-xs")

    if workspace.go_package_error:
        ui.label(workspace.go_package_error).classes("error-text q-mt-sm")


def _go_package_chosen() -> None:
    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        ui.label("go-пакет указан").classes("ok-badge")
        ui.space()
        ui.button(
            "Изменить", on_click=_forget_go_package, color=None
        ).props("flat no-caps").classes("btn-secondary")

    ui.label(workspace.go_package).classes("path-line q-mt-sm")
    ui.label('в .proto пойдёт option go_package = "…"').classes("hint q-mt-xs")


# --------------------------------------------------------- шаг 2: package


# Имя пакета протобуфа: слова через точку, каждое — как идентификатор.
_PROTO_PACKAGE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")


def default_proto_package() -> str:
    """Подсказка: хвост go-пакета после `;` — там лежит имя пакета Go.

    Совпадение не обязательно, но так их пишут чаще всего, и одним кликом
    получается осмысленный ответ вместо пустого поля.
    """
    go = workspace.go_package or ""
    if ";" in go:
        return go.rsplit(";", 1)[1].strip()
    return go.rsplit("/", 1)[-1].strip()


def choose_proto_package(raw: str | None) -> None:
    """Запоминает пакет и, если он годный, разбирает схему."""
    workspace.proto_package = None
    workspace.proto_package_error = _validate_proto_package(raw) or None
    if workspace.proto_package is not None:
        prepare()
    wizard.refresh()


def _validate_proto_package(raw: str | None) -> str:
    text = (raw or "").strip().strip('"')
    if not text:
        return "укажите package"
    if not _PROTO_PACKAGE.match(text):
        return "package пишется словами через точку: api, dc.v1"

    workspace.proto_package = text
    return ""


def _forget_proto_package() -> None:
    workspace.proto_package = None
    workspace.proto_package_error = None
    workspace.tables = None
    wizard.refresh()


def _proto_package_card() -> None:
    with ui.element("div").classes("card q-mt-md"):
        if workspace.proto_package is None:
            _proto_package_picker()
        else:
            _proto_package_chosen()


def _proto_package_picker() -> None:
    ui.label("package").classes("field-label")

    suggested = workspace.saved_proto_package or default_proto_package()

    with ui.row().classes("w-full items-center gap-3 no-wrap q-mt-xs"):
        value_input = (
            ui.input(value=suggested, placeholder="api.v1")
            .props("outlined dense")
            .classes("grow")
        )
        value_input.on("keydown.enter", lambda: choose_proto_package(value_input.value))
        ui.button(
            "Указать",
            on_click=lambda: choose_proto_package(value_input.value),
            color=None,
        ).props("unelevated no-caps").classes("btn-primary")

    if workspace.saved_proto_package:
        ui.label(f"взят из {SETTINGS_FILENAME} — можно заменить").classes("hint q-mt-xs")
    else:
        ui.label("имя пакета протобуфа: пойдёт строкой package в .proto").classes(
            "hint q-mt-xs"
        )

    if workspace.proto_package_error:
        ui.label(workspace.proto_package_error).classes("error-text q-mt-sm")


def _proto_package_chosen() -> None:
    with ui.row().classes("w-full items-center gap-3 no-wrap"):
        ui.label("package указан").classes("ok-badge")
        ui.space()
        ui.button(
            "Изменить", on_click=_forget_proto_package, color=None
        ).props("flat no-caps").classes("btn-secondary")

    ui.label(workspace.proto_package).classes("path-line q-mt-sm")
    ui.label("в .proto пойдёт строкой package …;").classes("hint q-mt-xs")


# ------------------------------------------------- шаг 3: schema.json и таблицы


def prepare() -> None:
    """Заводит `schema.json` рядом со схемой и разбирает `schema.sql`.

    Всё, что спрашивает мастер, к этому моменту уже выбрано, так что шаг
    делается сам — ждать от пользователя ещё одного клика не за что.
    """
    workspace.prepare_error = None

    try:
        tables = parse_schema_file(workspace.schema)
    except DDLError as err:
        workspace.prepare_error = str(err)
        return

    path = settings_path(workspace.folder)
    try:
        created = not path.is_file()
        answers = (
            workspace.folder,
            workspace.proto,
            workspace.go_package or "",
            workspace.proto_package or "",
        )
        data = default_settings(*answers) if created else load_settings(path)
        # Ответы мастера в файле всегда отражают выбранное сейчас и стоят первыми.
        data = with_paths(migrate_crud(data), *answers)
        save_settings(data, path)
    except (OSError, ValueError) as err:
        workspace.prepare_error = f"{path}: {err}"
        return

    workspace.tables = tables
    workspace.settings = data
    workspace.settings_file = path
    workspace.settings_created = created
    workspace.selected_table = tables[0].name
    workspace.selected_action = None


def select(table: str, action: str | None) -> None:
    workspace.selected_table = table
    workspace.selected_action = action
    wizard.refresh()


def _summary_card() -> None:
    """Что выбрано — одной карточкой, чтобы шаги 1–2 не занимали пол-экрана."""
    created = workspace.settings_created
    with ui.element("div").classes("card"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.label(f"таблиц в схеме: {len(workspace.tables)}").classes("ok-badge")
            ui.label(
                f"{SETTINGS_FILENAME} {'создан' if created else 'найден'}"
            ).classes("ok-badge")
            ui.space()
            ui.button(
                "Сгенерировать query.sql", on_click=_generate_query, color=None
            ).props("unelevated no-caps").classes("btn-primary")
            ui.button(
                f"Сгенерировать {PROTO_SUFFIX}", on_click=_generate_proto, color=None
            ).props("unelevated no-caps").classes("btn-primary")
            ui.button(
                "Другая папка", on_click=reset_all, color=None
            ).props("flat no-caps").classes("btn-secondary")

        rows = [
            ("схема", workspace.schema),
            (PROTO_SUFFIX, workspace.proto),
            ("package", workspace.proto_package),
            ("go_package", workspace.go_package),
            ("настройки", workspace.settings_file),
        ]
        if workspace.query_file is not None:
            rows.append(("query.sql", workspace.query_file))

        for caption, value in rows:
            with ui.row().classes("w-full items-baseline gap-2 no-wrap q-mt-xs"):
                ui.label(caption).classes("field-label w-24 shrink-0")
                ui.label(str(value)).classes("path-line")

        # Списки проблем разные у двух генераторов — подписываем, чей какой.
        for caption, group in (
            (QUERY_FILENAME, workspace.query_problems),
            (PROTO_SUFFIX, workspace.proto_problems),
        ):
            if not group:
                continue
            ui.label(caption).classes("field-label q-mt-sm")
            for problem in group:
                ui.label(str(problem)).classes(
                    "error-text q-mt-xs" if problem.fatal else "hint q-mt-xs"
                )


def _generate_query() -> None:
    """Пишет query.sql рядом со схемой из того, что сейчас в настройках."""
    if not _save_settings():
        return
    try:
        path, problems = generate(
            workspace.settings, workspace.tables, default_query_path(workspace.folder)
        )
    except (GenerationError, OSError) as err:
        ui.notify(str(err), type="negative")
        return

    workspace.query_file = path
    workspace.query_problems = problems

    # path is None — генератор отказался писать: прежний файл цел, и говорить
    # надо про него, а не про «записано».
    if path is None:
        blocking = [p for p in problems if p.blocks_file]
        ui.notify(
            f"{QUERY_FILENAME} не тронут: {blocking[0].message}", type="negative"
        )
        wizard.refresh()
        return

    broken = sum(1 for problem in problems if problem.fatal)
    if broken:
        ui.notify(f"записано: {path}; пропущено запросов: {broken}", type="warning")
    else:
        ui.notify(f"записано: {path}", type="positive")
    wizard.refresh()


def _generate_proto() -> None:
    """Пишет .proto по выбранному на шаге 2 пути из того, что сейчас в настройках."""
    if not _save_settings():
        return
    try:
        path, problems = generate_proto(
            workspace.settings, workspace.tables, workspace.proto
        )
    except (GenerationError, OSError) as err:
        ui.notify(str(err), type="negative")
        return

    workspace.proto_problems = problems

    broken = sum(1 for problem in problems if problem.fatal)
    if broken:
        ui.notify(f"записано: {path}; пропущено запросов: {broken}", type="warning")
    else:
        ui.notify(f"записано: {path}", type="positive")
    wizard.refresh()


def _sidebar() -> None:
    with ui.element("div").classes("sidebar"):
        ui.label("Таблицы").classes("field-label")
        with ui.column().classes("w-full gap-1 q-mt-sm"):
            for table in workspace.tables:
                _table_row(table)


def _table_row(table: Table) -> None:
    selected = table.name == workspace.selected_table
    classes = "table-row selected" if selected else "table-row"

    with ui.column().classes(f"{classes} w-full gap-1"):
        with ui.column().classes("w-full gap-0 cursor-pointer").on(
            "click", lambda name=table.name: select(name, None)
        ):
            ui.label(table.name).classes("table-name")
            _counts(table)

        with ui.row().classes("w-full gap-1 no-wrap"):
            for action in ACTIONS:
                active = selected and action == workspace.selected_action
                ui.button(
                    action,
                    on_click=lambda t=table.name, a=action: select(t, a),
                    color=None,
                ).props("flat no-caps dense").classes(
                    "crud-btn table-btn active" if active else "crud-btn table-btn"
                )


# ------------------------------------------------- предложить название запроса


def camel(name: str) -> str:
    """`column_cat` -> `ColumnCat`, `dc."user"` -> `User`."""
    parts = re.split(r"[^0-9A-Za-z]+", name)
    return "".join(part[:1].upper() + part[1:] for part in parts if part)


def table_camel(table: Table) -> str:
    """Имя таблицы без схемы: `dc.column_cat` -> `ColumnCat`."""
    return camel(table.name.split(".")[-1])


_VOWELS = set("aeiou")


def pluralize(word: str) -> str:
    """`ColumnCat` -> `ColumnCats`, `Alias` -> `Aliases`, `GroupLevels` — как есть.

    Эвристика обязана быть предсказуемой, а не умной, поэтому правил ровно
    столько, сколько нужно для имён таблиц: свистящие получают `es`, согласная
    перед `y` даёт `ies`, остальные — `s`. Отдельно распознаём уже множественное
    число: `levels` кончается на `s` после согласной, а `alias` — после гласной.
    """
    if not word:
        return word

    lowered = word.lower()

    if lowered.endswith("s") and not lowered.endswith("ss") and len(lowered) > 2:
        if lowered[-2] not in _VOWELS:
            return word

    if lowered.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lowered.endswith("y") and len(lowered) > 1 and lowered[-2] not in _VOWELS:
        return word[:-1] + "ies"

    return word + "s"


def where_fields(
    table: Table, checked: set[str], values: dict[str, str] | None = None
) -> list[str]:
    """Колонки, попавшие в WHERE: галкой или заполненным значением."""
    values = values or {}
    return [
        col.name
        for col in table.columns
        if col.name in checked or (values.get(col.name) or "").strip()
    ]


def _by_suffix(fields_: list[str]) -> str:
    return ("By" + "".join(camel(name) for name in fields_)) if fields_ else ""


def suggest_create_name(table: Table) -> str:
    return f"Create{table_camel(table)}"


def suggest_read_name(table: Table, draft: "ReadForm") -> str:
    """Имя по галкам WHERE. EXACT WHERE в него не входит.

    Заполненный EXACT WHERE сам по себе условия не даёт — он лишь подставляет
    значение вместо параметра в колонку, уже отмеченную галкой. Считать его
    отбором значило бы приписывать имени условие, которого в запросе нет.
    """
    entity = table_camel(table)
    if draft.annotation == "many":
        entity = pluralize(entity)
    return f"Get{entity}" + _by_suffix(where_fields(table, draft.where))


def suggest_update_name(table: Table, draft: "UpdateForm") -> str:
    return f"Update{table_camel(table)}" + _by_suffix(
        where_fields(table, draft.where, draft.where_values)
    )


def suggest_delete_name(table: Table, draft: "DeleteForm") -> str:
    """`DeleteAlias`, а в режиме UNDELETE — `UndeleteAlias`.

    Обратное удаление противоположно двум другим режимам по смыслу, и в
    `query.sql` они лежат рядом: имя — единственное, что их различает.
    """
    verb = "Undelete" if draft.mode == UNDELETE else "Delete"
    return f"{verb}{table_camel(table)}" + _by_suffix(
        where_fields(table, draft.where, draft.where_values)
    )


def _suggest_button(draft, suggestion) -> None:
    """Кнопка под полем названия. Имя подставляется, но остаётся редактируемым."""

    def apply() -> None:
        draft.name = suggestion()
        draft.error = None
        wizard.refresh()

    with ui.row().classes("w-full q-mt-xs"):
        ui.button("Предложить название", on_click=apply, color=None).props(
            "flat no-caps dense"
        ).classes("crud-btn")


def _counts(table: Table) -> None:
    """`C:00 R:00 U:00 D:00 J:00` — сколько уже описано запросов и цепочек."""
    with ui.row().classes("counts no-wrap"):
        for letter, direction in zip("CRUD", DIRECTIONS):
            total = len(entries_of(workspace.settings, table.name, direction))
            ui.label(f"{letter}:{total:02d}").classes("on" if total else "off")

        # Join'ов у таблицы может не быть вовсе — это обычное дело, а не
        # незаполненность, поэтому нулевой счётчик не красим красным.
        total = len(joins_of(workspace.settings, table.name))
        ui.label(f"J:{total:02d}").classes("on" if total else "")


def _detail() -> None:
    """Правая половина: форма выбранного действия."""
    table = next(
        (t for t in workspace.tables if t.name == workspace.selected_table), None
    )
    with ui.column().classes("grow gap-4 min-w-0"):
        with ui.element("div").classes("card"):
            if table is None:
                ui.label("выберите таблицу слева").classes("hint")
                return

            ui.label(table.name).classes("page-title")
            if workspace.selected_action is None:
                ui.label("выберите действие: " + " · ".join(ACTIONS)).classes("hint")
                return

            ui.label(workspace.selected_action).classes("eyebrow")
            if workspace.selected_action == "Create":
                _create_form(table)
            elif workspace.selected_action == "Read":
                _read_form(table)
            elif workspace.selected_action == "Update":
                _update_form(table)
            elif workspace.selected_action == "Delete":
                _delete_form(table)
            elif workspace.selected_action == "Join":
                _join_form(table)

        if workspace.selected_action == "Create":
            _created_list(table)
        elif workspace.selected_action == "Read":
            _read_list(table)
        elif workspace.selected_action == "Update":
            _update_list(table)
        elif workspace.selected_action == "Delete":
            _delete_list(table)
        elif workspace.selected_action == "Join":
            _join_list(table)


# ---------------------------------------------------------------- форма Create


@dataclass
class CreateForm:
    """Черновик одного запроса вставки. Живёт до нажатия «Добавить»."""

    table: str
    name: str = ""
    annotation: str = ANNOTATIONS[0]
    # колонка -> чем её заменить; пусто означает «параметром запроса».
    values: dict[str, str] = field(default_factory=dict)
    excluded: set[str] = field(default_factory=set)
    custom_query: str = ""
    error: str | None = None
    # Индекс правимой записи в CRUD.CREATE или None, если это новая запись.
    editing: int | None = None


form: CreateForm | None = None


def form_for(table: Table) -> CreateForm:
    """Форма для выбранной таблицы. Значения по умолчанию берём из DDL."""
    global form
    if form is None or form.table != table.name:
        form = CreateForm(
            table=table.name,
            values={col.name: col.default_sql or "" for col in table.columns},
            excluded=set(),
        )
    return form


def _submit_create(table: Table) -> None:
    """Кладёт описание запроса в настройки. На диск пишет «Готово»."""
    global form

    draft = form_for(table)
    name = (draft.name or "").strip()
    if not name:
        draft.error = "укажите название"
        wizard.refresh()
        return

    # Имя запроса — имя метода в sqlc: два одинаковых он не разрешит.
    if _name_taken(name, table.name, "CREATE", skip=draft.editing):
        draft.error = f"запрос с названием {name!r} уже есть"
        wizard.refresh()
        return

    entries = ensure_directions(workspace.settings, table.name)["CREATE"]
    entry = {
        NAME_KEY: name,
        ANNOTATION_KEY: draft.annotation,
        COLUMNS_KEY: [
            {
                COLUMN_NAME_KEY: col.name,
                # Пусто — значит колонка приходит параметром: подставляем @имя.
                COLUMN_VALUE_KEY: (draft.values.get(col.name) or "").strip()
                or f"@{col.name}",
            }
            for col in table.columns
            if col.name not in draft.excluded
        ],
        CUSTOM_QUERY_KEY: (draft.custom_query or "").strip() or None,
    }

    if draft.editing is None:
        entries.append(entry)
    else:
        entries[draft.editing] = entry

    # Форму сбрасываем: значения остались видны в самой записи ниже.
    form = None
    wizard.refresh()


def _name_taken(
    name: str, table: str, own_direction: str, skip: int | None = None
) -> bool:
    """Занято ли имя запроса. Смотрим весь файл: sqlc не разрешит двойника нигде."""
    for other_table, direction, index, entry in all_entries(workspace.settings):
        own = other_table == table and direction == own_direction and index == skip
        if own:
            continue
        if entry.get(NAME_KEY, "").strip() == name:
            return True
    return False


def _edit_create(index: int, table: Table, *, editing: bool = True) -> None:
    """Загружает запись обратно в форму — правкой или копией.

    Копия несёт те же настройки, включая название: имя запроса уникально по
    всему файлу, и придумывать за автора новое здесь нечего — форма скажет,
    что название занято, когда он нажмёт «Добавить».
    """
    global form

    entry = entries_of(workspace.settings, table.name, "CREATE")[index]
    written = {
        col[COLUMN_NAME_KEY]: col[COLUMN_VALUE_KEY] for col in entry.get(COLUMNS_KEY, [])
    }
    form = CreateForm(
        table=table.name,
        name=entry.get(NAME_KEY, ""),
        annotation=entry.get(ANNOTATION_KEY, ANNOTATIONS[0]),
        # `@имя` — это «приходит параметром», в поле замены его показывать незачем.
        values={
            col.name: ("" if written.get(col.name) == f"@{col.name}" else written.get(col.name, ""))
            for col in table.columns
        },
        excluded={col.name for col in table.columns if col.name not in written},
        custom_query=entry.get(CUSTOM_QUERY_KEY) or "",
        editing=index if editing else None,
    )
    wizard.refresh()


def _copy_create(index: int, table: Table) -> None:
    """Та же вставка новой записью: сохранение ляжет рядом с исходной."""
    _edit_create(index, table, editing=False)


def _remove_create(index: int, table: Table) -> None:
    global form

    del entries_of(workspace.settings, table.name, "CREATE")[index]
    # Правили именно её — форму больше не к чему привязывать.
    if form is not None and form.editing == index:
        form = None
    wizard.refresh()


def _save_settings() -> bool:
    try:
        save_settings(workspace.settings, workspace.settings_file)
    except OSError as err:
        ui.notify(f"не сохранилось: {err}", type="negative")
        return False
    ui.notify(f"сохранено: {workspace.settings_file}", type="positive")
    return True


def _create_form(table: Table) -> None:
    draft = form_for(table)

    def set_value(column: str, value: str) -> None:
        draft.values[column] = value

    def set_excluded(column: str, on: bool) -> None:
        draft.excluded.add(column) if on else draft.excluded.discard(column)

    ui.label("Название").classes("field-label q-mt-md")
    ui.input(
        value=draft.name, on_change=lambda e: setattr(draft, "name", e.value)
    ).props("outlined dense").classes("w-full q-mt-xs")
    _suggest_button(draft, lambda: suggest_create_name(table))

    ui.label("Query Annotation").classes("field-label q-mt-md")
    with ui.row().classes("items-center gap-2 no-wrap q-mt-xs"):
        ui.select(
            list(ANNOTATIONS),
            value=draft.annotation,
            on_change=lambda e: setattr(draft, "annotation", e.value),
        ).props("outlined dense").classes("w-48")
        ui.icon("help_outline").classes("help-icon").tooltip(ANNOTATION_HELP)

    ui.label("Поля").classes("field-label q-mt-md")
    with ui.element("div").classes("grid-head q-mt-xs"):
        ui.label("поля")
        ui.label("замена значений")
        ui.label("исключить из генератора")

    for col in table.columns:
        with ui.element("div").classes("grid-row"):
            with ui.column().classes("gap-0"):
                ui.label(col.name).classes("table-name")
                ui.label(col.sql_type).classes("hint")
            ui.input(
                value=draft.values.get(col.name, ""),
                on_change=lambda e, c=col.name: set_value(c, e.value),
            ).props("outlined dense")
            ui.checkbox(
                value=col.name in draft.excluded,
                on_change=lambda e, c=col.name: set_excluded(c, e.value),
            ).props("dense")

    ui.label("Custom Query").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_query,
        on_change=lambda e: setattr(draft, "custom_query", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")

    if draft.error:
        ui.label(draft.error).classes("error-text q-mt-sm")

    with ui.row().classes("w-full justify-end q-mt-md"):
        if draft.editing is not None:
            ui.button(
                "Отменить правку", on_click=_cancel_edit, color=None
            ).props("flat no-caps").classes("btn-secondary")
        ui.button(
            "Сохранить" if draft.editing is not None else "Добавить",
            on_click=lambda: _submit_create(table),
            color=None,
        ).props("unelevated no-caps").classes("btn-primary")


def _cancel_edit() -> None:
    global form

    form = None
    wizard.refresh()


def _created_list(table: Table) -> None:
    """Добавленные запросы этой таблицы — зафиксированными значениями."""
    entries = entries_of(workspace.settings, table.name, "CREATE")
    if not entries:
        return

    with ui.element("div").classes("card"):
        ui.label(f"Добавленные запросы · {len(entries)}").classes("field-label")

        for index, entry in enumerate(entries):
            editing = form is not None and form.editing == index
            with ui.element("div").classes("record editing" if editing else "record"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(entry.get(NAME_KEY, "")).classes("table-name")
                    ui.label(f":{entry.get(ANNOTATION_KEY, '')}").classes("hint")
                    ui.space()
                    ui.button(
                        "Редактировать",
                        on_click=lambda i=index: _edit_create(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Скопировать",
                        on_click=lambda i=index: _copy_create(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Удалить",
                        on_click=lambda i=index: _remove_create(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn danger")

                for column in entry.get(COLUMNS_KEY, []):
                    with ui.element("div").classes("record-row"):
                        ui.label(column[COLUMN_NAME_KEY]).classes("hint")
                        ui.label(column[COLUMN_VALUE_KEY]).classes("record-value")

                with ui.element("div").classes("record-row"):
                    ui.label("Custom Query").classes("hint")
                    ui.label(entry.get(CUSTOM_QUERY_KEY) or "—").classes("record-value")


# ---------------------------------------------------------------- форма Read


@dataclass
class ReadForm:
    """Черновик одной выборки. Живёт до нажатия «Добавить»."""

    table: str
    name: str = ""
    annotation: str = READ_ANNOTATIONS[0]
    pagination: bool = False
    # По умолчанию показываем всё, не фильтруем ничего.
    show: set[str] = field(default_factory=set)
    where: set[str] = field(default_factory=set)
    where_optional: set[str] = field(default_factory=set)
    exact: dict[str, str] = field(default_factory=dict)
    # Сортировка — только у `many`. По умолчанию не отмечена ни одна колонка:
    # сортировать всю таблицу подряд никто не просил.
    order_by: set[str] = field(default_factory=set)
    order_by_optional: set[str] = field(default_factory=set)
    # Включённые цепочки join'ов — именами из раздела JOINS.
    joins: set[str] = field(default_factory=set)
    # Колонки приджойненных таблиц. Ключ — (цепочка, алиас, колонка): в одной
    # выборке встречаются `id` нескольких таблиц, и имени колонки тут мало.
    joined_show: set[tuple[str, str, str]] = field(default_factory=set)
    joined_where: set[tuple[str, str, str]] = field(default_factory=set)
    joined_where_optional: set[tuple[str, str, str]] = field(default_factory=set)
    joined_exact: dict[tuple[str, str, str], str] = field(default_factory=dict)
    joined_order_by: set[tuple[str, str, str]] = field(default_factory=set)
    joined_order_by_optional: set[tuple[str, str, str]] = field(default_factory=set)
    custom_where: str = ""
    custom_query: str = ""
    error: str | None = None
    editing: int | None = None


read_form: ReadForm | None = None


def read_form_for(table: Table) -> ReadForm:
    global read_form
    if read_form is None or read_form.table != table.name:
        read_form = ReadForm(
            table=table.name,
            show={col.name for col in table.columns},
        )
    return read_form


def _read_join_links(table: Table, draft: ReadForm) -> list[tuple[str, str, Table]]:
    """(цепочка, алиас, таблица) по звеньям включённых цепочек, в их порядке.

    Звено с таблицей, которой в схеме уже нет, сюда не попадает: форма
    показывает только то, что можно выбрать, а о пропаже скажет генератор —
    он один решает, собирается запрос или нет.
    """
    by_name = {item.name: item for item in workspace.tables}
    links: list[tuple[str, str, Table]] = []

    for chain in joins_of(workspace.settings, table.name):
        name = (chain.get(NAME_KEY) or "").strip()
        if name not in draft.joins:
            continue
        for link in chain.get(LINKS_KEY) or []:
            joined = by_name.get(link.get(JOIN_TABLE_KEY) or "")
            alias = (link.get(JOIN_ALIAS_KEY) or "").strip()
            if joined is not None and alias:
                links.append((name, alias, joined))

    return links


def _used_joins(table: Table, draft: ReadForm) -> list[str]:
    """Имена включённых цепочек в порядке раздела JOINS — в нём же они в SQL."""
    return [
        name
        for chain in joins_of(workspace.settings, table.name)
        if (name := (chain.get(NAME_KEY) or "").strip()) in draft.joins
    ]


def _submit_read(table: Table) -> None:
    global read_form

    draft = read_form_for(table)
    name = (draft.name or "").strip()
    if not name:
        draft.error = "укажите название"
        wizard.refresh()
        return

    if _name_taken(name, table.name, "READ", skip=draft.editing):
        draft.error = f"запрос с названием {name!r} уже есть"
        wizard.refresh()
        return

    entries = ensure_directions(workspace.settings, table.name)["READ"]
    # Сортировка и постраничность бывают только у выборки списка.
    many = draft.annotation == "many"

    def column(col) -> dict:
        described = {
            COLUMN_NAME_KEY: col.name,
            SHOW_KEY: col.name in draft.show,
            WHERE_KEY: col.name in draft.where,
            WHERE_OPTIONAL_KEY: col.name in draft.where_optional,
            # Незаполненное поле — это null, а не пустая строка: генератору
            # так видно, что значения нет, а не что оно пустое.
            EXACT_WHERE_KEY: (draft.exact.get(col.name) or "").strip() or None,
        }
        if many:
            described[ORDER_BY_KEY] = col.name in draft.order_by
            described[ORDER_BY_OPTIONAL_KEY] = col.name in draft.order_by_optional
        return described

    def joined_column(chain: str, alias: str, col) -> dict:
        key = (chain, alias, col.name)
        described = {
            JOIN_NAME_KEY: chain,
            JOIN_ALIAS_KEY: alias,
            COLUMN_NAME_KEY: col.name,
            SHOW_KEY: key in draft.joined_show,
            WHERE_KEY: key in draft.joined_where,
            WHERE_OPTIONAL_KEY: key in draft.joined_where_optional,
            EXACT_WHERE_KEY: (draft.joined_exact.get(key) or "").strip() or None,
        }
        if many:
            described[ORDER_BY_KEY] = key in draft.joined_order_by
            described[ORDER_BY_OPTIONAL_KEY] = key in draft.joined_order_by_optional
        return described

    links = _read_join_links(table, draft)

    entry = {
        NAME_KEY: name,
        ANNOTATION_KEY: draft.annotation,
        PAGINATION_KEY: many and draft.pagination,
    }
    # Ключи join'ов появляются только у выборок, которые их используют: у
    # остальных запись остаётся ровно такой, какой была до join'ов вовсе.
    if links:
        entry[USED_JOINS_KEY] = _used_joins(table, draft)
    entry[COLUMNS_KEY] = [column(col) for col in table.columns]
    if links:
        entry[JOINED_COLUMNS_KEY] = [
            joined_column(chain, alias, col)
            for chain, alias, joined in links
            for col in joined.columns
        ]
    entry[CUSTOM_WHERE_KEY] = (draft.custom_where or "").strip() or None
    entry[CUSTOM_QUERY_KEY] = (draft.custom_query or "").strip() or None

    if draft.editing is None:
        entries.append(entry)
    else:
        entries[draft.editing] = entry

    read_form = None
    wizard.refresh()


def _edit_read(index: int, table: Table, *, editing: bool = True) -> None:
    global read_form

    entry = entries_of(workspace.settings, table.name, "READ")[index]
    written = {col[COLUMN_NAME_KEY]: col for col in entry.get(COLUMNS_KEY, [])}
    joined = entry.get(JOINED_COLUMNS_KEY) or []

    def flagged(key: str) -> set[str]:
        return {name for name, col in written.items() if col.get(key)}

    def key_of(col: dict) -> tuple[str, str, str]:
        return (
            col.get(JOIN_NAME_KEY) or "",
            col.get(JOIN_ALIAS_KEY) or "",
            col.get(COLUMN_NAME_KEY) or "",
        )

    def joined_flagged(key: str) -> set[tuple[str, str, str]]:
        return {key_of(col) for col in joined if col.get(key)}

    read_form = ReadForm(
        table=table.name,
        name=entry.get(NAME_KEY, ""),
        annotation=entry.get(ANNOTATION_KEY, READ_ANNOTATIONS[0]),
        pagination=bool(entry.get(PAGINATION_KEY)),
        show=flagged(SHOW_KEY),
        where=flagged(WHERE_KEY),
        where_optional=flagged(WHERE_OPTIONAL_KEY),
        exact={
            name: col[EXACT_WHERE_KEY]
            for name, col in written.items()
            if col.get(EXACT_WHERE_KEY)
        },
        order_by=flagged(ORDER_BY_KEY),
        order_by_optional=flagged(ORDER_BY_OPTIONAL_KEY),
        joins=set(entry.get(USED_JOINS_KEY) or []),
        joined_show=joined_flagged(SHOW_KEY),
        joined_where=joined_flagged(WHERE_KEY),
        joined_where_optional=joined_flagged(WHERE_OPTIONAL_KEY),
        joined_exact={
            key_of(col): col[EXACT_WHERE_KEY]
            for col in joined
            if col.get(EXACT_WHERE_KEY)
        },
        joined_order_by=joined_flagged(ORDER_BY_KEY),
        joined_order_by_optional=joined_flagged(ORDER_BY_OPTIONAL_KEY),
        custom_where=entry.get(CUSTOM_WHERE_KEY) or "",
        custom_query=entry.get(CUSTOM_QUERY_KEY) or "",
        editing=index if editing else None,
    )
    wizard.refresh()


def _copy_read(index: int, table: Table) -> None:
    """Та же выборка новой записью — вместе с join'ами и их колонками."""
    _edit_read(index, table, editing=False)


def _remove_read(index: int, table: Table) -> None:
    global read_form

    del entries_of(workspace.settings, table.name, "READ")[index]
    if read_form is not None and read_form.editing == index:
        read_form = None
    wizard.refresh()


def _cancel_read_edit() -> None:
    global read_form

    read_form = None
    wizard.refresh()


def _read_form(table: Table) -> None:
    draft = read_form_for(table)

    def toggle(target: set, key, on: bool) -> None:
        target.add(key) if on else target.discard(key)

    def set_annotation(value: str) -> None:
        draft.annotation = value
        # Галка постраничности имеет смысл только у many — перерисовываем форму.
        wizard.refresh()

    def toggle_join(name: str, on: bool) -> None:
        # От включённой цепочки зависит состав формы: её колонки появляются
        # своей сеткой, — здесь перерисовка обязательна.
        toggle(draft.joins, name, on)
        wizard.refresh()

    ui.label("Название").classes("field-label q-mt-md")
    ui.input(
        value=draft.name, on_change=lambda e: setattr(draft, "name", e.value)
    ).props("outlined dense").classes("w-full q-mt-xs")
    _suggest_button(draft, lambda: suggest_read_name(table, draft))

    ui.label("Query Annotation").classes("field-label q-mt-md")
    with ui.row().classes("items-center gap-3 no-wrap q-mt-xs"):
        ui.select(
            list(READ_ANNOTATIONS),
            value=draft.annotation,
            on_change=lambda e: set_annotation(e.value),
        ).props("outlined dense").classes("w-48")
        ui.icon("help_outline").classes("help-icon").tooltip(ANNOTATION_HELP)
        if draft.annotation == "many":
            ui.checkbox(
                "Pagination",
                value=draft.pagination,
                on_change=lambda e: setattr(draft, "pagination", e.value),
            ).props("dense")

    # Цепочки показываем, только если они у таблицы описаны: у таблицы без
    # join'ов форма остаётся ровно такой, какой была.
    chains = joins_of(workspace.settings, table.name)
    if chains:
        ui.label("Join").classes("field-label q-mt-md")
        for chain in chains:
            name = (chain.get(NAME_KEY) or "").strip()
            with ui.row().classes("items-center gap-2 no-wrap q-mt-xs"):
                ui.checkbox(
                    name,
                    value=name in draft.joins,
                    on_change=lambda e, n=name: toggle_join(n, e.value),
                ).props("dense")
                ui.label(
                    " · ".join(
                        f"{link.get(JOIN_TYPE_KEY)} {link.get(JOIN_TABLE_KEY)} "
                        f"{link.get(JOIN_ALIAS_KEY)}"
                        for link in chain.get(LINKS_KEY) or []
                    )
                ).classes("hint")

    # Сортировка есть только у списка: у `one` строка одна, порядок ей ни к чему.
    many = draft.annotation == "many"
    grid = "read-order-grid" if many else "read-grid"

    def head() -> None:
        with ui.element("div").classes(f"grid-head {grid} q-mt-xs"):
            ui.label("поля")
            ui.label("показать")
            ui.label("добавить в WHERE")
            ui.label("WHERE OPTIONAL")
            ui.label("EXACT WHERE")
            if many:
                ui.label("ORDER BY")
                ui.label("ORDER BY OPTIONAL")

    def row(col, key, groups: tuple, exact: dict, caption: str) -> None:
        """Строка сетки. Ключ у своей колонки — имя, у приджойненной — тройка."""
        show, where, where_optional, order_by, order_by_optional = groups
        with ui.element("div").classes(f"grid-row {grid}"):
            with ui.column().classes("gap-0"):
                ui.label(col.name).classes("table-name")
                ui.label(caption).classes("hint")
            ui.checkbox(
                value=key in show,
                on_change=lambda e: toggle(show, key, e.value),
            ).props("dense")
            ui.checkbox(
                value=key in where,
                on_change=lambda e: toggle(where, key, e.value),
            ).props("dense")
            ui.checkbox(
                value=key in where_optional,
                on_change=lambda e: toggle(where_optional, key, e.value),
            ).props("dense")
            ui.input(
                value=exact.get(key, ""),
                on_change=lambda e: exact.__setitem__(key, e.value),
            ).props("outlined dense")
            if many:
                ui.checkbox(
                    value=key in order_by,
                    on_change=lambda e: toggle(order_by, key, e.value),
                ).props("dense")
                ui.checkbox(
                    value=key in order_by_optional,
                    on_change=lambda e: toggle(order_by_optional, key, e.value),
                ).props("dense")

    own = (
        draft.show,
        draft.where,
        draft.where_optional,
        draft.order_by,
        draft.order_by_optional,
    )
    joined = (
        draft.joined_show,
        draft.joined_where,
        draft.joined_where_optional,
        draft.joined_order_by,
        draft.joined_order_by_optional,
    )

    ui.label("Поля").classes("field-label q-mt-md")
    head()
    for col in table.columns:
        row(col, col.name, own, draft.exact, col.sql_type)

    # Каждое звено — своей сеткой под своим алиасом: колонки разных таблиц в
    # одном списке различались бы только именем, а имена у них совпадают.
    links = _read_join_links(table, draft)
    for chain, alias, joined_table in links:
        with ui.row().classes("items-baseline gap-2 no-wrap q-mt-md"):
            ui.label(f"{alias} · {joined_table.name}").classes("field-label")
            ui.label(f"join {chain}").classes("hint")
        head()
        for col in joined_table.columns:
            row(
                col,
                (chain, alias, col.name),
                joined,
                draft.joined_exact,
                f"{col.sql_type} → {alias}_{col.name}",
            )

    if links:
        ui.label(JOIN_READ_HELP).classes("hint q-mt-xs")

    if many:
        ui.label(ORDER_BY_HELP).classes("hint q-mt-xs")

    ui.label("Custom WHERE").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_where,
        on_change=lambda e: setattr(draft, "custom_where", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")
    ui.label(CUSTOM_WHERE_HELP).classes("hint q-mt-xs")

    ui.label("Custom Query").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_query,
        on_change=lambda e: setattr(draft, "custom_query", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")

    if draft.error:
        ui.label(draft.error).classes("error-text q-mt-sm")

    with ui.row().classes("w-full justify-end q-mt-md"):
        if draft.editing is not None:
            ui.button(
                "Отменить правку", on_click=_cancel_read_edit, color=None
            ).props("flat no-caps").classes("btn-secondary")
        ui.button(
            "Сохранить" if draft.editing is not None else "Добавить",
            on_click=lambda: _submit_read(table),
            color=None,
        ).props("unelevated no-caps").classes("btn-primary")


def _read_list(table: Table) -> None:
    """Добавленные выборки этой таблицы — зафиксированными значениями."""
    entries = entries_of(workspace.settings, table.name, "READ")
    if not entries:
        return

    with ui.element("div").classes("card"):
        ui.label(f"Добавленные запросы · {len(entries)}").classes("field-label")

        for index, entry in enumerate(entries):
            editing = read_form is not None and read_form.editing == index
            columns = entry.get(COLUMNS_KEY, [])
            joined = entry.get(JOINED_COLUMNS_KEY) or []

            def named(col: dict) -> str:
                """Приджойненную колонку называем с алиасом: `id` бывает у обеих."""
                alias = col.get(JOIN_ALIAS_KEY)
                return f"{alias}.{col[COLUMN_NAME_KEY]}" if alias else col[COLUMN_NAME_KEY]

            def names(key: str) -> str:
                picked = [named(c) for c in [*columns, *joined] if c.get(key)]
                return ", ".join(picked) or "—"

            exact = [
                f"{named(c)} = {c[EXACT_WHERE_KEY]}"
                for c in [*columns, *joined]
                if c.get(EXACT_WHERE_KEY)
            ]

            with ui.element("div").classes("record editing" if editing else "record"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(entry.get(NAME_KEY, "")).classes("table-name")
                    ui.label(f":{entry.get(ANNOTATION_KEY, '')}").classes("hint")
                    if entry.get(PAGINATION_KEY):
                        ui.label("pagination").classes("ok-badge")
                    ui.space()
                    ui.button(
                        "Редактировать",
                        on_click=lambda i=index: _edit_read(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Скопировать",
                        on_click=lambda i=index: _copy_read(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Удалить",
                        on_click=lambda i=index: _remove_read(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn danger")

                lines = []
                # Строку join'ов пишем только у выборок, где они есть: у
                # остальных это был бы прочерк ни о чём.
                used = entry.get(USED_JOINS_KEY) or []
                if used:
                    lines.append(("JOIN", ", ".join(used)))
                lines += [
                    ("показать", names(SHOW_KEY)),
                    ("WHERE", names(WHERE_KEY)),
                    ("WHERE OPTIONAL", names(WHERE_OPTIONAL_KEY)),
                    ("EXACT WHERE", ", ".join(exact) or "—"),
                ]
                # Сортировка записана только у списка — у `one` этих строк нет.
                if entry.get(ANNOTATION_KEY) == "many":
                    lines += [
                        ("ORDER BY", names(ORDER_BY_KEY)),
                        ("ORDER BY OPTIONAL", names(ORDER_BY_OPTIONAL_KEY)),
                    ]
                lines += [
                    ("Custom WHERE", entry.get(CUSTOM_WHERE_KEY) or "—"),
                    ("Custom Query", entry.get(CUSTOM_QUERY_KEY) or "—"),
                ]

                for caption, value in lines:
                    with ui.element("div").classes("record-row"):
                        ui.label(caption).classes("hint")
                        ui.label(value).classes("record-value")


# ---------------------------------------------------------------- форма Update


@dataclass
class UpdateForm:
    """Черновик одного изменения. Живёт до нажатия «Добавить»."""

    table: str
    name: str = ""
    annotation: str = UPDATE_ANNOTATIONS[0]
    # По умолчанию меняем всё, не фильтруем ничего.
    sets: set[str] = field(default_factory=set)
    set_values: dict[str, str] = field(default_factory=dict)
    where: set[str] = field(default_factory=set)
    where_optional: set[str] = field(default_factory=set)
    where_values: dict[str, str] = field(default_factory=dict)
    custom_where: str = ""
    custom_query: str = ""
    error: str | None = None
    editing: int | None = None


update_form: UpdateForm | None = None


def update_form_for(table: Table) -> UpdateForm:
    global update_form
    if update_form is None or update_form.table != table.name:
        update_form = UpdateForm(
            table=table.name,
            sets={col.name for col in table.columns},
        )
    return update_form


def _submit_update(table: Table) -> None:
    global update_form

    draft = update_form_for(table)
    name = (draft.name or "").strip()
    if not name:
        draft.error = "укажите название"
        wizard.refresh()
        return

    if _name_taken(name, table.name, "UPDATE", skip=draft.editing):
        draft.error = f"запрос с названием {name!r} уже есть"
        wizard.refresh()
        return

    entries = ensure_directions(workspace.settings, table.name)["UPDATE"]
    entry = {
        NAME_KEY: name,
        ANNOTATION_KEY: draft.annotation,
        COLUMNS_KEY: [
            {
                COLUMN_NAME_KEY: col.name,
                SET_KEY: col.name in draft.sets,
                # Незаполненное значение изменения — это параметр запроса, как в
                # CREATE: пишем `@имя_колонки`, а не null.
                SET_VALUE_KEY: (draft.set_values.get(col.name) or "").strip()
                or f"@{col.name}",
                WHERE_KEY: col.name in draft.where,
                WHERE_OPTIONAL_KEY: col.name in draft.where_optional,
                WHERE_VALUE_KEY: (draft.where_values.get(col.name) or "").strip() or None,
            }
            for col in table.columns
        ],
        CUSTOM_WHERE_KEY: (draft.custom_where or "").strip() or None,
        CUSTOM_QUERY_KEY: (draft.custom_query or "").strip() or None,
    }

    if draft.editing is None:
        entries.append(entry)
    else:
        entries[draft.editing] = entry

    update_form = None
    wizard.refresh()


def _edit_update(index: int, table: Table, *, editing: bool = True) -> None:
    global update_form

    entry = entries_of(workspace.settings, table.name, "UPDATE")[index]
    written = {col[COLUMN_NAME_KEY]: col for col in entry.get(COLUMNS_KEY, [])}

    def flagged(key: str) -> set[str]:
        return {name for name, col in written.items() if col.get(key)}

    def filled(key: str) -> dict[str, str]:
        return {name: col[key] for name, col in written.items() if col.get(key)}

    def written_values(key: str) -> dict[str, str]:
        """Как `filled`, но `@имя` не показываем: это «приходит параметром»."""
        return {
            name: value
            for name, value in filled(key).items()
            if value != f"@{name}"
        }

    update_form = UpdateForm(
        table=table.name,
        name=entry.get(NAME_KEY, ""),
        annotation=entry.get(ANNOTATION_KEY, UPDATE_ANNOTATIONS[0]),
        sets=flagged(SET_KEY),
        set_values=written_values(SET_VALUE_KEY),
        where=flagged(WHERE_KEY),
        where_optional=flagged(WHERE_OPTIONAL_KEY),
        where_values=filled(WHERE_VALUE_KEY),
        custom_where=entry.get(CUSTOM_WHERE_KEY) or "",
        custom_query=entry.get(CUSTOM_QUERY_KEY) or "",
        editing=index if editing else None,
    )
    wizard.refresh()


def _copy_update(index: int, table: Table) -> None:
    """То же изменение новой записью: сохранение ляжет рядом с исходным."""
    _edit_update(index, table, editing=False)


def _remove_update(index: int, table: Table) -> None:
    global update_form

    del entries_of(workspace.settings, table.name, "UPDATE")[index]
    if update_form is not None and update_form.editing == index:
        update_form = None
    wizard.refresh()


def _cancel_update_edit() -> None:
    global update_form

    update_form = None
    wizard.refresh()


def _update_form(table: Table) -> None:
    draft = update_form_for(table)

    def toggle(target: set[str], column: str, on: bool) -> None:
        target.add(column) if on else target.discard(column)

    ui.label("Название").classes("field-label q-mt-md")
    ui.input(
        value=draft.name, on_change=lambda e: setattr(draft, "name", e.value)
    ).props("outlined dense").classes("w-full q-mt-xs")
    _suggest_button(draft, lambda: suggest_update_name(table, draft))

    ui.label("Query Annotation").classes("field-label q-mt-md")
    with ui.row().classes("items-center gap-2 no-wrap q-mt-xs"):
        ui.select(
            list(UPDATE_ANNOTATIONS),
            value=draft.annotation,
            on_change=lambda e: setattr(draft, "annotation", e.value),
        ).props("outlined dense").classes("w-48")
        ui.icon("help_outline").classes("help-icon").tooltip(ANNOTATION_HELP)

    ui.label("Поля").classes("field-label q-mt-md")
    with ui.element("div").classes("grid-head update-grid q-mt-xs"):
        ui.label("поля")
        ui.label("изменения")
        ui.label("значение изменения")
        ui.label("WHERE")
        ui.label("Optional WHERE")
        ui.label("значение WHERE")

    for col in table.columns:
        with ui.element("div").classes("grid-row update-grid"):
            with ui.column().classes("gap-0"):
                ui.label(col.name).classes("table-name")
                ui.label(col.sql_type).classes("hint")
            ui.checkbox(
                value=col.name in draft.sets,
                on_change=lambda e, c=col.name: toggle(draft.sets, c, e.value),
            ).props("dense")
            ui.input(
                value=draft.set_values.get(col.name, ""),
                on_change=lambda e, c=col.name: draft.set_values.__setitem__(c, e.value),
            ).props("outlined dense")
            ui.checkbox(
                value=col.name in draft.where,
                on_change=lambda e, c=col.name: toggle(draft.where, c, e.value),
            ).props("dense")
            ui.checkbox(
                value=col.name in draft.where_optional,
                on_change=lambda e, c=col.name: toggle(draft.where_optional, c, e.value),
            ).props("dense")
            ui.input(
                value=draft.where_values.get(col.name, ""),
                on_change=lambda e, c=col.name: draft.where_values.__setitem__(c, e.value),
            ).props("outlined dense")

    ui.label("Custom WHERE").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_where,
        on_change=lambda e: setattr(draft, "custom_where", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")
    ui.label(CUSTOM_WHERE_HELP).classes("hint q-mt-xs")

    ui.label("Custom Query").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_query,
        on_change=lambda e: setattr(draft, "custom_query", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")

    if draft.error:
        ui.label(draft.error).classes("error-text q-mt-sm")

    with ui.row().classes("w-full justify-end q-mt-md"):
        if draft.editing is not None:
            ui.button(
                "Отменить правку", on_click=_cancel_update_edit, color=None
            ).props("flat no-caps").classes("btn-secondary")
        ui.button(
            "Сохранить" if draft.editing is not None else "Добавить",
            on_click=lambda: _submit_update(table),
            color=None,
        ).props("unelevated no-caps").classes("btn-primary")


def _update_list(table: Table) -> None:
    """Добавленные изменения этой таблицы — зафиксированными значениями."""
    entries = entries_of(workspace.settings, table.name, "UPDATE")
    if not entries:
        return

    with ui.element("div").classes("card"):
        ui.label(f"Добавленные запросы · {len(entries)}").classes("field-label")

        for index, entry in enumerate(entries):
            editing = update_form is not None and update_form.editing == index
            columns = entry.get(COLUMNS_KEY, [])

            def listed(flag: str, value_key: str) -> str:
                parts = [
                    c[COLUMN_NAME_KEY] + (f" = {c[value_key]}" if c.get(value_key) else "")
                    for c in columns
                    if c.get(flag)
                ]
                return ", ".join(parts) or "—"

            with ui.element("div").classes("record editing" if editing else "record"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(entry.get(NAME_KEY, "")).classes("table-name")
                    ui.label(f":{entry.get(ANNOTATION_KEY, '')}").classes("hint")
                    ui.space()
                    ui.button(
                        "Редактировать",
                        on_click=lambda i=index: _edit_update(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Скопировать",
                        on_click=lambda i=index: _copy_update(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Удалить",
                        on_click=lambda i=index: _remove_update(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn danger")

                for caption, value in (
                    ("изменения", listed(SET_KEY, SET_VALUE_KEY)),
                    ("WHERE", listed(WHERE_KEY, WHERE_VALUE_KEY)),
                    (
                        "Optional WHERE",
                        listed(WHERE_OPTIONAL_KEY, WHERE_VALUE_KEY),
                    ),
                    ("Custom WHERE", entry.get(CUSTOM_WHERE_KEY) or "—"),
                    ("Custom Query", entry.get(CUSTOM_QUERY_KEY) or "—"),
                ):
                    with ui.element("div").classes("record-row"):
                        ui.label(caption).classes("hint")
                        ui.label(value).classes("record-value")


# ---------------------------------------------------------------- форма Delete


@dataclass
class DeleteForm:
    """Черновик одного удаления. Живёт до нажатия «Добавить»."""

    table: str
    name: str = ""
    mode: str = HARD_DELETE
    # Колонки мягкого и обратного удаления: по умолчанию не отмечена ни одна.
    # Проставляют обычно две-три служебные колонки, а не всю таблицу, — отмечать
    # заранее все значило бы заставлять снимать лишние галки руками.
    sets: set[str] = field(default_factory=set)
    set_values: dict[str, str] = field(default_factory=dict)
    where: set[str] = field(default_factory=set)
    where_optional: set[str] = field(default_factory=set)
    where_values: dict[str, str] = field(default_factory=dict)
    custom_where: str = ""
    custom_query: str = ""
    error: str | None = None
    editing: int | None = None


delete_form: DeleteForm | None = None


def delete_form_for(table: Table) -> DeleteForm:
    global delete_form
    if delete_form is None or delete_form.table != table.name:
        delete_form = DeleteForm(table=table.name)
    return delete_form


def _submit_delete(table: Table) -> None:
    global delete_form

    draft = delete_form_for(table)
    name = (draft.name or "").strip()
    if not name:
        draft.error = "укажите название"
        wizard.refresh()
        return

    if _name_taken(name, table.name, "DELETE", skip=draft.editing):
        draft.error = f"запрос с названием {name!r} уже есть"
        wizard.refresh()
        return

    soft = draft.mode in SET_MODES

    def column(col) -> dict:
        described = {COLUMN_NAME_KEY: col.name}
        if soft:
            # Физическое удаление ничего не проставляет — этих ключей у него нет.
            described[SET_KEY] = col.name in draft.sets
            described[SET_VALUE_KEY] = (
                draft.set_values.get(col.name) or ""
            ).strip() or None
        described[WHERE_KEY] = col.name in draft.where
        described[WHERE_OPTIONAL_KEY] = col.name in draft.where_optional
        described[WHERE_VALUE_KEY] = (
            draft.where_values.get(col.name) or ""
        ).strip() or None
        return described

    entries = ensure_directions(workspace.settings, table.name)["DELETE"]
    entry = {
        NAME_KEY: name,
        MODE_KEY: draft.mode,
        COLUMNS_KEY: [column(col) for col in table.columns],
        CUSTOM_WHERE_KEY: (draft.custom_where or "").strip() or None,
        CUSTOM_QUERY_KEY: (draft.custom_query or "").strip() or None,
    }

    if draft.editing is None:
        entries.append(entry)
    else:
        entries[draft.editing] = entry

    delete_form = None
    wizard.refresh()


def _edit_delete(index: int, table: Table, *, editing: bool = True) -> None:
    global delete_form

    entry = entries_of(workspace.settings, table.name, "DELETE")[index]
    written = {col[COLUMN_NAME_KEY]: col for col in entry.get(COLUMNS_KEY, [])}
    mode = entry.get(MODE_KEY, HARD_DELETE)

    def flagged(key: str) -> set[str]:
        return {name for name, col in written.items() if col.get(key)}

    def filled(key: str) -> dict[str, str]:
        return {name: col[key] for name, col in written.items() if col.get(key)}

    delete_form = DeleteForm(
        table=table.name,
        name=entry.get(NAME_KEY, ""),
        mode=mode,
        # У физического удаления колонок изменения нет вовсе — там и брать нечего.
        sets=flagged(SET_KEY),
        set_values=filled(SET_VALUE_KEY),
        where=flagged(WHERE_KEY),
        where_optional=flagged(WHERE_OPTIONAL_KEY),
        where_values=filled(WHERE_VALUE_KEY),
        custom_where=entry.get(CUSTOM_WHERE_KEY) or "",
        custom_query=entry.get(CUSTOM_QUERY_KEY) or "",
        editing=index if editing else None,
    )
    wizard.refresh()


def _copy_delete(index: int, table: Table) -> None:
    """То же удаление новой записью — вместе с режимом и его колонками."""
    _edit_delete(index, table, editing=False)


def _remove_delete(index: int, table: Table) -> None:
    global delete_form

    del entries_of(workspace.settings, table.name, "DELETE")[index]
    if delete_form is not None and delete_form.editing == index:
        delete_form = None
    wizard.refresh()


def _cancel_delete_edit() -> None:
    global delete_form

    delete_form = None
    wizard.refresh()


def _delete_form(table: Table) -> None:
    draft = delete_form_for(table)

    def toggle(target: set[str], column: str, on: bool) -> None:
        target.add(column) if on else target.discard(column)

    def set_mode(value: str) -> None:
        draft.mode = value
        # Набор колонок у режимов разный — перерисовываем форму целиком.
        wizard.refresh()

    soft = draft.mode in SET_MODES

    ui.label("Название").classes("field-label q-mt-md")
    ui.input(
        value=draft.name, on_change=lambda e: setattr(draft, "name", e.value)
    ).props("outlined dense").classes("w-full q-mt-xs")
    _suggest_button(draft, lambda: suggest_delete_name(table, draft))

    ui.label("Режим").classes("field-label q-mt-md")
    ui.select(
        list(DELETE_MODES),
        value=draft.mode,
        on_change=lambda e: set_mode(e.value),
    ).props("outlined dense").classes("w-64 q-mt-xs")

    ui.label("Поля").classes("field-label q-mt-md")
    grid = "update-grid" if soft else "delete-grid"
    with ui.element("div").classes(f"grid-head {grid} q-mt-xs"):
        ui.label("поля")
        if soft:
            ui.label("изменения")
            ui.label("значение изменения")
        ui.label("WHERE")
        ui.label("Optional WHERE")
        ui.label("значение WHERE")

    for col in table.columns:
        with ui.element("div").classes(f"grid-row {grid}"):
            with ui.column().classes("gap-0"):
                ui.label(col.name).classes("table-name")
                ui.label(col.sql_type).classes("hint")
            if soft:
                ui.checkbox(
                    value=col.name in draft.sets,
                    on_change=lambda e, c=col.name: toggle(draft.sets, c, e.value),
                ).props("dense")
                ui.input(
                    value=draft.set_values.get(col.name, ""),
                    on_change=lambda e, c=col.name: draft.set_values.__setitem__(
                        c, e.value
                    ),
                ).props("outlined dense")
            ui.checkbox(
                value=col.name in draft.where,
                on_change=lambda e, c=col.name: toggle(draft.where, c, e.value),
            ).props("dense")
            ui.checkbox(
                value=col.name in draft.where_optional,
                on_change=lambda e, c=col.name: toggle(draft.where_optional, c, e.value),
            ).props("dense")
            ui.input(
                value=draft.where_values.get(col.name, ""),
                on_change=lambda e, c=col.name: draft.where_values.__setitem__(
                    c, e.value
                ),
            ).props("outlined dense")

    ui.label("Custom WHERE").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_where,
        on_change=lambda e: setattr(draft, "custom_where", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")
    ui.label(CUSTOM_WHERE_HELP).classes("hint q-mt-xs")

    ui.label("Custom Query").classes("field-label q-mt-md")
    ui.textarea(
        value=draft.custom_query,
        on_change=lambda e: setattr(draft, "custom_query", e.value),
    ).props("outlined dense autogrow").classes("w-full q-mt-xs")

    if draft.error:
        ui.label(draft.error).classes("error-text q-mt-sm")

    with ui.row().classes("w-full justify-end q-mt-md"):
        if draft.editing is not None:
            ui.button(
                "Отменить правку", on_click=_cancel_delete_edit, color=None
            ).props("flat no-caps").classes("btn-secondary")
        ui.button(
            "Сохранить" if draft.editing is not None else "Добавить",
            on_click=lambda: _submit_delete(table),
            color=None,
        ).props("unelevated no-caps").classes("btn-primary")


def _delete_list(table: Table) -> None:
    """Добавленные удаления этой таблицы — зафиксированными значениями."""
    entries = entries_of(workspace.settings, table.name, "DELETE")
    if not entries:
        return

    with ui.element("div").classes("card"):
        ui.label(f"Добавленные запросы · {len(entries)}").classes("field-label")

        for index, entry in enumerate(entries):
            editing = delete_form is not None and delete_form.editing == index
            columns = entry.get(COLUMNS_KEY, [])
            soft = entry.get(MODE_KEY) in SET_MODES

            def listed(flag: str, value_key: str) -> str:
                parts = [
                    c[COLUMN_NAME_KEY] + (f" = {c[value_key]}" if c.get(value_key) else "")
                    for c in columns
                    if c.get(flag)
                ]
                return ", ".join(parts) or "—"

            with ui.element("div").classes("record editing" if editing else "record"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(entry.get(NAME_KEY, "")).classes("table-name")
                    ui.label(entry.get(MODE_KEY, "")).classes("hint")
                    ui.space()
                    ui.button(
                        "Редактировать",
                        on_click=lambda i=index: _edit_delete(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Скопировать",
                        on_click=lambda i=index: _copy_delete(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Удалить",
                        on_click=lambda i=index: _remove_delete(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn danger")

                lines = []
                if soft:
                    lines.append(("изменения", listed(SET_KEY, SET_VALUE_KEY)))
                lines += [
                    ("WHERE", listed(WHERE_KEY, WHERE_VALUE_KEY)),
                    ("Optional WHERE", listed(WHERE_OPTIONAL_KEY, WHERE_VALUE_KEY)),
                    ("Custom WHERE", entry.get(CUSTOM_WHERE_KEY) or "—"),
                    ("Custom Query", entry.get(CUSTOM_QUERY_KEY) or "—"),
                ]
                for caption, value in lines:
                    with ui.element("div").classes("record-row"):
                        ui.label(caption).classes("hint")
                        ui.label(value).classes("record-value")


# ------------------------------------------------------------------ форма Join


@dataclass
class JoinLink:
    """Звено цепочки: к какой таблице и по какому условию присоединяемся."""

    type: str = JOIN_TYPES[0]
    table: str = ""
    alias: str = ""
    on: str = ""


@dataclass
class JoinForm:
    """Черновик одной цепочки. Живёт до нажатия «Добавить»."""

    table: str
    name: str = ""
    links: list[JoinLink] = field(default_factory=lambda: [JoinLink()])
    error: str | None = None
    # Индекс правимой цепочки в JOINS или None, если это новая.
    editing: int | None = None


join_form: JoinForm | None = None


def join_form_for(table: Table) -> JoinForm:
    global join_form
    if join_form is None or join_form.table != table.name:
        join_form = JoinForm(table=table.name)
    return join_form


def suggest_alias(draft: JoinForm, table: Table, joined: str) -> str:
    """Алиас по имени таблицы: `dc."order"` -> `order`, а занятый — `order2`.

    Пустая строка означает «сами не придумали»: короткое имя бывает словом SQL
    (`user`), а такой алиас не годится — из него собираются имена параметров.
    """
    short = joined.split(".")[-1].strip('"').lower()
    if not is_alias(short):
        return ""

    taken = {table.short_name} | {link.alias for link in draft.links if link.alias}
    if short not in taken:
        return short
    for number in range(2, 10):
        if f"{short}{number}" not in taken:
            return f"{short}{number}"
    return ""


def _add_link() -> None:
    """Ещё одно звено: связь «многие ко многим» — это связующая и целевая таблицы."""
    if join_form is not None:
        join_form.links.append(JoinLink())
    wizard.refresh()


def _remove_link(index: int) -> None:
    del join_form.links[index]
    # Цепочка без звеньев — не цепочка: пустую форму заводим заново.
    if not join_form.links:
        join_form.links.append(JoinLink())
    wizard.refresh()


def _set_link_table(draft: JoinForm, link: JoinLink, table: Table, value: str) -> None:
    """Выбор таблицы подставляет алиас, пока его не написали руками."""
    link.table = value
    if not link.alias:
        link.alias = suggest_alias(draft, table, value)
    wizard.refresh()


def _join_name_taken(table: str, name: str, skip: int | None = None) -> bool:
    """Имена цепочек уникальны в пределах таблицы: в sqlc они не попадают."""
    for index, chain in enumerate(joins_of(workspace.settings, table)):
        if index != skip and (chain.get(NAME_KEY) or "").strip() == name:
            return True
    return False


def _submit_join(table: Table) -> None:
    global join_form

    draft = join_form_for(table)
    name = (draft.name or "").strip()
    if not name:
        draft.error = "укажите название"
        wizard.refresh()
        return

    if _join_name_taken(table.name, name, skip=draft.editing):
        draft.error = f"join с названием {name!r} у таблицы уже есть"
        wizard.refresh()
        return

    known = {item.name for item in workspace.tables}
    # Алиас не должен сталкиваться ни с соседним звеном, ни с именем своей
    # таблицы: `FROM dc."user" ... JOIN dc.role "user"` Postgres не примет.
    aliases = {table.short_name}
    links = []
    for number, link in enumerate(draft.links, start=1):
        if link.table not in known:
            draft.error = f"звено {number}: выберите таблицу"
            wizard.refresh()
            return

        alias = (link.alias or "").strip()
        if not is_alias(alias):
            draft.error = (
                f"звено {number}: алиас {alias!r} не годится — нужно простое имя "
                "латиницей, не совпадающее со словом SQL"
            )
            wizard.refresh()
            return
        if alias in aliases:
            draft.error = f"звено {number}: алиас {alias!r} уже занят"
            wizard.refresh()
            return

        on = (link.on or "").strip()
        if not on:
            draft.error = f"звено {number}: напишите условие ON"
            wizard.refresh()
            return

        aliases.add(alias)
        links.append(
            {
                JOIN_TYPE_KEY: link.type,
                JOIN_TABLE_KEY: link.table,
                JOIN_ALIAS_KEY: alias,
                JOIN_ON_KEY: on,
            }
        )

    chains = ensure_joins(workspace.settings, table.name)
    chain = {NAME_KEY: name, LINKS_KEY: links}
    if draft.editing is None:
        chains.append(chain)
    else:
        previous = (chains[draft.editing].get(NAME_KEY) or "").strip()
        chains[draft.editing] = chain
        if previous != name:
            _rename_join(table.name, previous, name)

    join_form = None
    wizard.refresh()


def _rename_join(table: str, old: str, new: str) -> None:
    """Выборки ссылаются на цепочку по имени — переименование ведём за собой."""
    for entry in entries_of(workspace.settings, table, "READ"):
        if USED_JOINS_KEY in entry:
            entry[USED_JOINS_KEY] = [
                new if used == old else used for used in entry[USED_JOINS_KEY]
            ]
        for col in entry.get(JOINED_COLUMNS_KEY) or []:
            if col.get(JOIN_NAME_KEY) == old:
                col[JOIN_NAME_KEY] = new


def _forget_join(table: str, name: str) -> None:
    """Убирает удалённую цепочку из выборок: ссылка на неё сорвёт генерацию."""
    for entry in entries_of(workspace.settings, table, "READ"):
        if USED_JOINS_KEY not in entry:
            continue
        entry[USED_JOINS_KEY] = [used for used in entry[USED_JOINS_KEY] if used != name]
        entry[JOINED_COLUMNS_KEY] = [
            col
            for col in entry.get(JOINED_COLUMNS_KEY) or []
            if col.get(JOIN_NAME_KEY) != name
        ]


def _edit_join(index: int, table: Table, *, editing: bool = True) -> None:
    """Загружает цепочку обратно в форму — правкой или копией.

    Имя, как и у запросов, переносится как есть: оно уникально в пределах
    таблицы, и придумывать за автора новое здесь нечего.
    """
    global join_form

    chain = joins_of(workspace.settings, table.name)[index]
    join_form = JoinForm(
        table=table.name,
        name=chain.get(NAME_KEY, ""),
        links=[
            JoinLink(
                type=(link.get(JOIN_TYPE_KEY) or JOIN_TYPES[0]),
                table=link.get(JOIN_TABLE_KEY) or "",
                alias=link.get(JOIN_ALIAS_KEY) or "",
                on=link.get(JOIN_ON_KEY) or "",
            )
            for link in chain.get(LINKS_KEY) or []
        ]
        or [JoinLink()],
        editing=index if editing else None,
    )
    wizard.refresh()


def _copy_join(index: int, table: Table) -> None:
    """Та же цепочка новой записью: сохранение ляжет рядом с исходной.

    Цепочки соседних таблиц часто отличаются одним звеном — копию быстрее
    поправить, чем набрать заново.
    """
    _edit_join(index, table, editing=False)


def _remove_join(index: int, table: Table) -> None:
    global join_form

    chains = joins_of(workspace.settings, table.name)
    name = (chains[index].get(NAME_KEY) or "").strip()
    del chains[index]
    _forget_join(table.name, name)
    if join_form is not None and join_form.editing == index:
        join_form = None
    wizard.refresh()


def _cancel_join_edit() -> None:
    global join_form

    join_form = None
    wizard.refresh()


def _join_form(table: Table) -> None:
    draft = join_form_for(table)
    names = [item.name for item in workspace.tables]

    ui.label("Название").classes("field-label q-mt-md")
    ui.input(
        value=draft.name, on_change=lambda e: setattr(draft, "name", e.value)
    ).props("outlined dense").classes("w-full q-mt-xs")
    ui.label(JOIN_HELP).classes("hint q-mt-xs")

    for index, link in enumerate(draft.links):
        with ui.element("div").classes("record"):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(f"звено {index + 1}").classes("field-label")
                ui.space()
                if len(draft.links) > 1:
                    ui.button(
                        "Убрать",
                        on_click=lambda i=index: _remove_link(i),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn danger")

            with ui.row().classes("w-full items-center gap-2 no-wrap q-mt-xs"):
                ui.select(
                    list(JOIN_TYPES),
                    value=link.type,
                    on_change=lambda e, l=link: setattr(l, "type", e.value),
                ).props("outlined dense").classes("w-32")
                ui.select(
                    names,
                    value=link.table or None,
                    on_change=lambda e, l=link: _set_link_table(draft, l, table, e.value),
                ).props("outlined dense").classes("grow")
                ui.input(
                    value=link.alias,
                    placeholder="алиас",
                    on_change=lambda e, l=link: setattr(l, "alias", e.value),
                ).props("outlined dense").classes("w-32")

            ui.label("ON").classes("field-label q-mt-sm")
            ui.textarea(
                value=link.on,
                on_change=lambda e, l=link: setattr(l, "on", e.value),
            ).props("outlined dense autogrow").classes("w-full q-mt-xs")
            ui.label(
                f"Условие пишется руками. Своя таблица в нём — "
                f"{ident(table.short_name)}, приджойненная — под своим алиасом."
            ).classes("hint q-mt-xs")

    with ui.row().classes("w-full q-mt-sm"):
        ui.button("Добавить таблицу", on_click=_add_link, color=None).props(
            "flat no-caps dense"
        ).classes("crud-btn")

    if draft.error:
        ui.label(draft.error).classes("error-text q-mt-sm")

    with ui.row().classes("w-full justify-end q-mt-md"):
        if draft.editing is not None:
            ui.button(
                "Отменить правку", on_click=_cancel_join_edit, color=None
            ).props("flat no-caps").classes("btn-secondary")
        ui.button(
            "Сохранить" if draft.editing is not None else "Добавить",
            on_click=lambda: _submit_join(table),
            color=None,
        ).props("unelevated no-caps").classes("btn-primary")


def _join_list(table: Table) -> None:
    """Добавленные цепочки этой таблицы — звеньями, в порядке соединения."""
    chains = joins_of(workspace.settings, table.name)
    if not chains:
        return

    with ui.element("div").classes("card"):
        ui.label(f"Добавленные join'ы · {len(chains)}").classes("field-label")

        for index, chain in enumerate(chains):
            editing = join_form is not None and join_form.editing == index
            with ui.element("div").classes("record editing" if editing else "record"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.label(chain.get(NAME_KEY, "")).classes("table-name")
                    ui.space()
                    ui.button(
                        "Редактировать",
                        on_click=lambda i=index: _edit_join(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Скопировать",
                        on_click=lambda i=index: _copy_join(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn")
                    ui.button(
                        "Удалить",
                        on_click=lambda i=index: _remove_join(i, table),
                        color=None,
                    ).props("flat no-caps dense").classes("crud-btn danger")

                for link in chain.get(LINKS_KEY) or []:
                    with ui.element("div").classes("record-row"):
                        ui.label(
                            f"{link.get(JOIN_TYPE_KEY)} JOIN "
                            f"{link.get(JOIN_TABLE_KEY)} {link.get(JOIN_ALIAS_KEY)}"
                        ).classes("hint")
                        ui.label(f"ON {link.get(JOIN_ON_KEY)}").classes("record-value")


def _finish_row() -> None:
    with ui.row().classes("w-full q-mt-md"):
        ui.button(
            "Сохранить JSON", on_click=_save_settings, color=None
        ).props("unelevated no-caps").classes("btn-primary w-full")


# ---------------------------------------------------------------- шаги


@ui.refreshable
def wizard() -> None:
    if workspace.tables is not None:
        _summary_card()
        with ui.row().classes("w-full no-wrap gap-4 q-mt-md items-start"):
            with ui.column().classes("gap-0"):
                _sidebar()
                _finish_row()
            _detail()
        return

    _step_head(
        "Шаг 1 · схема",
        "Папка, в которой лежит DDL",
        f"Программа возьмёт из неё {SCHEMA_FILENAME} и разберёт таблицы.",
    )
    _folder_card()

    if workspace.folder is None:
        return

    _step_head(
        "Шаг 2 · protobuf",
        "Куда сохранить .proto",
        "Файл контракта для gRPC. Программа затирает его целиком при каждой "
        "генерации — править руками бессмысленно.",
    )
    _proto_card()

    # Шапку .proto спрашиваем сразу за путём: без файла вопрос беспредметен,
    # а package подсказывается по go-пакету, поэтому идёт следом за ним.
    if workspace.proto is not None:
        _go_package_card()
    if workspace.go_package is not None:
        _proto_package_card()

    if workspace.prepare_error:
        ui.label(workspace.prepare_error).classes("error-text q-mt-md")


# ---------------------------------------------------------------- сборка


def build() -> None:
    """Регистрирует статику и страницы приложения."""
    app.add_static_files("/assets", str(ASSETS))

    @ui.page("/")
    def index() -> None:
        ui.add_head_html(STYLES)
        ui.colors(primary=ACCENT)

        with ui.header().classes("app-header"):
            with ui.element("div").classes("container"):
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.html(
                        f'<img class="app-logo" src="{LOGO}" width="54" height="62" '
                        'alt="SG Buddy">'
                    )
                    ui.label("SG Buddy").classes("app-title")
                    ui.space()
                    ui.button(
                        "Начать заново", on_click=reset_all, color=None
                    ).props("flat no-caps").classes("btn-ghost")

        # NiceGUI сама оборачивает содержимое страницы в <main> — второй не нужен.
        with ui.element("div").classes("container"):
            wizard()

        # fixed=False: подвал стоит под страницей, а не прилипает к низу окна —
        # мастер длинный, полоса поверх содержимого мешала бы.
        with ui.footer(fixed=False).classes("app-footer"):
            with ui.element("div").classes("container"):
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    # Размеры проставлены явно, чтобы высота подвала была известна
                    # до загрузки картинки и страница не дёргалась при отрисовке.
                    ui.html(f'<img class="app-logo" src="{MASCOT}" width="62" height="59" alt="">')
                    ui.label("SG BUDDY · SELF-HOSTED · КОГДА ПСУ ДЕЛАТЬ НЕЧЕГО").classes("footer-copy")
