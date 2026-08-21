"""Перевод настроек в `query.sql`. Правила перечислены в docstring `query_gen`."""

from __future__ import annotations

import pytest

from sgbuddy import query_gen
from sgbuddy.query_gen import GenerationError, Param

from .conftest import chain, col, crud, entry, jcol, link, table_named, with_joins


def build(table, direction, *entries, tables=None):
    """Текст и проблемы для запросов одной таблицы."""
    settings = crud(table.name, **{direction: list(entries)})
    return query_gen.render(settings, tables or [table])


def sql(table, direction, *entries, tables=None) -> str:
    return build(table, direction, *entries, tables=tables)[0]


def messages(problems) -> str:
    return " | ".join(str(problem) for problem in problems)


# ---------------------------------------------------------------- имена и параметры


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("dc.alias", "dc.alias"),
        # `user` — зарезервированное слово, без кавычек Postgres его не примет.
        ("dc.user", 'dc."user"'),
        ("order", '"order"'),
        ("alias", "alias"),
        # Прописные буквы Postgres сложил бы к строчным — кавычки обязательны.
        ("Alias", '"Alias"'),
        ("два слова", '"два слова"'),
        ('стран"ное', '"стран""ное"'),
    ],
)
def test_ident_quotes_only_what_needs_quoting(name, expected):
    assert query_gen.ident(name) == expected


def test_params_read_every_form_of_writing():
    """Параметр приходит и из значения руками, и из `custom_query`."""
    found = query_gen.params(
        "SELECT * FROM t WHERE a = @id::uuid "
        "AND (sqlc.narg('flag')::boolean IS NULL OR b = sqlc.narg('flag')) "
        "AND c = sqlc.arg('order')::text "
        "AND d = sqlc.narg(bare) AND e = sqlc.arg(plain) AND f = @amount::double precision"
    )
    assert found == [
        Param("id", "uuid"),
        Param("flag", "boolean", optional=True),
        Param("order", "text"),
        Param("bare", None, optional=True),
        Param("plain", None),
        Param("amount", "double precision"),
    ]


def test_repeated_param_keeps_the_first_type():
    """`narg('x')::bool IS NULL OR col = narg('x')` — тип написан только в начале."""
    assert query_gen.params("@x::bigint = 1 AND @x = 2") == [Param("x", "bigint")]


def test_query_names_are_collected_from_the_whole_file():
    settings = {
        "CRUD": {
            "dc.alias": {"CREATE": [entry("CreateAlias")], "READ": [entry("GetAliases")]},
            "dc.host": {"DELETE": [entry("DeleteHost")]},
        }
    }
    assert query_gen.query_names(settings) == {"CreateAlias", "GetAliases", "DeleteHost"}


def test_query_path_is_next_to_the_schema(tmp_path):
    assert query_gen.default_query_path(tmp_path) == tmp_path / query_gen.QUERY_FILENAME


# --------------------------------------------------------------------- CREATE


def test_insert_lists_columns_without_table_name(alias):
    """`INSERT` перечисляет свои колонки — квалификация там синтаксическая ошибка."""
    text = sql(alias, "CREATE", entry("CreateAlias", col("name"), col("is_deleted")))
    assert "-- name: CreateAlias :exec" in text
    assert "INSERT INTO dc.alias (\n    name,\n    is_deleted\n) VALUES (" in text
    assert "alias.name" not in text


def test_empty_value_becomes_a_parameter(alias):
    """Пустое значение — «приходит параметром», заполненное идёт в SQL как есть."""
    text = sql(
        alias,
        "CREATE",
        entry("CreateAlias", col("name"), col("created_at", value="now()")),
    )
    assert ") VALUES (\n    @name,\n    now()\n)" in text


def test_one_means_returning_for_insert(alias):
    """sqlc обязан вернуть строку, если у запроса аннотация `one`."""
    text = sql(alias, "CREATE", entry("CreateAlias", col("name"), annotation="one"))
    assert text.rstrip().endswith(")\nRETURNING *;")


def test_exec_insert_has_no_returning(alias):
    """`:exec` возвращать нечего — `RETURNING` тут sqlc не примет."""
    assert "RETURNING" not in sql(alias, "CREATE", entry("CreateAlias", col("name")))


def test_insert_without_columns_is_skipped(alias):
    with pytest.raises(GenerationError):
        build(alias, "CREATE", entry("CreateAlias"))


# ----------------------------------------------------------------------- READ


def test_select_qualifies_columns_with_short_table_name(alias):
    text = sql(alias, "READ", entry("GetAlias", col("id", show=True), col("name", show=True), annotation="one"))
    assert "SELECT\n    alias.id,\n    alias.name\nFROM dc.alias" in text


def test_select_from_quoted_table_uses_the_same_quotes(user):
    """В `FROM dc."user"` таблица видна как `"user"` — ссылка обязана совпасть."""
    text = sql(user, "READ", entry("GetUser", col("id", show=True), annotation="one"))
    assert 'SELECT\n    "user".id\nFROM dc."user"' in text


def test_nothing_shown_means_select_star_with_a_warning(alias):
    text, problems = build(alias, "READ", entry("GetAlias", col("id"), annotation="one"))
    assert "SELECT *\nFROM dc.alias" in text
    assert any(not problem.fatal for problem in problems)
    assert "берём все" in messages(problems)


def test_one_gets_limit_one(alias):
    text = sql(alias, "READ", entry("GetAlias", col("id", show=True, where=True), annotation="one"))
    assert text.rstrip().endswith("LIMIT 1;")
    # Порядок у одиночной строки не нужен — сортировки в запросе нет.
    assert "ORDER BY" not in text


def test_where_is_mandatory_condition(alias):
    text = sql(alias, "READ", entry("GetAlias", col("id", show=True, where=True), annotation="one"))
    assert "WHERE alias.id = @id" in text


def test_where_value_replaces_the_parameter(alias):
    """`EXACT WHERE` у отмеченной колонки задаёт значение вместо параметра."""
    text = sql(
        alias,
        "READ",
        entry("GetAlive", col("is_deleted", show=True, where=True, exact="false"), annotation="one"),
    )
    assert "WHERE alias.is_deleted = false" in text


def test_exact_where_alone_still_filters(alias):
    """Колонка не отмечена, но значение вписано — условие всё равно в запросе."""
    text = sql(
        alias,
        "READ",
        entry(
            "GetAlive",
            col("id", show=True, where=True),
            col("is_deleted", show=True, exact="false"),
            annotation="one",
        ),
    )
    assert "WHERE alias.id = @id\n  AND alias.is_deleted = false" in text


def test_optional_where_casts_the_parameter(alias):
    """Без приведения sqlc не выведет тип `sqlc.narg`."""
    text = sql(
        alias,
        "READ",
        entry("GetAlias", col("is_deleted", show=True, where_optional=True), annotation="one"),
    )
    assert (
        "WHERE (sqlc.narg('is_deleted')::boolean IS NULL "
        "OR alias.is_deleted = sqlc.narg('is_deleted'))" in text
    )


def test_custom_where_is_wrapped_in_parentheses(alias):
    """Своё условие может содержать OR и молча расширить выборку."""
    text = sql(
        alias,
        "READ",
        entry(
            "GetAlias",
            col("id", show=True, where=True),
            annotation="one",
            custom_where="name IS NOT NULL OR description IS NOT NULL",
        ),
    )
    assert "  AND (name IS NOT NULL OR description IS NOT NULL)" in text


def test_custom_where_copied_with_where_and_semicolon_is_cleaned(alias):
    """Условие часто копируют из готового запроса — вместе с `WHERE` и `;`."""
    text = sql(
        alias,
        "READ",
        entry("GetAlias", col("id", show=True), annotation="one", custom_where="WHERE id > 0;"),
    )
    assert "WHERE (id > 0)" in text
    assert ";)" not in text


# ------------------------------------------------------------------ сортировка


def test_many_is_always_ordered(alias):
    """Без `ORDER BY` постраничная выборка начинает повторять и терять строки."""
    text = sql(alias, "READ", entry("GetAliases", col("id", show=True), annotation="many"))
    assert "ORDER BY CASE WHEN sqlc.arg('order')::text <> 'DESC' THEN alias.id END ASC," in text
    assert "    CASE WHEN sqlc.arg('order')::text = 'DESC' THEN alias.id END DESC" in text


def test_optional_order_column_is_chosen_by_name(alias):
    """Выбираемая колонка срабатывает по `@order_by`, обычная — всегда."""
    text = sql(
        alias,
        "READ",
        entry(
            "GetAliases",
            col("id", show=True, order_by=True),
            col("name", show=True, order_by_optional=True),
            annotation="many",
        ),
    )
    assert "@order_by::text = 'name'" in text
    # Обычной колонке выбор не нужен — она идёт дополнительным ключом всегда.
    assert "@order_by::text = 'id'" not in text
    assert "THEN alias.id END ASC" in text


def test_ordering_reports_the_default_key(alias):
    """`ELSE` — первая обычная колонка сортировки, иначе первая колонка DDL.

    Сортировка считается по колонкам выборки, а не по записи настроек: у
    выборки с join'ом среди них есть и колонки приджойненных таблиц.
    """
    marked = entry("GetAliases", col("name", order_by=True), annotation="many")
    fields = query_gen.read_fields(marked, alias)
    assert query_gen.ordering(fields, alias, always=True).default == "name"

    empty = query_gen.read_fields(entry("GetAliases", annotation="many"), alias)
    assert query_gen.ordering(empty, alias, always=True).default == "id"
    # У `one` порядка нет вовсе.
    assert query_gen.ordering(empty, alias, always=False).default is None


# --------------------------------------------------------------- постраничность


def test_pagination_adds_limit_offset_and_a_counter(alias):
    text, problems = build(
        alias,
        "READ",
        entry(
            "GetAliases",
            col("id", show=True, order_by=True),
            col("is_deleted", where=True, exact="false"),
            annotation="many",
            pagination=True,
        ),
    )
    assert "LIMIT @page_limit::int OFFSET (sqlc.arg('page')::int-1)*sqlc.arg('page_limit')::int;" in text
    assert "-- name: CountGetAliases :one" in text
    assert "count(*)" in text and "total_pages" in text
    # Условия у счётчика те же — иначе он считал бы другую выборку.
    assert text.count("WHERE alias.is_deleted = false") == 2
    # А сортировка ему не достаётся: считать она не помогает.
    assert text.count("ORDER BY") == 1
    assert not any(problem.fatal for problem in problems)


def test_pagination_without_a_chosen_order_column_warns(alias):
    """Сортировка взята по первой колонке DDL, а не выбрана осознанно."""
    _, problems = build(
        alias,
        "READ",
        entry("GetAliases", col("id", show=True), annotation="many", pagination=True),
    )
    assert "постраничность без отмеченной колонки ORDER BY" in messages(problems)
    assert all(not problem.fatal for problem in problems)


def test_taken_counter_name_blocks_the_whole_file(alias, tmp_path):
    """Двойника sqlc не простит, а выборка без счётчика — молча другой смысл."""
    settings = crud(
        alias.name,
        READ=[
            entry("GetAliases", col("id", show=True), annotation="many", pagination=True),
            entry("CountGetAliases", col("id", show=True), annotation="one"),
        ],
    )
    _, problems = query_gen.render(settings, [alias])
    assert any(problem.blocks_file for problem in problems)

    target = tmp_path / "query.sql"
    target.write_text("рабочий файл", encoding="utf-8")
    path, _ = query_gen.generate(settings, [alias], target)
    assert path is None
    # Прежний файл остаётся нетронутым: неполный хуже старого.
    assert target.read_text(encoding="utf-8") == "рабочий файл"


def test_pagination_is_ignored_for_one(alias):
    """У одиночной строки страниц нет — счётчик не появляется."""
    text = sql(
        alias,
        "READ",
        entry("GetAlias", col("id", show=True), annotation="one", pagination=True),
    )
    assert "CountGetAlias" not in text
    assert "LIMIT 1;" in text


# --------------------------------------------------------------------- UPDATE


def test_update_sets_unqualified_and_filters_qualified(alias):
    text = sql(
        alias,
        "UPDATE",
        entry(
            "UpdateAlias",
            col("name", set=True),
            col("updated_at", set=True, set_value="now()"),
            col("id", where=True),
        ),
    )
    assert "UPDATE dc.alias\nSET name = @name,\n    updated_at = now()" in text
    assert "WHERE alias.id = @id" in text


def test_update_without_set_columns_is_skipped(alias):
    with pytest.raises(GenerationError):
        build(alias, "UPDATE", entry("UpdateAlias", col("id", where=True)))


def test_update_without_where_is_generated_with_a_warning(alias):
    """Опасно, но осмысленно: запрос пишем, а строку показываем."""
    text, problems = build(alias, "UPDATE", entry("UpdateAlias", col("name", set=True)))
    assert "UPDATE dc.alias\nSET name = @name;" in text
    assert "изменит всю таблицу" in messages(problems)
    assert all(not problem.fatal for problem in problems)


def test_returning_comes_last(alias):
    """`RETURNING` в Postgres пишется после всего остального."""
    text = sql(
        alias,
        "UPDATE",
        entry("UpdateAlias", col("name", set=True), col("id", where=True), annotation="one"),
    )
    assert text.rstrip().endswith("WHERE alias.id = @id\nRETURNING *;")


# --------------------------------------------------------------------- DELETE


def test_delete_is_physical_by_default(alias):
    text = sql(alias, "DELETE", entry("DeleteAlias", col("id", where=True)))
    assert "DELETE FROM dc.alias\nWHERE alias.id = @id;" in text


@pytest.mark.parametrize("mode", [query_gen.SOFT_DELETE, query_gen.UNDELETE])
def test_soft_modes_are_updates(alias, mode):
    """Мягкое и обратное отличаются только значениями, которые проставил автор."""
    text = sql(
        alias,
        "DELETE",
        entry(
            "DeleteAlias",
            col("is_deleted", set=True, set_value="true" if mode == query_gen.SOFT_DELETE else "false"),
            col("id", where=True),
            mode=mode,
        ),
    )
    assert text.count("UPDATE dc.alias\nSET is_deleted = ") == 1
    assert "DELETE FROM" not in text


def test_soft_delete_without_columns_to_set_is_skipped(alias):
    with pytest.raises(GenerationError):
        build(
            alias,
            "DELETE",
            entry("DeleteAlias", col("id", where=True), mode=query_gen.SOFT_DELETE),
        )


def test_delete_without_where_is_generated_with_a_warning(alias):
    text, problems = build(alias, "DELETE", entry("DeleteAlias"))
    assert "DELETE FROM dc.alias;" in text
    assert "заденет всю таблицу" in messages(problems)
    assert all(not problem.fatal for problem in problems)


# --------------------------------------------------------------- custom_query


def test_custom_query_overrides_everything(alias):
    """Из настроек берутся только имя и аннотация — остальное автор пишет сам."""
    text = sql(
        alias,
        "CREATE",
        entry(
            "UpsertAlias",
            col("name"),
            annotation="one",
            custom_query="INSERT INTO dc.alias (name) VALUES (@name) ON CONFLICT DO NOTHING RETURNING *",
        ),
    )
    assert "-- name: UpsertAlias :one" in text
    assert "ON CONFLICT DO NOTHING RETURNING *;" in text
    # Ни собранного тела, ни своего `RETURNING` генератор не добавляет.
    assert text.count("RETURNING") == 1
    assert "VALUES (\n" not in text


def test_custom_query_semicolon_is_not_doubled(alias):
    text = sql(alias, "READ", entry("Raw", custom_query="SELECT 1;"))
    assert "SELECT 1;\n" in text
    assert ";;" not in text


def test_custom_query_is_not_checked_against_the_schema(alias):
    """В таком запросе колонки могут вообще не участвовать — проверять нечего."""
    text, problems = build(
        alias, "READ", entry("Raw", col("нет такой"), custom_query="SELECT 1")
    )
    assert "-- name: Raw" in text
    assert problems == []


# ------------------------------------------------------------ файл целиком


def test_table_header_only_where_something_was_built(alias, user):
    """У таблицы, от которой ничего не собралось, шапки в файле нет."""
    settings = {
        "CRUD": {
            alias.name: {"CREATE": [entry("CreateAlias", col("name"))]},
            # Все запросы этой таблицы пропущены — заголовок висел бы пустым.
            user.name: {"CREATE": [entry("CreateUser")]},
        }
    }
    text, problems = query_gen.render(settings, [alias, user])
    assert "-- dc.alias" in text
    assert '-- dc."user"' not in text
    assert "INSERT без колонок" in messages(problems)


def test_header_is_written_once(alias):
    text = sql(alias, "CREATE", entry("CreateAlias", col("name")))
    assert text.startswith(query_gen.HEADER[0])
    assert text.count(query_gen.HEADER[0]) == 1


def test_query_without_a_name_is_skipped(alias):
    _, problems = build(
        alias, "CREATE", entry("CreateAlias", col("name")), entry("  ", col("name"))
    )
    assert "запрос без названия" in messages(problems)


def test_unknown_column_skips_the_query(alias):
    _, problems = build(
        alias, "CREATE", entry("CreateAlias", col("name")), entry("Broken", col("нет такой"))
    )
    assert "нет таких колонок в схеме: нет такой" in messages(problems)


def test_table_missing_from_the_schema_is_reported(alias):
    settings = {
        "CRUD": {
            alias.name: {"CREATE": [entry("CreateAlias", col("name"))]},
            "dc.gone": {"CREATE": [entry("CreateGone", col("id"))]},
        }
    }
    _, problems = query_gen.render(settings, [alias])
    assert "таблицы нет в схеме" in messages(problems)


def test_nothing_to_generate_is_an_error(alias):
    with pytest.raises(GenerationError):
        query_gen.render({}, [alias])


def test_generate_writes_the_file_and_leaves_no_temporary(alias, tmp_path):
    target = tmp_path / "sub" / "query.sql"
    path, problems = query_gen.generate(
        crud(alias.name, CREATE=[entry("CreateAlias", col("name"))]), [alias], target
    )
    assert path == target
    assert path.read_text(encoding="utf-8").startswith("-- Файл сгенерирован")
    assert [p.name for p in target.parent.iterdir()] == ["query.sql"]
    assert problems == []


def test_generated_file_overwrites_the_old_one(alias, tmp_path):
    """Файл производный: правки в нём затираются без вопросов."""
    target = tmp_path / "query.sql"
    target.write_text("правки руками", encoding="utf-8")
    query_gen.generate(
        crud(alias.name, CREATE=[entry("CreateAlias", col("name"))]), [alias], target
    )
    assert "правки руками" not in target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------- join'ы


@pytest.fixture
def linked(reference_tables):
    """Три таблицы, связанные по порядку: колонка -> таблица -> схема."""
    return [
        table_named(reference_tables, name)
        for name in ("dc.column_cat", "dc.table_cat", "dc.schema_cat")
    ]


def joined(table, *entries, chains=(), tables=None):
    """Текст и проблемы выборок, у которых есть раздел join'ов."""
    settings = crud(table.name, READ=list(entries))
    with_joins(settings, table.name, *chains)
    return query_gen.render(settings, tables)


def joined_sql(table, *entries, chains=(), tables=None) -> str:
    return joined(table, *entries, chains=chains, tables=tables)[0]


def with_user(type: str = "LEFT") -> dict:
    """Цепочка из одного звена: `dc.alias` и её пользователь."""
    return chain("with_user", link("dc.user", "u", "u.id = alias.user_id", type=type))


@pytest.mark.parametrize(
    ("name", "good"),
    [
        ("u", True),
        ("user_table", True),
        # Слово SQL: `@user_id` в запросе прочтётся не так, как задумано.
        ("user", False),
        ("order", False),
        # Из алиаса собирается имя параметра — пробелам и кавычкам там не место.
        ("my alias", False),
        ("Alias", False),
        ("", False),
    ],
)
def test_is_alias_allows_only_simple_names(name, good):
    assert query_gen.is_alias(name) is good


def test_chain_turns_into_join_lines(alias, user):
    """Звено даёт строку `JOIN`, а имя таблицы экранируется как везде."""
    text = joined_sql(
        alias,
        entry(
            "GetAliasesWithUser",
            col("id", show=True),
            annotation="many",
            joins=["with_user"],
            joined=[jcol("with_user", "u", "name", show=True)],
        ),
        chains=[with_user()],
        tables=[alias, user],
    )
    assert 'FROM dc.alias\nLEFT JOIN dc."user" u ON u.id = alias.user_id' in text


def test_links_follow_the_order_of_the_chain(linked):
    """Связь «многие ко многим» — два звена подряд: связующая и целевая."""
    columns, tables, schemas = linked
    text = joined_sql(
        columns,
        entry(
            "GetColumnsWithSchema",
            col("id", show=True),
            annotation="many",
            joins=["with_schema"],
            joined=[jcol("with_schema", "s", "name", show=True)],
        ),
        chains=[
            chain(
                "with_schema",
                link("dc.table_cat", "t", "t.id = column_cat.table_id"),
                link("dc.schema_cat", "s", "s.id = t.schema_id", type="LEFT"),
            )
        ],
        tables=linked,
    )
    assert (
        "FROM dc.column_cat\n"
        "INNER JOIN dc.table_cat t ON t.id = column_cat.table_id\n"
        "LEFT JOIN dc.schema_cat s ON s.id = t.schema_id" in text
    )


def test_joined_column_carries_its_alias_into_the_name(alias, user):
    """`id` есть у обеих таблиц — двух одинаковых имён sqlc не примет."""
    text = joined_sql(
        alias,
        entry(
            "GetAliasesWithUser",
            col("id", show=True),
            annotation="many",
            joins=["with_user"],
            joined=[jcol("with_user", "u", "id", show=True), jcol("with_user", "u", "name", show=True)],
        ),
        chains=[with_user()],
        tables=[alias, user],
    )
    assert "    alias.id,\n    u.id AS u_id,\n    u.name AS u_name" in text


def test_name_taken_after_the_alias_gets_a_number(reference_tables):
    """`alias.id` даёт `alias_id`, а такая колонка у `dc.column_cat` уже своя."""
    columns = table_named(reference_tables, "dc.column_cat")
    aliases = table_named(reference_tables, "dc.alias")
    text = joined_sql(
        columns,
        entry(
            "GetColumnsWithAlias",
            col("alias_id", show=True),
            annotation="many",
            joins=["with_alias"],
            joined=[
                jcol("with_alias", "alias", "id", show=True),
                jcol("with_alias", "alias", "name", show=True),
            ],
        ),
        chains=[
            chain("with_alias", link("dc.alias", "alias", "alias.id = column_cat.alias_id"))
        ],
        tables=[columns, aliases],
    )
    assert (
        "    column_cat.alias_id,\n"
        "    alias.id AS alias_id_2,\n"
        "    alias.name AS alias_name" in text
    )


def test_renamed_column_keeps_its_new_name_everywhere(reference_tables):
    """Параметр и сортировка зовут колонку тем же именем, что видно в ответе."""
    columns = table_named(reference_tables, "dc.column_cat")
    aliases = table_named(reference_tables, "dc.alias")
    text = joined_sql(
        columns,
        entry(
            "GetColumnsWithAlias",
            col("alias_id", show=True),
            annotation="many",
            joins=["with_alias"],
            joined=[
                jcol("with_alias", "alias", "id", show=True, where=True, order_by_optional=True)
            ],
        ),
        chains=[
            chain("with_alias", link("dc.alias", "alias", "alias.id = column_cat.alias_id"))
        ],
        tables=[columns, aliases],
    )
    assert "WHERE alias.id = @alias_id_2" in text
    assert "@order_by::text = 'alias_id_2'" in text


def test_column_written_twice_is_aliased_too(alias):
    """Один и тот же столбец дважды — два одинаковых имени, и sqlc их не примет."""
    text = sql(
        alias,
        "READ",
        entry(
            "GetAlias",
            col("id", show=True),
            col("id", show=True),
            annotation="one",
        ),
    )
    assert "SELECT\n    alias.id,\n    alias.id AS id_2\n" in text


def test_join_without_marked_columns_is_skipped(alias, user):
    """`SELECT *` вернул бы колонки обеих таблиц вперемешку — sqlc такое не примет."""
    text, problems = joined(
        alias,
        entry("Plain", col("id", show=True), annotation="one"),
        entry("Broken", annotation="many", joins=["with_user"]),
        chains=[with_user()],
        tables=[alias, user],
    )
    assert "Broken" not in text
    # Соседний запрос от этого не страдает.
    assert "-- name: Plain :one" in text
    assert "колонки не отмечены" in messages(problems)
    assert [p.fatal for p in problems] == [True]


def test_conditions_on_a_joined_column(alias, user):
    """Параметр называется именем колонки на выходе, а не именем в таблице."""
    text = joined_sql(
        alias,
        entry(
            "GetAliasesWithUser",
            col("id", show=True),
            annotation="many",
            joins=["with_user"],
            joined=[
                jcol("with_user", "u", "id", show=True),
                jcol("with_user", "u", "name", where=True),
                jcol("with_user", "u", "external_id", where_optional=True),
                jcol("with_user", "u", "is_deleted", exact="false"),
            ],
        ),
        chains=[with_user()],
        tables=[alias, user],
    )
    assert "WHERE u.name = @u_name" in text
    assert (
        "(sqlc.narg('u_external_id')::uuid IS NULL "
        "OR u.external_id = sqlc.narg('u_external_id'))" in text
    )
    assert "u.is_deleted = false" in text


def test_ordering_by_a_joined_column(alias, user):
    """Колонку сортировки вызывающий выбирает тем же именем, что видит в ответе."""
    text = joined_sql(
        alias,
        entry(
            "GetAliasesWithUser",
            col("id", show=True),
            annotation="many",
            joins=["with_user"],
            joined=[jcol("with_user", "u", "name", show=True, order_by_optional=True)],
        ),
        chains=[with_user()],
        tables=[alias, user],
    )
    assert "@order_by::text = 'u_name'" in text
    assert "THEN u.name END ASC" in text


def test_counter_repeats_the_joins_of_its_query(alias, user):
    """Считать он обязан ту же выборку — иначе страницы не сойдутся со строками."""
    text = joined_sql(
        alias,
        entry(
            "GetAliasesWithUser",
            col("id", show=True, order_by=True),
            annotation="many",
            pagination=True,
            joins=["with_user"],
            joined=[jcol("with_user", "u", "name", show=True, where=True)],
        ),
        chains=[with_user()],
        tables=[alias, user],
    )
    counter = text.split("-- name: CountGetAliasesWithUser :one")[1]
    assert 'LEFT JOIN dc."user" u ON u.id = alias.user_id' in counter
    assert "WHERE u.name = @u_name" in counter


def test_written_on_goes_into_the_file_as_is(alias, user):
    """Условие пишут руками: разбирать его и что-то в нём править — гадание."""
    text = joined_sql(
        alias,
        entry(
            "GetAliasesWithUser",
            col("id", show=True),
            annotation="many",
            joins=["with_user"],
            joined=[jcol("with_user", "u", "name", show=True)],
        ),
        chains=[
            chain(
                "with_user",
                # Условие скопировали из готового запроса — с ведущим ON и `;`.
                link("dc.user", "u", "ON u.id = alias.user_id AND u.is_deleted = false;"),
            )
        ],
        tables=[alias, user],
    )
    assert "INNER JOIN dc.\"user\" u ON u.id = alias.user_id AND u.is_deleted = false\n" in text


@pytest.mark.parametrize(
    ("chains", "used", "expected"),
    [
        ([], ["with_user"], "не описан"),
        (
            [chain("with_user", link("dc.нет_такой", "u", "u.id = alias.user_id"))],
            ["with_user"],
            "нет в схеме",
        ),
        (
            [chain("with_user", link("dc.user", "user", "u.id = alias.user_id"))],
            ["with_user"],
            "не годится",
        ),
        (
            [chain("with_user", link("dc.user", "alias", "u.id = alias.user_id"))],
            ["with_user"],
            "уже занят",
        ),
        ([chain("with_user", link("dc.user", "u", "   "))], ["with_user"], "без условия ON"),
        (
            [chain("with_user", link("dc.user", "u", "u.id = alias.user_id", type="OUTER"))],
            ["with_user"],
            "неизвестный вид соединения",
        ),
    ],
)
def test_broken_chain_stops_its_query_and_says_why(alias, user, chains, used, expected):
    text, problems = joined(
        alias,
        entry("Plain", col("id", show=True), annotation="one"),
        entry(
            "Broken",
            col("id", show=True),
            annotation="many",
            joins=used,
            joined=[jcol("with_user", "u", "name", show=True)],
        ),
        chains=chains,
        tables=[alias, user],
    )
    assert "Broken" not in text
    assert "-- name: Plain :one" in text
    assert expected in messages(problems)


def test_columns_that_no_longer_match_the_chain_stop_the_query(alias, user):
    """У звена сменили алиас: выкинуть колонку молча — отдать другую выборку."""
    text, problems = joined(
        alias,
        entry("Plain", col("id", show=True), annotation="one"),
        entry(
            "Broken",
            col("id", show=True),
            annotation="many",
            joins=["with_user"],
            # Цепочка знает алиас `u`, а колонка записана на прежний `usr`.
            joined=[jcol("with_user", "usr", "name", show=True)],
        ),
        chains=[with_user()],
        tables=[alias, user],
    )
    assert "Broken" not in text
    assert "-- name: Plain :one" in text
    assert "не сходится с join" in messages(problems)


def test_query_without_joins_is_built_exactly_as_before(alias, user):
    """Раздел join'ов не должен менять выборки, которые его не используют."""
    plain = entry("GetAliases", col("id", show=True), annotation="many")
    text = joined_sql(alias, plain, chains=[with_user()], tables=[alias, user])
    assert "JOIN" not in text
    assert text == sql(alias, "READ", plain)

