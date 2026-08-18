"""Сборка `.proto`. Контракт описывает те же запросы, что и `query.sql`."""

from __future__ import annotations

import pytest

from sgbuddy import ddl, proto_gen, query_gen
from sgbuddy.query_gen import GenerationError
from sgbuddy.settings import GO_PACKAGE_KEY, PROTO_PACKAGE_KEY

from .conftest import col, crud, entry


def build(table, direction, *entries, tables=None, **head):
    settings = crud(table.name, **{direction: list(entries)})
    settings.update(head)
    return proto_gen.render(settings, tables or [table])


def proto(table, direction, *entries, tables=None, **head) -> str:
    return build(table, direction, *entries, tables=tables, **head)[0]


def messages(problems) -> str:
    return " | ".join(str(problem) for problem in problems)


def one_column(sql_type: str) -> ddl.Table:
    return ddl.parse_schema(f"CREATE TABLE t (a {sql_type} NOT NULL)")[0]


# ------------------------------------------------------------------- типы


@pytest.mark.parametrize(
    ("sql_type", "expected"),
    [
        ("bigserial", "int64"),
        ("bigint", "int64"),
        ("integer", "int32"),
        ("serial", "int32"),
        ("smallint", "int32"),
        ("boolean", "bool"),
        ("double precision", "double"),
        ("real", "float"),
        # numeric и money — строкой: в double они теряют точность, а это деньги.
        ("numeric(10,2)", "string"),
        ("money", "string"),
        ("character varying(255)", "string"),
        ("text", "string"),
        ("uuid", "string"),
        ("jsonb", "string"),
        ("bytea", "bytes"),
        ("timestamp", proto_gen.TIMESTAMP),
        ("timestamptz", proto_gen.TIMESTAMP),
        ("date", proto_gen.TIMESTAMP),
    ],
)
def test_column_types(sql_type, expected):
    table = one_column(sql_type)
    text = proto(table, "READ", entry("GetT", col("a", show=True), annotation="one"))
    assert f"  {expected} a = 1;" in text


def test_unknown_column_type_becomes_string_with_a_warning():
    table = ddl.parse_schema("CREATE TABLE t (a tsvector NOT NULL)")[0]
    text, problems = build(table, "READ", entry("GetT", col("a", show=True), annotation="one"))
    assert "  string a = 1;" in text
    assert "неизвестен" in messages(problems)
    assert all(not problem.fatal for problem in problems)


def test_nullable_column_is_optional():
    table = ddl.parse_schema("CREATE TABLE t (a int, b int NOT NULL)")[0]
    text = proto(
        table, "READ", entry("GetT", col("a", show=True), col("b", show=True), annotation="one")
    )
    assert "  optional int32 a = 1;" in text
    assert "  int32 b = 2;" in text


def test_nullable_timestamp_is_not_optional(alias):
    """У сообщения присутствие и так различимо — `optional` ему незачем."""
    text = proto(alias, "READ", entry("GetAlias", *(col(name, show=True) for name in alias.column_names), annotation="one"))
    assert f"  {proto_gen.TIMESTAMP} updated_at = 5;" in text
    assert "optional google.protobuf.Timestamp" not in text


def test_timestamp_import_only_when_used(alias):
    with_time = proto(alias, "READ", entry("GetAlias", col("created_at", show=True), col("id", show=True), annotation="one"))
    assert proto_gen.TIMESTAMP_IMPORT in with_time

    without = proto(alias, "READ", entry("GetAlias", col("id", show=True), annotation="one"))
    assert proto_gen.TIMESTAMP_IMPORT not in without


# ------------------------------------------------------------------- шапка


def test_packages_come_from_the_wizard(alias):
    text = proto(
        alias,
        "CREATE",
        entry("CreateAlias", col("name")),
        **{PROTO_PACKAGE_KEY: "api.v1", GO_PACKAGE_KEY: "example.com/pkg;pkg"},
    )
    assert 'syntax = "proto3";' in text
    assert "package api.v1;" in text
    assert 'option go_package = "example.com/pkg;pkg";' in text


def test_no_packages_no_lines(alias):
    """В старых настройках их нет: пустые `package ;` protoc не примет."""
    text = proto(alias, "CREATE", entry("CreateAlias", col("name")))
    assert "package " not in text
    assert "go_package" not in text


def test_file_ends_with_a_newline(alias):
    text = proto(alias, "CREATE", entry("CreateAlias", col("name")))
    assert text.startswith(proto_gen.HEADER[0])
    assert text.endswith("\n")


# ---------------------------------------------------------------- запрос


def test_request_fields_are_the_parameters_of_the_sql(alias):
    """Порядок полей — порядок появления параметров в собранном запросе."""
    text = proto(
        alias,
        "READ",
        entry(
            "GetAlias",
            col("id", show=True, where=True),
            col("name", show=True, where=True),
            annotation="one",
        ),
    )
    assert "message GetAliasRequest {\n  int64 id = 1;\n  string name = 2;\n}" in text


def test_optional_filter_gives_an_optional_field(alias):
    text = proto(
        alias,
        "READ",
        entry("GetAlias", col("is_deleted", show=True, where_optional=True), annotation="one"),
    )
    assert "  optional bool is_deleted = 1;" in text


def test_parameter_type_comes_from_the_cast(alias):
    """Приведение автор написал руками именно про этот параметр."""
    text = proto(
        alias,
        "READ",
        entry("Raw", annotation="one", custom_query="SELECT 1 FROM dc.alias WHERE x = @thing::bigint"),
    )
    assert "  int64 thing = 1;" in text


def test_parameter_type_comes_from_a_neighbouring_table(alias, user):
    """`@external_id` приходит из подзапроса по `dc."user"` — тип честнее взять оттуда."""
    text, problems = build(
        alias,
        "CREATE",
        entry(
            "CreateAlias",
            col("name"),
            col("user_id", value='(SELECT u.id FROM dc."user" u WHERE u.external_id = @external_id)'),
        ),
        tables=[alias, user],
    )
    assert "  string external_id = 2;" in text
    assert problems == []


def test_unknown_parameter_is_string_with_a_warning(alias):
    text, problems = build(
        alias, "READ", entry("Raw", annotation="one", custom_query="SELECT 1 WHERE a = @outsider")
    )
    assert "не нашёлся ни в одной таблице схемы" in messages(problems)
    assert all(not problem.fatal for problem in problems)
    assert "string" in text


def test_same_name_with_different_types_is_reported():
    """Угадать нельзя, но и молчать нельзя: берём первую по порядку схемы."""
    tables = ddl.parse_schema(
        "CREATE TABLE own (x int NOT NULL);"
        "CREATE TABLE a (code int NOT NULL);"
        "CREATE TABLE b (code text NOT NULL);"
    )
    text, problems = build(
        tables[0],
        "READ",
        entry("Raw", annotation="one", custom_query="SELECT 1 WHERE c = @code"),
        tables=tables,
    )
    assert "разными типами" in messages(problems)
    assert "  int32 code = 1;" in text


# ------------------------------------------------------------------ ответ


def test_one_returns_a_single_row_named_after_the_table(alias):
    """Поле ответа зовут по таблице, а не по запросу: в нём лежит её строка."""
    text = proto(alias, "READ", entry("GetAlias", col("id", show=True), annotation="one"))
    assert "message GetAliasResponse {\n  GetAliasRow alias = 1;\n}" in text


def test_many_returns_repeated_rows(alias):
    text = proto(alias, "READ", entry("GetAliases", col("id", show=True), annotation="many"))
    assert "  repeated GetAliasesRow rows = 1;" in text


def test_exec_response_is_empty(alias):
    text = proto(alias, "CREATE", entry("CreateAlias", col("name")))
    assert "message CreateAliasResponse {}" in text


def test_insert_with_returning_gives_the_table_row(alias):
    text = proto(alias, "CREATE", entry("CreateAlias", col("name"), annotation="one"))
    assert "message Alias {" in text
    assert "message CreateAliasResponse {\n  Alias alias = 1;\n}" in text


def test_delete_never_returns_a_row(alias):
    text = proto(
        alias, "DELETE", entry("DeleteAlias", col("id", where=True), annotation="one")
    )
    assert "message DeleteAliasResponse {}" in text
    assert "message Alias {" not in text


def test_subset_of_columns_gets_its_own_row_message(alias):
    """Описывать выборку сообщением таблицы значило бы обещать поля, которых нет."""
    text = proto(
        alias,
        "READ",
        entry("GetAliasNames", col("id", show=True), col("name", show=True), annotation="one"),
    )
    assert "message GetAliasNamesRow {\n  int64 id = 1;\n  string name = 2;\n}" in text
    assert "message Alias {" not in text


def test_all_columns_shown_reuse_the_table_message(alias):
    text = proto(
        alias,
        "READ",
        entry("GetAlias", *(col(name, show=True) for name in alias.column_names), annotation="one"),
    )
    assert "message Alias {" in text
    assert "GetAliasRow" not in text


def test_select_star_reuses_the_table_message(alias):
    """Ни одной отмеченной колонки — запрос вернёт таблицу целиком."""
    text = proto(alias, "READ", entry("GetAlias", col("id"), annotation="one"))
    assert "message Alias {" in text
    assert "GetAliasRow" not in text


# --------------------------------------------------------------- постраничность


def test_pagination_is_described_whole(alias):
    text = proto(
        alias,
        "READ",
        entry("GetAliases", col("id", show=True, order_by=True), annotation="many", pagination=True),
    )
    assert "  int32 page_limit = " in text and "  int32 page = " in text
    assert "  repeated GetAliasesRow data = 1;" in text
    assert "  Pagination pagination = 2;" in text
    assert "message Pagination {" in text


def test_pagination_message_is_one_per_file(alias):
    text = proto(
        alias,
        "READ",
        entry("GetAliases", col("id", show=True), annotation="many", pagination=True),
        entry("GetDeleted", col("id", show=True), annotation="many", pagination=True),
    )
    assert text.count("message Pagination {") == 1


def test_no_pagination_message_without_paged_queries(alias):
    text = proto(alias, "READ", entry("GetAliases", col("id", show=True), annotation="many"))
    assert "message Pagination" not in text
    assert "page_limit" not in text


def test_page_parameters_are_not_duplicated(alias):
    """В SQL те же имена встречаются ещё и в счётчике — порядок там ни о чём не говорит."""
    text = proto(
        alias,
        "READ",
        entry("GetAliases", col("id", show=True), annotation="many", pagination=True),
    )
    request = text.split("message GetAliasesRequest {")[1].split("}")[0]
    assert request.count("page_limit") == 1
    assert request.count(" page = ") == 1


# ------------------------------------------------------------------ подсказки


def test_order_fields_say_what_is_allowed(alias):
    """По имени `order_by` не видно, что можно выбрать, — единственное место с подсказкой."""
    text = proto(
        alias,
        "READ",
        entry(
            "GetAliases",
            col("id", show=True, order_by=True),
            col("name", show=True, order_by_optional=True),
            annotation="many",
        ),
    )
    assert "  // допустимые значения: name\n  string order_by = " in text
    assert f"  // допустимые значения: {query_gen.ASCENDING}, {query_gen.DESCENDING}" in text


def test_request_comment_names_the_default_order(alias):
    """Обычные колонки сортировки параметрами не становятся — по полям их не видно."""
    text = proto(
        alias,
        "READ",
        entry("GetAliases", col("id", show=True, order_by=True), annotation="many"),
    )
    assert "// Выборка GetAliases: параметры вызова. Порядок по умолчанию — id." in text


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, "Удаление"),
        (query_gen.SOFT_DELETE, "Мягкое удаление"),
        (query_gen.UNDELETE, "Обратное удаление"),
    ],
)
def test_delete_comment_tells_the_mode(alias, mode, expected):
    columns = [col("id", where=True)]
    if mode is not None:
        columns.append(col("is_deleted", set=True, set_value="true"))
    text = proto(alias, "DELETE", entry("DeleteAlias", *columns, mode=mode))
    assert f"// {expected} DeleteAlias: параметры вызова." in text


# ------------------------------------------------------------ файл целиком


def test_service_lists_every_query_of_the_table(alias):
    text = proto(
        alias,
        "READ",
        entry("GetAlias", col("id", show=True), annotation="one"),
        entry("GetAliases", col("id", show=True), annotation="many"),
    )
    assert (
        "service AliasService {\n"
        "  rpc GetAlias(GetAliasRequest) returns (GetAliasResponse);\n"
        "  rpc GetAliases(GetAliasesRequest) returns (GetAliasesResponse);\n"
        "}" in text
    )


def test_service_name_is_camel_case():
    table = ddl.parse_schema("CREATE TABLE dc.column_cat (id bigint NOT NULL)")[0]
    text = proto(table, "READ", entry("GetColumnCat", col("id", show=True), annotation="one"))
    assert "service ColumnCatService {" in text
    assert "message ColumnCat {" in text
    assert "  ColumnCat column_cat = 1;" in text


def test_query_skipped_in_sql_is_skipped_here(alias):
    """Причина та же, и формулирует её генератор SQL."""
    text, problems = build(
        alias, "CREATE", entry("CreateAlias", col("name")), entry("Broken")
    )
    assert "Broken" not in text
    assert "INSERT без колонок" in messages(problems)


def test_table_missing_from_the_schema_is_reported(alias):
    settings = {"CRUD": {"dc.gone": {"CREATE": [entry("CreateGone", col("id"))]}}}
    with pytest.raises(GenerationError):
        proto_gen.render(settings, [alias])


def test_nothing_to_generate_is_an_error(alias):
    with pytest.raises(GenerationError):
        proto_gen.render({}, [alias])


def test_generate_writes_the_file_and_leaves_no_temporary(alias, tmp_path):
    target = tmp_path / "sub" / "api.proto"
    path, problems = proto_gen.generate(
        crud(alias.name, CREATE=[entry("CreateAlias", col("name"))]), [alias], target
    )
    assert path == target
    assert path.read_text(encoding="utf-8").startswith("// Файл сгенерирован")
    assert [p.name for p in target.parent.iterdir()] == ["api.proto"]
    assert problems == []
