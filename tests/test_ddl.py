"""Разбор DDL. Проверяется то, ради чего взят sqlglot, а не регулярки."""

from __future__ import annotations

import pytest

from sgbuddy import ddl

from .conftest import table_named


def parse_one(text: str) -> ddl.Table:
    return ddl.parse_schema(text)[0]


# ------------------------------------------------------------ эталонная схема


def test_reference_schema_parsed_whole(reference_tables):
    """Все шестнадцать таблиц эталона разбираются и идут в порядке объявления."""
    assert len(reference_tables) == 16
    assert reference_tables[0].name == "dc.alias"
    assert reference_tables[-1].name == "dc.user"


def test_table_name_keeps_schema(alias):
    assert alias.name == "dc.alias"
    assert alias.short_name == "alias"


def test_quoted_name_stored_without_quotes(user):
    """`dc."user"` — кавычки принадлежат SQL, а не имени: их ставит генератор."""
    assert user.name == "dc.user"
    assert user.short_name == "user"


def test_inline_constraints_read(user):
    """У `dc."user"` ограничения написаны отдельными строками — они всё равно видны."""
    assert user.column("id").is_primary_key
    assert user.column("id").sql_type == "bigserial"
    assert user.column("name").nullable is False


def test_nullable_only_without_not_null(alias):
    assert alias.column("created_at").nullable is False
    assert alias.column("updated_at").nullable is True


# ------------------------------------------------------------------ типы и длины


def test_length_of_varchar_written_the_long_way():
    """`character varying(255)` и `varchar(255)` — один тип, длина у обоих одна."""
    table = parse_one(
        "CREATE TABLE t (a character varying(255), b varchar(255), c char(3))"
    )
    assert table.column("a").max_length == 255
    assert table.column("b").max_length == 255
    assert table.column("c").max_length == 3


def test_no_length_for_types_without_one():
    table = parse_one("CREATE TABLE t (a bigint, b numeric(10,2), c text)")
    assert table.column("a").max_length is None
    assert table.column("b").max_length is None
    assert table.column("c").max_length is None


def test_unknown_type_does_not_break_parsing():
    """Тип, которого генератор не знает, всё равно доезжает до него строкой."""
    assert parse_one("CREATE TABLE t (a inet)").column("a").sql_type == "inet"


# -------------------------------------------------------------------- DEFAULT


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        # sqlglot печатает их канонически (`CURRENT_TIMESTAMP`, `FALSE`), а
        # человек ждёт в интерфейсе того же, что видел в схеме.
        ("now()", "now()"),
        ("false", "false"),
        ("true", "true"),
        ("0", "0"),
    ],
)
def test_default_shown_as_written(written, expected):
    table = parse_one(f"CREATE TABLE t (a int DEFAULT {written})")
    assert table.column("a").has_default
    assert table.column("a").default_sql == expected


def test_default_with_string_literal_keeps_case():
    """Регистр строкового литерала трогать нельзя: `'Hi'` — не `'hi'`."""
    table = parse_one("CREATE TABLE t (a text DEFAULT 'Hi')")
    assert table.column("a").default_sql == "'Hi'"


def test_no_default_is_none():
    column = parse_one("CREATE TABLE t (a int)").column("a")
    assert column.has_default is False
    assert column.default_sql is None


# -------------------------------------------------------------------- модель


def test_signature_follows_meaning():
    """Отпечаток меняется вместе со смыслом колонки и не меняется от имени."""
    table = parse_one(
        "CREATE TABLE t (a varchar(10) NOT NULL, b varchar(10) NOT NULL, c varchar(20) NOT NULL, d varchar(10))"
    )
    assert table.column("a").signature == table.column("b").signature
    assert table.column("a").signature != table.column("c").signature
    assert table.column("a").signature != table.column("d").signature


def test_column_lookup(alias):
    assert alias.column("id") is not None
    assert alias.column("нет такой") is None
    assert alias.column_names == (
        "id",
        "name",
        "description",
        "created_at",
        "updated_at",
        "is_deleted",
        "user_id",
    )


# --------------------------------------------------------------- что игнорируем


def test_only_create_table_is_taken():
    """`CREATE SCHEMA` и `CREATE INDEX` — не таблицы, и таблицами стать не должны."""
    tables = ddl.parse_schema(
        "CREATE SCHEMA s;"
        "CREATE TABLE s.t (a int);"
        "CREATE INDEX i ON s.t (a);"
        "ALTER TABLE s.t ADD COLUMN b int;"
    )
    assert [table.name for table in tables] == ["s.t"]
    assert tables[0].column_names == ("a",)


def test_table_without_schema_keeps_bare_name():
    assert parse_one("CREATE TABLE t (a int)").name == "t"


# --------------------------------------------------------------------- ошибки


def test_schema_without_tables_is_an_error():
    """Гадать нечего: пустой разбор молча дал бы мастеру пустой список таблиц."""
    with pytest.raises(ddl.DDLError):
        ddl.parse_schema("SELECT 1")


def test_broken_sql_is_an_error():
    with pytest.raises(ddl.DDLError):
        ddl.parse_schema("CREATE TABLE t (((")


def test_missing_file_is_a_ddl_error(tmp_path):
    """Ошибка чтения приходит тем же типом, что и ошибка разбора: у мастера одна ветка."""
    with pytest.raises(ddl.DDLError):
        ddl.parse_schema_file(tmp_path / "нет.sql")


def test_error_names_the_source(tmp_path):
    path = tmp_path / "schema.sql"
    path.write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ddl.DDLError, match="schema.sql"):
        ddl.parse_schema_file(path)


def test_reference_tables_are_hashable(reference_tables):
    """Таблицы и колонки frozen: их кладут в словари состояния интерфейса."""
    assert len(set(reference_tables)) == len(reference_tables)
    assert table_named(reference_tables, "dc.host") in set(reference_tables)
