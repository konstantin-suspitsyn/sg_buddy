"""Сквозная проверка на эталоне: `schema.sql` -> настройки -> оба файла.

Эталон — `test_data/tables_model/schema.sql`, на нём пользователь принимает
работу. Настройки собираются здесь, а не читаются из лежащего рядом
`schema.json`: тот файл — рабочий артефакт, его затирают и пересоздают.
"""

from __future__ import annotations

from sgbuddy import ddl, proto_gen, query_gen
from sgbuddy.settings import CRUD_KEY, GO_PACKAGE_KEY, PROTO_PACKAGE_KEY

from .conftest import col, entry


def full_settings(tables: list[ddl.Table]) -> dict:
    """По четыре запроса на каждую таблицу — все направления и постраничность."""
    crud: dict[str, dict] = {}
    for table in tables:
        name = "".join(part.capitalize() for part in table.short_name.split("_"))
        first = table.columns[0].name
        crud[table.name] = {
            "CREATE": [
                entry(
                    f"Create{name}",
                    *(col(column.name) for column in table.columns),
                    annotation="one",
                )
            ],
            "READ": [
                entry(
                    f"Get{name}List",
                    *(col(column.name, show=True, order_by=column.name == first) for column in table.columns),
                    annotation="many",
                    pagination=True,
                ),
                entry(
                    f"Get{name}One",
                    *(col(column.name, show=True, where=column.name == first) for column in table.columns),
                    annotation="one",
                ),
            ],
            "UPDATE": [
                entry(
                    f"Update{name}",
                    *(
                        col(column.name, set=column.name != first, where=column.name == first)
                        for column in table.columns
                    ),
                )
            ],
            "DELETE": [entry(f"Delete{name}", col(first, where=True))],
        }
    return {
        PROTO_PACKAGE_KEY: "api.v1",
        GO_PACKAGE_KEY: "example.com/pkg;pkg",
        CRUD_KEY: crud,
    }


def test_every_table_of_the_reference_generates_both_files(reference_tables, tmp_path):
    settings = full_settings(reference_tables)

    query_path, query_problems = query_gen.generate(
        settings, reference_tables, query_gen.default_query_path(tmp_path)
    )
    proto_path, proto_problems = proto_gen.generate(
        settings, reference_tables, tmp_path / "tables_model.proto"
    )

    assert query_path is not None
    fatal = [p for p in query_problems + proto_problems if p.fatal]
    assert fatal == [], "\n".join(str(problem) for problem in fatal)

    query_text = query_path.read_text(encoding="utf-8")
    proto_text = proto_path.read_text(encoding="utf-8")

    for table in reference_tables:
        # Шапка таблицы стоит в обоих файлах и в одинаковых кавычках с запросами.
        assert f"-- {query_gen.ident(table.name)}" in query_text
        assert f"// {table.name}" in proto_text

    for name in query_gen.query_names(settings):
        assert f"-- name: {name} :" in query_text
        assert f"message {name}Request" in proto_text


def test_quoted_table_survives_the_whole_path(reference_tables, tmp_path):
    """`dc."user"` — таблица, на которой ломается всё, что кавычек не ждёт."""
    settings = full_settings(reference_tables)
    text, _ = query_gen.render(settings, reference_tables)

    assert 'FROM dc."user"' in text
    assert 'INSERT INTO dc."user" (' in text
    assert '"user".id' in text
    # Схема в самом имени колонки не участвует — ссылка идёт коротким именем.
    assert 'dc."user".id' not in text


def test_counter_is_paired_with_every_paginated_query(reference_tables):
    settings = full_settings(reference_tables)
    text, _ = query_gen.render(settings, reference_tables)

    for table in reference_tables:
        name = "".join(part.capitalize() for part in table.short_name.split("_"))
        assert f"-- name: CountGet{name}List :one" in text
