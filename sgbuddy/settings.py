"""`schema.json` — настройки одной DDL-схемы. Лежит рядом со `schema.sql`.

Пояснение «что это за файл» лежит первым ключом `description`: комментариев
JSON не знает, а человеку, открывшему файл в редакторе, надо сразу понимать,
кто его создал. Раньше на этом месте были строки `//` — файлы той поры на
дисках есть, и чтение их снимает (см. `_strip_header`).
"""

from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILENAME = "schema.json"

# Шапка файла. Правится здесь и только здесь.
DESCRIPTION_KEY = "description"
DESCRIPTION = (
    "Файл создан программой SG Buddy. "
    "Здесь лежат настройки генерации query.sql и .proto по DDL-схеме. "
    "Программа перезаписывает файл целиком, когда сохраняет настройки."
)

# Порядок первых пяти ключей фиксирован: пояснение, папка схемы, .proto и две
# его шапки — всё, что мастер спрашивает до разбора схемы. Ключи идут в том же
# порядке, в каком строки лежат в сгенерированном файле.
SCHEMA_FOLDER_KEY = "schema_folder_path"
SAVE_PROTO_KEY = "save_proto_path"
PROTO_PACKAGE_KEY = "proto_package"
GO_PACKAGE_KEY = "go_package"

# Раздел с запросами: CRUD -> таблица -> CREATE/READ/UPDATE/DELETE -> описания.
CRUD_KEY = "CRUD"
DIRECTIONS = ("CREATE", "READ", "UPDATE", "DELETE")

# Ключи одного описания запроса. Таблицу внутрь не пишем — она уже ключом выше.
NAME_KEY = "Name"
ANNOTATION_KEY = "Query Annotation"
COLUMNS_KEY = "columns"
COLUMN_NAME_KEY = "column_name"
COLUMN_VALUE_KEY = "column_value"

# Ключи выборки (READ).
PAGINATION_KEY = "Pagination"
SHOW_KEY = "show"
WHERE_KEY = "where"
WHERE_OPTIONAL_KEY = "where_optional"
EXACT_WHERE_KEY = "exact_where"
CUSTOM_WHERE_KEY = "custom_where"
# Сортировка. Есть только у выборки списка: у `one` строка одна, порядок ей ни к
# чему, — поэтому в колонках эти ключи появляются только при аннотации `many`.
ORDER_BY_KEY = "order_by"
ORDER_BY_OPTIONAL_KEY = "order_by_optional"
# Своё тело запроса — есть у всех четырёх направлений.
CUSTOM_QUERY_KEY = "custom_query"

# Ключи изменения (UPDATE).
SET_KEY = "set"
SET_VALUE_KEY = "set_value"
WHERE_VALUE_KEY = "where_value"

# Ключи удаления (DELETE): физическое или мягкое.
MODE_KEY = "Mode"


def directions_of(settings: dict, table: str) -> dict:
    """Направления таблицы для чтения. Настройки не трогает."""
    return settings.get(CRUD_KEY, {}).get(table, {})


def entries_of(settings: dict, table: str, direction: str) -> list:
    return directions_of(settings, table).get(direction, [])


def ensure_directions(settings: dict, table: str) -> dict:
    """Раздел таблицы со всеми четырьмя направлениями. Заводит его, если его нет.

    Вызывается только при записи: от простого просмотра в файле не должны
    появляться пустые разделы всех шестнадцати таблиц.
    """
    section = settings.setdefault(CRUD_KEY, {}).setdefault(table, {})
    for direction in DIRECTIONS:
        section.setdefault(direction, [])
    return section


def migrate_crud(settings: dict) -> dict:
    """Переносит плоский CRUD старого формата под таблицы.

    Раньше запросы лежали как `CRUD -> CREATE -> [ {Table: ...}, ... ]`. Файлы
    той поры уже есть на дисках, и падать на них нельзя.
    """
    crud = settings.get(CRUD_KEY)
    if not isinstance(crud, dict) or not set(crud) & set(DIRECTIONS):
        return settings

    nested: dict[str, dict] = {}
    for direction, entries in crud.items():
        if direction not in DIRECTIONS or not isinstance(entries, list):
            continue
        for entry in entries:
            table = entry.pop("Table", "") or "?"
            nested.setdefault(table, {}).setdefault(direction, []).append(entry)

    for directions in nested.values():
        for direction in DIRECTIONS:
            directions.setdefault(direction, [])

    settings[CRUD_KEY] = nested
    return settings


def all_entries(settings: dict):
    """(таблица, направление, индекс, запись) по всему файлу — для проверки имён."""
    for table, directions in settings.get(CRUD_KEY, {}).items():
        for direction, entries in directions.items():
            for index, entry in enumerate(entries):
                yield table, direction, index, entry


def settings_path(folder: str | Path) -> Path:
    return Path(folder) / SETTINGS_FILENAME


def windows_path(value: str | Path) -> str:
    """Путь с обратными слэшами: `C:/dc/schema` -> `C:\\dc\\schema`.

    Программа локальная и windows-овая, а путь из файла копируют в проводник и
    в чужие конфиги. Введённый со слэшами он работает, но выглядит чужеродно
    рядом с остальными, поэтому в файл кладём один вид разделителя.
    """
    return str(value).replace("/", "\\")


def default_settings(
    folder: str | Path,
    proto: str | Path,
    go_package: str = "",
    proto_package: str = "",
) -> dict:
    """Стандартные параметры нового файла — пояснение, два пути и две шапки."""
    return {
        DESCRIPTION_KEY: DESCRIPTION,
        SCHEMA_FOLDER_KEY: windows_path(folder),
        SAVE_PROTO_KEY: windows_path(proto),
        PROTO_PACKAGE_KEY: proto_package,
        GO_PACKAGE_KEY: go_package,
    }


def with_paths(
    data: dict,
    folder: str | Path,
    proto: str | Path,
    go_package: str = "",
    proto_package: str = "",
) -> dict:
    """Возвращает настройки, где шапка и выбранное в мастере стоят первыми.

    Пути и go-пакет — то, что выбрано в интерфейсе сейчас; всё остальное из
    файла сохраняется как есть. `description` переписывается нашим текстом: это
    подпись программы, а не пользовательское поле.
    """
    head = (
        DESCRIPTION_KEY,
        SCHEMA_FOLDER_KEY,
        SAVE_PROTO_KEY,
        PROTO_PACKAGE_KEY,
        GO_PACKAGE_KEY,
    )
    rest = {k: v for k, v in data.items() if k not in head}
    return {
        DESCRIPTION_KEY: DESCRIPTION,
        SCHEMA_FOLDER_KEY: windows_path(folder),
        SAVE_PROTO_KEY: windows_path(proto),
        PROTO_PACKAGE_KEY: proto_package,
        # Пакеты через `windows_path` не пропускаем: это имя пакета и путь
        # импорта Go, а не файловые пути, и точки со слэшами в них — значение.
        GO_PACKAGE_KEY: go_package,
        **rest,
    }


def load_settings(path: str | Path) -> dict:
    """Читает файл, снимая строки-комментарии в шапке старых файлов."""
    text = Path(path).read_text(encoding="utf-8")
    body = _strip_header(text)
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("ожидался объект JSON")
    return data


def save_settings(data: dict, path: str | Path) -> Path:
    """Пишет через временный файл: прерванная запись не должна убить настройки."""
    target = Path(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target


def _strip_header(text: str) -> str:
    """Убирает ведущие строки `//` из файлов старого формата.

    Сами мы такую шапку больше не пишем — пояснение лежит ключом `description`,
    — но файлы с комментариями на дисках есть, и падать на них нельзя.
    """
    lines = text.splitlines()
    start = 0
    for index, line in enumerate(lines):
        if line.strip().startswith("//") or not line.strip():
            start = index + 1
        else:
            break
    return "\n".join(lines[start:])
