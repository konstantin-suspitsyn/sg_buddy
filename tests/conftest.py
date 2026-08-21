"""Общие фикстуры и сборщики настроек для тестов.

Настройки в тестах пишутся не литеральными словарями, а через `entry`/`col`:
ключи `schema.json` задаются в `settings.py` и только там, и тест, повторяющий
их строками, разошёлся бы с программой молча.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sgbuddy import ddl
from sgbuddy.settings import (
    ANNOTATION_KEY,
    COLUMN_NAME_KEY,
    COLUMN_VALUE_KEY,
    COLUMNS_KEY,
    CRUD_KEY,
    CUSTOM_QUERY_KEY,
    CUSTOM_WHERE_KEY,
    EXACT_WHERE_KEY,
    JOIN_ALIAS_KEY,
    JOIN_NAME_KEY,
    JOIN_ON_KEY,
    JOIN_TABLE_KEY,
    JOIN_TYPE_KEY,
    JOINED_COLUMNS_KEY,
    JOINS_KEY,
    LINKS_KEY,
    MODE_KEY,
    NAME_KEY,
    ORDER_BY_KEY,
    ORDER_BY_OPTIONAL_KEY,
    PAGINATION_KEY,
    SET_KEY,
    SET_VALUE_KEY,
    SHOW_KEY,
    USED_JOINS_KEY,
    WHERE_KEY,
    WHERE_OPTIONAL_KEY,
    WHERE_VALUE_KEY,
)

# Эталонная схема, на которой пользователь принимает работу.
REFERENCE_SCHEMA = (
    Path(__file__).resolve().parents[1] / "test_data" / "tables_model" / "schema.sql"
)


@pytest.fixture(scope="session")
def reference_tables() -> list[ddl.Table]:
    return ddl.parse_schema_file(REFERENCE_SCHEMA)


@pytest.fixture
def alias(reference_tables: list[ddl.Table]) -> ddl.Table:
    """`dc.alias` — обычная таблица: имя без кавычек, есть nullable-колонка."""
    return table_named(reference_tables, "dc.alias")


@pytest.fixture
def user(reference_tables: list[ddl.Table]) -> ddl.Table:
    """`dc.user` — имя в кавычках, `bigserial`, inline-constraints."""
    return table_named(reference_tables, "dc.user")


def table_named(tables: list[ddl.Table], name: str) -> ddl.Table:
    return next(table for table in tables if table.name == name)


# ------------------------------------------------------------ сборка настроек

_COLUMN_KEYS = {
    "value": COLUMN_VALUE_KEY,
    "show": SHOW_KEY,
    "where": WHERE_KEY,
    "where_optional": WHERE_OPTIONAL_KEY,
    "exact": EXACT_WHERE_KEY,
    "where_value": WHERE_VALUE_KEY,
    "order_by": ORDER_BY_KEY,
    "order_by_optional": ORDER_BY_OPTIONAL_KEY,
    "set": SET_KEY,
    "set_value": SET_VALUE_KEY,
}

_ENTRY_KEYS = {
    "annotation": ANNOTATION_KEY,
    "pagination": PAGINATION_KEY,
    "custom_where": CUSTOM_WHERE_KEY,
    "custom_query": CUSTOM_QUERY_KEY,
    "mode": MODE_KEY,
    # Ключи join'ов есть только у выборок, которые их используют.
    "joins": USED_JOINS_KEY,
    "joined": JOINED_COLUMNS_KEY,
}


def col(name: str, **flags) -> dict:
    """Описание одной колонки запроса. Ключи разные у направлений — см. CLAUDE.md."""
    return {COLUMN_NAME_KEY: name, **{_COLUMN_KEYS[key]: value for key, value in flags.items()}}


def entry(name: str, *columns: dict, **rest) -> dict:
    """Описание одного запроса."""
    return {
        NAME_KEY: name,
        COLUMNS_KEY: list(columns),
        **{_ENTRY_KEYS[key]: value for key, value in rest.items()},
    }


def crud(table: str, **directions) -> dict:
    """Настройки с запросами одной таблицы: `crud("dc.alias", READ=[...])`."""
    return {CRUD_KEY: {table: {name: list(items) for name, items in directions.items()}}}


def link(table: str, alias: str, on: str, type: str = "INNER") -> dict:
    """Звено цепочки: к какой таблице и по какому условию присоединяемся."""
    return {
        JOIN_TYPE_KEY: type,
        JOIN_TABLE_KEY: table,
        JOIN_ALIAS_KEY: alias,
        JOIN_ON_KEY: on,
    }


def chain(name: str, *links: dict) -> dict:
    """Именованная цепочка: звеньев столько, сколько таблиц присоединяется."""
    return {NAME_KEY: name, LINKS_KEY: list(links)}


def jcol(join: str, alias: str, name: str, **flags) -> dict:
    """Колонка приджойненной таблицы: те же флаги, что у своих, плюс цепочка."""
    return {
        JOIN_NAME_KEY: join,
        JOIN_ALIAS_KEY: alias,
        COLUMN_NAME_KEY: name,
        **{_COLUMN_KEYS[key]: value for key, value in flags.items()},
    }


def with_joins(settings: dict, table: str, *chains: dict) -> dict:
    """Дописывает к настройкам раздел `JOINS` одной таблицы."""
    settings.setdefault(JOINS_KEY, {})[table] = list(chains)
    return settings
