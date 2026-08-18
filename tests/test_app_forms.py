"""Логика интерфейса, которую можно проверить без браузера.

Выпадающие списки Quasar под автоматизацией не открываются, поэтому ветки,
зависящие от выбора в списке (`many` в Read, режим в Delete), проверяются
прямым вызовом обработчиков — так же, как описано в CLAUDE.md.
"""

from __future__ import annotations

import pytest

from sgbuddy import app
from sgbuddy.settings import (
    ANNOTATION_KEY,
    COLUMN_NAME_KEY,
    COLUMN_VALUE_KEY,
    COLUMNS_KEY,
    CRUD_KEY,
    CUSTOM_QUERY_KEY,
    EXACT_WHERE_KEY,
    NAME_KEY,
    ORDER_BY_KEY,
    ORDER_BY_OPTIONAL_KEY,
    PAGINATION_KEY,
    SET_KEY,
    SHOW_KEY,
    WHERE_KEY,
)


@pytest.fixture(autouse=True)
def isolated_state(reference_tables, monkeypatch):
    """Состояние — модульные синглтоны: между тестами их надо разводить.

    Перерисовку глушим: вне клиента NiceGUI перерисовывать нечего.
    """
    monkeypatch.setattr(app.wizard, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(app, "form", None)
    monkeypatch.setattr(app, "read_form", None)
    monkeypatch.setattr(app, "update_form", None)
    monkeypatch.setattr(app, "delete_form", None)

    app.workspace.tables = reference_tables
    app.workspace.settings = {}
    yield
    app.workspace.reset()


def entries(table, direction) -> list:
    return app.workspace.settings[CRUD_KEY][table.name][direction]


# ------------------------------------------------------------ имена запросов


@pytest.mark.parametrize(
    ("name", "expected"),
    [("column_cat", "ColumnCat"), ('dc."user"', "DcUser"), ("user", "User"), ("", "")],
)
def test_camel(name, expected):
    assert app.camel(name) == expected


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("Alias", "Aliases"),
        ("ColumnCat", "ColumnCats"),
        ("Host", "Hosts"),
        # Уже множественное число: `levels` кончается на `s` после согласной.
        ("GroupLevels", "GroupLevels"),
        ("Class", "Classes"),
        ("Entity", "Entities"),
        ("Day", "Days"),
        ("", ""),
    ],
)
def test_pluralize_is_predictable_not_clever(word, expected):
    assert app.pluralize(word) == expected


def test_suggested_names_follow_the_table(alias, user):
    assert app.suggest_create_name(alias) == "CreateAlias"
    assert app.suggest_create_name(user) == "CreateUser"


def test_read_name_lists_the_filter_columns(alias):
    draft = app.ReadForm(table=alias.name, annotation="one", where={"id"})
    assert app.suggest_read_name(alias, draft) == "GetAliasById"

    listing = app.ReadForm(table=alias.name, annotation="many", where=set())
    assert app.suggest_read_name(alias, listing) == "GetAliases"


def test_exact_where_does_not_get_into_the_read_name(alias):
    """Заполненный EXACT WHERE сам по себе условия не даёт — только значение."""
    draft = app.ReadForm(
        table=alias.name, annotation="one", where={"id"}, exact={"is_deleted": "false"}
    )
    assert app.suggest_read_name(alias, draft) == "GetAliasById"


def test_update_and_delete_names_count_written_values_too(alias):
    """У изменения и удаления заполненное значение — это и есть условие."""
    update = app.UpdateForm(table=alias.name, where_values={"id": "@id"})
    assert app.suggest_update_name(alias, update) == "UpdateAliasById"

    hard = app.DeleteForm(table=alias.name, mode=app.HARD_DELETE, where={"id"})
    assert app.suggest_delete_name(alias, hard) == "DeleteAliasById"

    # Обратное удаление лежит в файле рядом с мягким: имя — единственное отличие.
    back = app.DeleteForm(table=alias.name, mode=app.UNDELETE, where={"id"})
    assert app.suggest_delete_name(alias, back) == "UndeleteAliasById"


def test_where_fields_keeps_the_ddl_order(alias):
    assert app.where_fields(alias, {"name", "id"}) == ["id", "name"]


# ------------------------------------------------------- уникальность имён


def test_name_is_taken_anywhere_in_the_file(alias, user):
    """sqlc не разрешит двойника нигде, поэтому смотрим весь файл, не таблицу."""
    app.workspace.settings = {
        CRUD_KEY: {
            user.name: {"CREATE": [{NAME_KEY: "CreateThing"}]},
            alias.name: {"READ": [{NAME_KEY: "GetAlias"}]},
        }
    }
    assert app._name_taken("CreateThing", alias.name, "CREATE")
    assert app._name_taken("GetAlias", alias.name, "READ")
    assert not app._name_taken("Свободное", alias.name, "CREATE")


def test_editing_a_query_does_not_collide_with_itself(alias):
    app.workspace.settings = {CRUD_KEY: {alias.name: {"READ": [{NAME_KEY: "GetAlias"}]}}}
    assert app._name_taken("GetAlias", alias.name, "READ")
    assert not app._name_taken("GetAlias", alias.name, "READ", skip=0)


def test_duplicate_name_is_refused_with_an_error(alias):
    app.form = app.CreateForm(table=alias.name, name="CreateAlias")
    app._submit_create(alias)
    assert entries(alias, "CREATE")[0][NAME_KEY] == "CreateAlias"

    app.form = app.CreateForm(table=alias.name, name="CreateAlias")
    app._submit_create(alias)
    assert len(entries(alias, "CREATE")) == 1
    assert "уже есть" in app.form.error


def test_query_without_a_name_is_refused(alias):
    app.form = app.CreateForm(table=alias.name, name="   ")
    app._submit_create(alias)
    assert app.form.error == "укажите название"
    assert app.workspace.settings == {}


# --------------------------------------------------- что попадает в настройки


def test_create_writes_a_parameter_for_an_empty_value(alias):
    """Пустое поле в CREATE означает «приходит параметром» и даёт `@колонка`."""
    app.form = app.CreateForm(
        table=alias.name,
        name="CreateAlias",
        values={"created_at": "now()"},
        excluded={"id"},
    )
    app._submit_create(alias)

    columns = entries(alias, "CREATE")[0][COLUMNS_KEY]
    written = {c[COLUMN_NAME_KEY]: c[COLUMN_VALUE_KEY] for c in columns}
    assert written["name"] == "@name"
    assert written["created_at"] == "now()"
    # Исключённая колонка в запрос не попадает вовсе.
    assert "id" not in written


def test_empty_text_fields_are_written_as_null(alias):
    """Незаполненное поле — `null`, а не `""`: генератору видно, что значения нет."""
    app.read_form = app.ReadForm(
        table=alias.name, name="GetAliases", annotation="many", exact={"name": "  "}
    )
    app._submit_read(alias)

    entry = entries(alias, "READ")[0]
    assert entry[CUSTOM_QUERY_KEY] is None
    columns = {c[COLUMN_NAME_KEY]: c for c in entry[COLUMNS_KEY]}
    assert columns["name"][EXACT_WHERE_KEY] is None


def test_order_keys_appear_only_for_many(alias):
    """У `one` строка одна — порядок ей ни к чему, и ключей в файле быть не должно."""
    app.read_form = app.ReadForm(
        table=alias.name, name="GetAliases", annotation="many", order_by={"id"}
    )
    app._submit_read(alias)
    listing = entries(alias, "READ")[0][COLUMNS_KEY][0]
    assert listing[ORDER_BY_KEY] is True
    assert ORDER_BY_OPTIONAL_KEY in listing

    app.read_form = app.ReadForm(table=alias.name, name="GetAlias", annotation="one")
    app._submit_read(alias)
    single = entries(alias, "READ")[1][COLUMNS_KEY][0]
    assert ORDER_BY_KEY not in single
    assert ORDER_BY_OPTIONAL_KEY not in single


def test_pagination_belongs_to_many_only(alias):
    app.read_form = app.ReadForm(
        table=alias.name, name="GetAlias", annotation="one", pagination=True
    )
    app._submit_read(alias)
    assert entries(alias, "READ")[0][PAGINATION_KEY] is False


def test_read_describes_every_column(alias):
    """Колонки пишутся все: в файле должно быть видно и то, что не отмечено."""
    app.read_form = app.ReadForm(
        table=alias.name,
        name="GetAliasById",
        annotation="one",
        show={"id", "name"},
        where={"id"},
    )
    app._submit_read(alias)

    columns = {c[COLUMN_NAME_KEY]: c for c in entries(alias, "READ")[0][COLUMNS_KEY]}
    assert set(columns) == set(alias.column_names)
    assert columns["id"][SHOW_KEY] is True and columns["id"][WHERE_KEY] is True
    assert columns["description"][SHOW_KEY] is False


def test_soft_delete_writes_the_columns_it_sets(alias):
    """`SOFT DELETE` и `UNDELETE` дают `UPDATE ... SET` — им нужны проставляемые колонки."""
    app.delete_form = app.DeleteForm(
        table=alias.name,
        name="DeleteAliasById",
        mode=app.SOFT_DELETE,
        sets={"is_deleted"},
        set_values={"is_deleted": "true"},
        where={"id"},
    )
    app._submit_delete(alias)

    entry = entries(alias, "DELETE")[0]
    columns = {c[COLUMN_NAME_KEY]: c for c in entry[COLUMNS_KEY]}
    assert columns["is_deleted"][SET_KEY] is True
    assert columns["id"][WHERE_KEY] is True


def test_hard_delete_has_no_set_columns(alias):
    """Физическое удаление ничего не проставляет — ключей `set` в файле нет."""
    app.delete_form = app.DeleteForm(
        table=alias.name, name="DeleteAliasById", mode=app.HARD_DELETE, where={"id"}
    )
    app._submit_delete(alias)

    columns = entries(alias, "DELETE")[0][COLUMNS_KEY]
    assert all(SET_KEY not in column for column in columns)


# ------------------------------------------------------------- разделы таблиц


def test_sections_appear_only_for_tables_with_queries(alias):
    """От простого просмотра в файл не должны падать пустые разделы всех таблиц."""
    app.form = app.CreateForm(table=alias.name, name="CreateAlias")
    app._submit_create(alias)
    assert set(app.workspace.settings[CRUD_KEY]) == {alias.name}


def test_annotation_is_stored_as_chosen(alias):
    app.form = app.CreateForm(table=alias.name, name="CreateAlias", annotation="one")
    app._submit_create(alias)
    assert entries(alias, "CREATE")[0][ANNOTATION_KEY] == "one"
