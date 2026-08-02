"""Генератор `query.sql` для sqlc по настройкам из `schema.json`.

Правила перевода настроек в SQL собраны здесь целиком, чтобы их можно было
прочитать в одном месте:

* аннотация запроса берётся из настроек; `one` для вставки и изменения означает
  `RETURNING *`, потому что sqlc обязан вернуть строку;
* пустое значение колонки — это параметр `@имя_колонки`, заполненное
  подставляется в SQL как есть (`now()`, `false`, подзапрос);
* обязательный фильтр даёт `колонка = значение`, необязательный —
  `(значение IS NULL OR колонка = значение)` с приведением типа из DDL, чтобы
  sqlc понимал тип параметра;
* `custom_where` приклеивается к остальным условиям через `AND`;
* **заполненный `custom_query` отменяет всё остальное**: колонки, фильтры и
  `custom_where` игнорируются, в файл идёт ровно то, что написано руками. Из
  настроек берутся только имя запроса и аннотация — всё прочее, включая
  `RETURNING` и `LIMIT`, автор пишет сам.

Файл перезаписывается целиком: он производный, править его руками бессмысленно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .ddl import Table
from .settings import (
    ANNOTATION_KEY,
    COLUMN_NAME_KEY,
    COLUMN_VALUE_KEY,
    COLUMNS_KEY,
    CRUD_KEY,
    CUSTOM_QUERY_KEY,
    CUSTOM_WHERE_KEY,
    EXACT_WHERE_KEY,
    MODE_KEY,
    NAME_KEY,
    PAGINATION_KEY,
    SET_KEY,
    SET_VALUE_KEY,
    SHOW_KEY,
    WHERE_KEY,
    WHERE_OPTIONAL_KEY,
    WHERE_VALUE_KEY,
)

QUERY_FILENAME = "query.sql"

HEADER = (
    "-- Файл сгенерирован программой SG Buddy.",
    "-- Правки будут затёрты при следующей генерации: правьте настройки, а не этот файл.",
)

SOFT_DELETE = "SOFT DELETE"

# Аннотация по умолчанию, если её нет в настройках (у DELETE её нет вовсе).
_DEFAULT_ANNOTATION = {"CREATE": "exec", "READ": "many", "UPDATE": "exec", "DELETE": "exec"}

# Постраничность: имена параметров фиксированы, иначе их неоткуда взять.
LIMIT_PARAM = "@page_limit"
OFFSET_PARAM = "@page_offset"

# Идентификаторы, которые обязаны быть в кавычках. Список короткий намеренно:
# кавычить всё подряд — читать невозможно, угадывать — ошибка.
RESERVED = {
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "authorization",
    "between", "both", "case", "cast", "check", "collate", "column", "constraint",
    "create", "cross", "current_date", "current_role", "current_time",
    "current_timestamp", "current_user", "default", "deferrable", "desc", "distinct",
    "do", "else", "end", "except", "false", "for", "foreign", "freeze", "from", "full",
    "grant", "group", "having", "ilike", "in", "initially", "inner", "intersect",
    "into", "is", "isnull", "join", "leading", "left", "like", "limit", "localtime",
    "localtimestamp", "natural", "not", "notnull", "null", "offset", "on", "only",
    "or", "order", "outer", "overlaps", "placing", "primary", "references", "returning",
    "right", "select", "session_user", "similar", "some", "table", "then", "to",
    "trailing", "true", "union", "unique", "user", "using", "verbose", "when", "where",
    "window", "with",
}

_SIMPLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class Problem:
    """Запрос, который сгенерировать не удалось или который стоит перечитать."""

    table: str
    query: str
    message: str
    fatal: bool = True

    def __str__(self) -> str:
        return f"{self.table} · {self.query}: {self.message}"


class GenerationError(Exception):
    """Сгенерировать нечего — например, в настройках нет ни одного запроса."""


def default_query_path(folder: str | Path) -> Path:
    """`query.sql` кладём в папку схемы, рядом со `schema.json`.

    Своего ключа с путём в настройках нет и не нужно: файл всегда лежит там же,
    где схема и её настройки.
    """
    return Path(folder) / QUERY_FILENAME


def ident(name: str) -> str:
    """Имя в кавычках, только если без них нельзя: `dc.user` -> `dc."user"`."""
    parts = []
    for part in name.split("."):
        if _SIMPLE_NAME.match(part) and part not in RESERVED:
            parts.append(part)
        else:
            parts.append('"' + part.replace('"', '""') + '"')
    return ".".join(parts)


def render(settings: dict, tables: list[Table]) -> tuple[str, list[Problem]]:
    """Собирает текст `query.sql`. Проблемные запросы пропускает, но называет."""
    by_name = {table.name: table for table in tables}
    problems: list[Problem] = []
    blocks: list[str] = []

    for table_name, directions in (settings.get(CRUD_KEY) or {}).items():
        table = by_name.get(table_name)
        if table is None:
            problems.append(
                Problem(table_name, "—", "таблицы нет в схеме — все её запросы пропущены")
            )
            continue

        for direction in ("CREATE", "READ", "UPDATE", "DELETE"):
            for entry in directions.get(direction) or []:
                block = _entry_sql(direction, entry, table, problems)
                if block:
                    blocks.append(block)

    if not blocks:
        raise GenerationError("в настройках нет ни одного запроса")

    return "\n".join([*HEADER, "", *blocks]), problems


def generate(settings: dict, tables: list[Table], path: str | Path) -> tuple[Path, list[Problem]]:
    """Пишет файл через временный: прерванная запись не должна его порвать."""
    text, problems = render(settings, tables)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target, problems


# ---------------------------------------------------------------- один запрос


def _entry_sql(
    direction: str, entry: dict, table: Table, problems: list[Problem]
) -> str | None:
    name = (entry.get(NAME_KEY) or "").strip()
    if not name:
        problems.append(Problem(table.name, "—", f"{direction}: запрос без названия"))
        return None

    annotation = (entry.get(ANNOTATION_KEY) or _DEFAULT_ANNOTATION[direction]).strip()

    # Запрос написан руками целиком — из настроек больше ничего не берём и ничего
    # не проверяем: колонки в нём могут вообще не участвовать.
    custom = (entry.get(CUSTOM_QUERY_KEY) or "").strip()
    if custom:
        return _custom_block(name, annotation, custom)

    unknown = [
        col.get(COLUMN_NAME_KEY)
        for col in entry.get(COLUMNS_KEY) or []
        if table.column(col.get(COLUMN_NAME_KEY)) is None
    ]
    if unknown:
        problems.append(
            Problem(table.name, name, "нет таких колонок в схеме: " + ", ".join(unknown))
        )
        return None

    builders = {
        "CREATE": _create_sql,
        "READ": _read_sql,
        "UPDATE": _update_sql,
        "DELETE": _delete_sql,
    }
    return builders[direction](entry, table, name, annotation, problems)


def _create_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []
    if not columns:
        problems.append(Problem(table.name, name, "INSERT без колонок"))
        return None

    names = ",\n    ".join(ident(col[COLUMN_NAME_KEY]) for col in columns)
    values = ",\n    ".join(
        _value(col.get(COLUMN_VALUE_KEY), col[COLUMN_NAME_KEY]) for col in columns
    )

    body = [
        f"INSERT INTO {ident(table.name)} (",
        f"    {names}",
        ") VALUES (",
        f"    {values}",
        ")",
    ]
    # sqlc не примет `:one` у запроса, которому нечего вернуть.
    return _block(name, annotation, body, returning=annotation == "one")


def _read_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []

    shown = [col[COLUMN_NAME_KEY] for col in columns if col.get(SHOW_KEY)]
    if not shown:
        problems.append(
            Problem(table.name, name, "не отмечена ни одна колонка — берём все", fatal=False)
        )

    if shown:
        body = ["SELECT", "    " + ",\n    ".join(ident(column) for column in shown)]
    else:
        body = ["SELECT *"]

    body.append(f"FROM {ident(table.name)}")
    body += _where_block(entry, table, EXACT_WHERE_KEY)

    if annotation == "one":
        body.append("LIMIT 1")
    elif entry.get(PAGINATION_KEY):
        body.append(f"LIMIT {LIMIT_PARAM} OFFSET {OFFSET_PARAM}")

    return _block(name, annotation, body)


def _update_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []

    assignments = [
        f"{ident(col[COLUMN_NAME_KEY])} = "
        + _value(col.get(SET_VALUE_KEY), col[COLUMN_NAME_KEY])
        for col in columns
        if col.get(SET_KEY)
    ]
    if not assignments:
        problems.append(Problem(table.name, name, "UPDATE без единой изменяемой колонки"))
        return None

    where = _where_block(entry, table, WHERE_VALUE_KEY)
    if not where:
        problems.append(
            Problem(table.name, name, "UPDATE без WHERE — изменит всю таблицу", fatal=False)
        )

    body = [f"UPDATE {ident(table.name)}", "SET " + ",\n    ".join(assignments)]
    body += where

    return _block(name, annotation, body, returning=annotation == "one")


def _delete_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []
    soft = entry.get(MODE_KEY) == SOFT_DELETE

    where = _where_block(entry, table, WHERE_VALUE_KEY)
    if not where:
        problems.append(
            Problem(
                table.name,
                name,
                "удаление без WHERE — заденет всю таблицу",
                fatal=False,
            )
        )

    if soft:
        assignments = [
            f"{ident(col[COLUMN_NAME_KEY])} = "
            + _value(col.get(SET_VALUE_KEY), col[COLUMN_NAME_KEY])
            for col in columns
            if col.get(SET_KEY)
        ]
        if not assignments:
            problems.append(
                Problem(table.name, name, "мягкое удаление без единой проставляемой колонки")
            )
            return None
        body = [f"UPDATE {ident(table.name)}", "SET " + ",\n    ".join(assignments)]
    else:
        body = [f"DELETE FROM {ident(table.name)}"]

    body += where
    return _block(name, annotation, body)


# ---------------------------------------------------------------- части запроса


def _value(written: str | None, column: str) -> str:
    """Заполненное значение идёт в SQL как есть, пустое — параметром."""
    written = (written or "").strip()
    return written or f"@{column}"


def _where_block(entry: dict, table: Table, value_key: str) -> list[str]:
    """Строки `WHERE ...` / `  AND ...` — или пустой список, если условий нет."""
    conditions: list[str] = []

    for col in entry.get(COLUMNS_KEY) or []:
        name = col[COLUMN_NAME_KEY]
        written = (col.get(value_key) or "").strip()

        if col.get(WHERE_KEY):
            conditions.append(f"{ident(name)} = {written or f'@{name}'}")
        elif col.get(WHERE_OPTIONAL_KEY):
            # Необязательный фильтр: параметр либо задан, либо условие не работает.
            # Приведение типа нужно, чтобы sqlc не гадал тип sqlc.narg.
            param = written or f"sqlc.narg('{name}')"
            column = table.column(name)
            cast = f"::{column.sql_type}" if column is not None else ""
            conditions.append(f"({param}{cast} IS NULL OR {ident(name)} = {param})")

    custom = (entry.get(CUSTOM_WHERE_KEY) or "").strip()
    if custom:
        # В скобках: своё условие может содержать OR и молча расширить выборку.
        conditions.append(f"({custom})")

    if not conditions:
        return []

    return [f"WHERE {conditions[0]}"] + [f"  AND {rest}" for rest in conditions[1:]]


def _block(
    name: str, annotation: str, body: list[str], returning: bool = False
) -> str:
    """Заголовок sqlc, тело собранного запроса и `RETURNING`."""
    parts = [*body, "RETURNING *"] if returning else list(body)
    return "\n".join([f"-- name: {name} :{annotation}", *parts]) + ";\n"


def _custom_block(name: str, annotation: str, custom: str) -> str:
    """Запрос, написанный руками: только заголовок sqlc и его собственный текст."""
    # Точку с запятой добавляем, только если её не поставили сами.
    tail = "" if custom.rstrip().endswith(";") else ";"
    return f"-- name: {name} :{annotation}\n{custom}{tail}\n"
