"""Генератор `.proto` по настройкам из `schema.json`.

Контракт описывает те же запросы, что и `query.sql`, поэтому правила перевода
привязаны к собранному SQL, а не к настройкам напрямую:

* на таблицу — сообщение со всеми её колонками: это строка, какой её вернёт
  `SELECT *` и `RETURNING *`;
* на запрос — пара сообщений `<Имя>Request`/`<Имя>Response` и метод в сервисе
  таблицы `<Таблица>Service`;
* поля запроса — параметры **готового SQL** в порядке появления. Читаем их из
  запроса, а не из настроек: параметр приходит и из значения, написанного руками
  (`... WHERE u.external_id = @external_id`), и из `custom_query`;
* необязательный фильтр (`sqlc.narg`) и колонка, допускающая `NULL`, дают
  `optional`-поле;
* ответ зависит от аннотации: `exec` — пустое сообщение, `one` — одна строка,
  `many` — `repeated`; у `DELETE` строки нет никогда;
* **постраничность описывается целиком**: в запрос добавляются `page_limit` и
  `page_offset`, в ответ — `total_rows` и `total_pages` из парного счётчика
  `Count<имя>`. Имена совпадают с параметрами SQL, чтобы контракт и запрос
  читались как одно целое;
* выборка с явным списком колонок получает своё сообщение строки `<Имя>Row` —
  в ответе должно быть видно ровно то, что выгружается, а не вся таблица.

Запрос, который не собрался в SQL, не попадает и в контракт: причина та же и
формулирует её генератор SQL. Файл перезаписывается целиком.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import query_gen
from .ddl import Column, Table
from .query_gen import GenerationError, Problem
from .settings import (
    ANNOTATION_KEY,
    COLUMN_NAME_KEY,
    COLUMNS_KEY,
    CRUD_KEY,
    DIRECTIONS,
    NAME_KEY,
    PAGINATION_KEY,
    SHOW_KEY,
)

HEADER = (
    "// Файл сгенерирован программой SG Buddy.",
    "// Правки будут затёрты при следующей генерации: правьте настройки, а не этот файл.",
)

# Шапка таблицы — как в query.sql, только комментарий протобуфовский.
_TABLE_RULE = "// " + "=" * 57

SYNTAX = 'syntax = "proto3";'
TIMESTAMP = "google.protobuf.Timestamp"
TIMESTAMP_IMPORT = 'import "google/protobuf/timestamp.proto";'

# Пакет, если у таблиц нет схемы: `package ;` не бывает.
FALLBACK_PACKAGE = "api"

# Постраничность. Имена те же, что у параметров SQL и колонок счётчика.
PAGE_PARAMS = ("page_limit", "page_offset")
PAGE_REQUEST = (("int32", "page_limit"), ("int32", "page_offset"))
PAGE_RESPONSE = (("int64", "total_rows"), ("int64", "total_pages"))

# Postgres -> proto. Сопоставление по началу типа: `varchar(255)` и `varchar` —
# одно и то же. Порядок важен: `integer` обязан проверяться раньше `int`.
_TYPES = (
    ("bigserial", "int64"),
    ("bigint", "int64"),
    ("int8", "int64"),
    ("smallserial", "int32"),
    ("smallint", "int32"),
    ("serial", "int32"),
    ("integer", "int32"),
    ("int4", "int32"),
    ("int2", "int32"),
    ("int", "int32"),
    ("boolean", "bool"),
    ("bool", "bool"),
    ("double precision", "double"),
    ("float8", "double"),
    ("real", "float"),
    ("float4", "float"),
    # numeric и money — строкой: в double они теряют точность, а это деньги.
    ("numeric", "string"),
    ("decimal", "string"),
    ("money", "string"),
    ("timestamptz", TIMESTAMP),
    ("timestamp", TIMESTAMP),
    ("date", TIMESTAMP),
    ("time", TIMESTAMP),
    ("bytea", "bytes"),
    ("character varying", "string"),
    ("varchar", "string"),
    ("character", "string"),
    ("char", "string"),
    ("text", "string"),
    ("uuid", "string"),
    ("jsonb", "string"),
    ("json", "string"),
    ("inet", "string"),
)

_WORD = re.compile(r"[^0-9A-Za-z]+")


@dataclass
class _Field:
    """Поле сообщения. Номера расставляются при печати, по порядку."""

    type: str
    name: str
    repeated: bool = False
    optional: bool = False


@dataclass
class _Built:
    """Что дал один запрос: сообщения, метод сервиса и нужна ли строка таблицы."""

    messages: list[str] = field(default_factory=list)
    rpc: str = ""
    uses_row: bool = False


def render(settings: dict, tables: list[Table]) -> tuple[str, list[Problem]]:
    """Собирает текст `.proto`. Несобравшиеся запросы пропускает, но называет."""
    by_name = {table.name: table for table in tables}
    problems: list[Problem] = []
    taken = query_gen.query_names(settings)

    sections: list[str] = []
    schemas: list[str] = []

    for table_name, directions in (settings.get(CRUD_KEY) or {}).items():
        table = by_name.get(table_name)
        if table is None:
            problems.append(
                Problem(table_name, "—", "таблицы нет в схеме — все её запросы пропущены")
            )
            continue

        built = [
            result
            for direction in DIRECTIONS
            for entry in directions.get(direction) or []
            if (result := _entry(direction, entry, table, taken, problems)) is not None
        ]
        if not built:
            continue

        schemas.append(table_name.split(".")[0] if "." in table_name else "")
        sections.append(_section(table, built, problems))

    if not sections:
        raise GenerationError("в настройках нет ни одного запроса")

    body = "\n\n".join(sections)
    head = [*HEADER, "", SYNTAX, "", f"package {_package(schemas, problems)};"]
    if TIMESTAMP in body:
        head += ["", TIMESTAMP_IMPORT]

    return "\n".join([*head, "", body]), problems


def generate(
    settings: dict, tables: list[Table], path: str | Path
) -> tuple[Path, list[Problem]]:
    """Пишет файл через временный: прерванная запись не должна его порвать."""
    text, problems = render(settings, tables)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target, problems


# ---------------------------------------------------------------- один запрос


def _entry(
    direction: str, entry: dict, table: Table, taken: set[str], problems: list[Problem]
) -> _Built | None:
    """Сообщения и метод одного запроса. `None` — запрос не собрался в SQL."""
    name = (entry.get(NAME_KEY) or "").strip()

    # Контракт описывает то, что реально уйдёт в базу, поэтому спрашиваем SQL у
    # его генератора. Свои правила завели бы вторую версию тех же правил.
    sql_problems: list[Problem] = []
    sql = query_gen.entry_sql(direction, entry, table, taken, sql_problems)
    if sql is None:
        problems.extend(problem for problem in sql_problems if problem.fatal)
        return None

    annotation = (
        entry.get(ANNOTATION_KEY) or query_gen.DEFAULT_ANNOTATION[direction]
    ).strip()
    paged = bool(entry.get(PAGINATION_KEY)) and direction == "READ" and annotation == "many"

    request = _request(sql, table, name, paged, problems)
    row_type, row_message, uses_row = _row(direction, entry, table, name, annotation, problems)
    response = _response(row_type, table, annotation, paged)

    messages = [_message(f"{name}Request", request)]
    if row_message is not None:
        messages.append(row_message)
    messages.append(_message(f"{name}Response", response))

    return _Built(
        messages=messages,
        rpc=f"  rpc {name}({name}Request) returns ({name}Response);",
        uses_row=uses_row,
    )


def _request(
    sql: str, table: Table, query: str, paged: bool, problems: list[Problem]
) -> list[_Field]:
    """Поля запроса: параметры SQL, а следом — постраничность."""
    fields: list[_Field] = []

    for param in query_gen.params(sql):
        # Постраничность добавляем сами и всегда парой: в SQL те же параметры
        # встречаются ещё и в счётчике, порядок там ни о чём не говорит.
        if param.name in PAGE_PARAMS:
            continue

        column = table.column(param.name)
        if column is not None:
            proto = _column_type(column, table.name, query, problems)
            optional = param.optional or column.nullable
        else:
            proto = _proto_type(param.cast or "")
            if proto is None:
                problems.append(
                    Problem(
                        table.name,
                        query,
                        f"параметр @{param.name} — не колонка таблицы и без приведения "
                        "типа: поле объявлено string",
                        fatal=False,
                    )
                )
                proto = "string"
            optional = param.optional

        fields.append(_Field(proto, param.name, optional=optional and proto != TIMESTAMP))

    if paged:
        fields += [_Field(proto, name) for proto, name in PAGE_REQUEST]
    return fields


def _row(
    direction: str,
    entry: dict,
    table: Table,
    query: str,
    annotation: str,
    problems: list[Problem],
) -> tuple[str | None, str | None, bool]:
    """Тип строки ответа: имя сообщения, своё сообщение строки и нужна ли таблица.

    `RETURNING *` и `SELECT *` возвращают таблицу целиком — для них годится
    сообщение таблицы. Выборка с отмеченными колонками возвращает меньше, и
    описывать её сообщением таблицы значило бы обещать поля, которых не будет.
    """
    if not _returns_row(direction, annotation):
        return None, None, False

    table_message = _camel(table.short_name)
    if direction != "READ":
        return table_message, None, True

    shown = [
        col[COLUMN_NAME_KEY]
        for col in entry.get(COLUMNS_KEY) or []
        if col.get(SHOW_KEY) and table.column(col[COLUMN_NAME_KEY]) is not None
    ]
    if not shown or len(shown) == len(table.columns):
        return table_message, None, True

    fields = [
        _column_field(table.column(name), table.name, query, problems) for name in shown
    ]
    return f"{query}Row", _message(f"{query}Row", fields), False


def _response(
    row_type: str | None, table: Table, annotation: str, paged: bool
) -> list[_Field]:
    """Поля ответа: строки и, если запрос постраничный, счётчики."""
    fields: list[_Field] = []

    if row_type is not None:
        if annotation == "many":
            fields.append(_Field(row_type, "rows", repeated=True))
        else:
            fields.append(_Field(row_type, _snake(table.short_name)))

    if paged:
        fields += [_Field(proto, name) for proto, name in PAGE_RESPONSE]
    return fields


def _returns_row(direction: str, annotation: str) -> bool:
    """Вернёт ли запрос строки. У `exec` их нет, у `DELETE` — никогда."""
    if direction == "READ":
        return annotation in ("one", "many")
    if direction in ("CREATE", "UPDATE"):
        # `one` в этих направлениях означает `RETURNING *`.
        return annotation == "one"
    return False


# ---------------------------------------------------------------- части файла


def _section(table: Table, built: list[_Built], problems: list[Problem]) -> str:
    """Всё, что относится к одной таблице: шапка, сообщения и сервис."""
    parts = [_TABLE_RULE, f"// {table.name}", _TABLE_RULE, ""]

    if any(item.uses_row for item in built):
        fields = [
            _column_field(column, table.name, table.short_name, problems)
            for column in table.columns
        ]
        parts.append(_message(_camel(table.short_name), fields))
        parts.append("")

    for item in built:
        for message in item.messages:
            parts.append(message)
            parts.append("")

    service = [f"service {_camel(table.short_name)}Service {{"]
    service += [item.rpc for item in built]
    service.append("}")
    parts.append("\n".join(service))

    return "\n".join(parts)


def _message(name: str, fields: list[_Field]) -> str:
    """Сообщение с полями по порядку. Номера — от единицы, без пропусков."""
    if not fields:
        return f"message {name} {{}}"

    lines = [f"message {name} {{"]
    for number, item in enumerate(fields, start=1):
        prefix = "repeated " if item.repeated else "optional " if item.optional else ""
        lines.append(f"  {prefix}{item.type} {item.name} = {number};")
    lines.append("}")
    return "\n".join(lines)


def _column_field(
    column: Column, table_name: str, query: str, problems: list[Problem]
) -> _Field:
    proto = _column_type(column, table_name, query, problems)
    # У сообщений (Timestamp) присутствие и так различимо — `optional` им незачем.
    return _Field(proto, column.name, optional=column.nullable and proto != TIMESTAMP)


def _column_type(
    column: Column, table_name: str, query: str, problems: list[Problem]
) -> str:
    proto = _proto_type(column.sql_type)
    if proto is None:
        problems.append(
            Problem(
                table_name,
                query,
                f"тип {column.sql_type} колонки {column.name} неизвестен — "
                "поле объявлено string",
                fatal=False,
            )
        )
        return "string"
    return proto


def _proto_type(sql_type: str) -> str | None:
    lowered = (sql_type or "").strip().lower()
    for prefix, proto in _TYPES:
        if lowered.startswith(prefix):
            return proto
    return None


def _package(schemas: list[str], problems: list[Problem]) -> str:
    """Пакет — схема таблиц. Разные схемы в одном файле — повод сказать вслух."""
    named = sorted({schema for schema in schemas if schema})
    if not named:
        return FALLBACK_PACKAGE
    if len(named) > 1:
        problems.append(
            Problem(
                ", ".join(named),
                "—",
                f"таблицы из разных схем — package взят по первой: {named[0]}",
                fatal=False,
            )
        )
    return named[0]


def _camel(name: str) -> str:
    """`column_cat` -> `ColumnCat`."""
    return "".join(part[:1].upper() + part[1:] for part in _WORD.split(name) if part)


def _snake(name: str) -> str:
    """`ColumnCat` -> `column_cat`; имя колонки уже в нужном виде."""
    return "_".join(part.lower() for part in _WORD.split(name) if part)
