"""Разбор DDL-схемы Postgres в модель таблиц и колонок.

Единственное место в программе, которое знает синтаксис SQL. Разбор идёт через
sqlglot, а не регулярками: `varchar(255)` и `character varying(255)` — один и тот
же тип, написанный по-разному, и регулярка, знающая только одно написание, молча
теряет границу длины.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
from sqlglot import exp

# Типы, у которых есть осмысленная граница длины для валидации.
_LENGTH_TYPES = {exp.DataType.Type.VARCHAR, exp.DataType.Type.CHAR}


@dataclass(frozen=True)
class Column:
    """Колонка таблицы в том виде, в каком её видит генератор."""

    name: str
    sql_type: str
    nullable: bool
    max_length: int | None = None
    has_default: bool = False
    # Текст выражения по умолчанию как в DDL: `now()`, `false`. Нужен интерфейсу,
    # чтобы подставить его в поле замены значения.
    default_sql: str | None = None
    is_primary_key: bool = False

    @property
    def signature(self) -> str:
        """Отпечаток для сверки со старым конфигом: меняется вместе со смыслом."""
        parts = [self.sql_type.lower(), "null" if self.nullable else "not null"]
        if self.max_length is not None:
            parts.append(f"len={self.max_length}")
        return " ".join(parts)


@dataclass(frozen=True)
class Table:
    """Таблица схемы. `name` — как в DDL, вместе со схемой: `dc.alias`."""

    name: str
    columns: tuple[Column, ...] = field(default_factory=tuple)

    @property
    def short_name(self) -> str:
        return self.name.split(".")[-1]

    def column(self, name: str) -> Column | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(col.name for col in self.columns)


class DDLError(Exception):
    """Схему не удалось разобрать. Гадать нельзя — сообщаем и останавливаемся."""


def parse_schema_file(path: str | Path) -> list[Table]:
    """Читает файл DDL и возвращает таблицы в порядке объявления."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as err:
        raise DDLError(f"не удалось прочитать {file_path}: {err}") from err

    return parse_schema(text, source=str(file_path))


def parse_schema(text: str, source: str = "<текст>") -> list[Table]:
    """Разбирает текст DDL. `CREATE TABLE` учитываются, остальное игнорируется."""
    try:
        statements = sqlglot.parse(text, dialect="postgres")
    except sqlglot.ParseError as err:
        raise DDLError(f"{source}: синтаксическая ошибка DDL: {err}") from err

    tables: list[Table] = []
    for statement in statements:
        if not isinstance(statement, exp.Create):
            continue
        if (statement.kind or "").upper() != "TABLE":
            continue

        table_expr = statement.find(exp.Table)
        if table_expr is None:
            continue

        keys = _primary_key_names(statement)
        columns = tuple(
            _column(col, keys) for col in statement.find_all(exp.ColumnDef)
        )
        if not columns:
            continue

        tables.append(Table(name=_table_name(table_expr), columns=columns))

    if not tables:
        raise DDLError(f"{source}: не найдено ни одного CREATE TABLE")

    return tables


def _table_name(table: exp.Table) -> str:
    """`dc.alias` для таблицы со схемой, `alias` — без неё."""
    parts = [part.name for part in (table.args.get("db"), table.this) if part]
    return ".".join(parts)


def _primary_key_names(statement: exp.Create) -> frozenset[str]:
    """Колонки ключа, объявленного строкой: `PRIMARY KEY (id)`, `(a, b)`.

    Ключ, написанный у самой колонки, сюда не попадает — он приходит
    ограничением `ColumnDef` и разбирается в `_column`.
    """
    return frozenset(
        expression.name
        for key in statement.find_all(exp.PrimaryKey)
        for expression in key.expressions
    )


def _column(col: exp.ColumnDef, keys: frozenset[str] = frozenset()) -> Column:
    constraints = col.args.get("constraints") or []
    kinds = [c.args.get("kind") for c in constraints]

    is_pk = (
        any(isinstance(k, exp.PrimaryKeyColumnConstraint) for k in kinds)
        or col.name in keys
    )
    # PRIMARY KEY в Postgres подразумевает NOT NULL, и рядом с ключом его не
    # пишут: `id bigserial constraint user_pk primary key` — обязательная
    # колонка. Не учесть этого значит объявить её `optional` в контракте.
    nullable = not is_pk and not any(
        isinstance(k, exp.NotNullColumnConstraint) for k in kinds
    )
    default = next(
        (k for k in kinds if isinstance(k, exp.DefaultColumnConstraint)), None
    )

    data_type = col.args.get("kind")

    return Column(
        name=col.name,
        sql_type=_type_name(data_type),
        nullable=nullable,
        max_length=_max_length(data_type),
        has_default=default is not None,
        default_sql=_default_sql(default),
        is_primary_key=is_pk,
    )


# sqlglot разбирает `now()` в узел CurrentTimestamp, а печатает его канонически —
# `CURRENT_TIMESTAMP`. Смысл тот же, но в DDL написано другое, и человек ждёт в
# интерфейсе именно того, что видел в схеме.
_DEFAULT_AS_WRITTEN = {"CURRENT_TIMESTAMP": "now()"}


def _default_sql(default: exp.DefaultColumnConstraint | None) -> str | None:
    """Текст default'а в том виде, в каком его пишут в DDL."""
    if default is None or default.this is None:
        return None

    rendered = default.this.sql(dialect="postgres")
    if "'" in rendered:
        # В выражении есть строковый литерал — регистр менять нельзя.
        return rendered
    return _DEFAULT_AS_WRITTEN.get(rendered.upper(), rendered.lower())


def _type_name(data_type: exp.DataType | None) -> str:
    if data_type is None:
        return "unknown"
    return data_type.sql(dialect="postgres").lower()


def _max_length(data_type: exp.DataType | None) -> int | None:
    """Граница длины для varchar/char; для остальных типов её нет."""
    if data_type is None or data_type.this not in _LENGTH_TYPES:
        return None

    for param in data_type.expressions:
        literal = param.find(exp.Literal)
        if literal is not None and literal.is_int:
            return int(literal.name)

    return None
