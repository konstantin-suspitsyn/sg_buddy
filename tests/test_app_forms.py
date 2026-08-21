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
    JOIN_ALIAS_KEY,
    JOIN_NAME_KEY,
    JOIN_ON_KEY,
    JOIN_TABLE_KEY,
    JOIN_TYPE_KEY,
    JOINED_COLUMNS_KEY,
    JOINS_KEY,
    LINKS_KEY,
    NAME_KEY,
    ORDER_BY_KEY,
    ORDER_BY_OPTIONAL_KEY,
    PAGINATION_KEY,
    SET_KEY,
    SHOW_KEY,
    USED_JOINS_KEY,
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
    monkeypatch.setattr(app, "join_form", None)

    app.workspace.tables = reference_tables
    app.workspace.settings = {}
    yield
    app.workspace.reset()


def entries(table, direction) -> list:
    return app.workspace.settings[CRUD_KEY][table.name][direction]


def chains(table) -> list:
    return app.workspace.settings[JOINS_KEY][table.name]


def add_chain(table, name: str = "with_user", alias: str = "u", **rest) -> None:
    """Цепочка `dc.alias` -> `dc."user"`, добавленная через форму."""
    app.join_form = app.JoinForm(
        table=table.name,
        name=name,
        links=[
            app.JoinLink(
                type=rest.get("type", "LEFT"),
                table=rest.get("joined", "dc.user"),
                alias=alias,
                on=rest.get("on", "u.id = alias.user_id"),
            )
        ],
    )
    app._submit_join(table)


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


# ---------------------------------------------------------------------- join'ы


def test_chain_is_written_with_its_links(alias):
    """Звеньев столько, сколько таблиц присоединяется, и в порядке записи."""
    app.join_form = app.JoinForm(
        table=alias.name,
        name="with_user",
        links=[
            app.JoinLink("INNER", "dc.host", "h", "h.id = alias.id"),
            app.JoinLink("LEFT", "dc.user", "u", "u.id = alias.user_id"),
        ],
    )
    app._submit_join(alias)

    chain = chains(alias)[0]
    assert chain[NAME_KEY] == "with_user"
    assert [link[JOIN_ALIAS_KEY] for link in chain[LINKS_KEY]] == ["h", "u"]
    assert chain[LINKS_KEY][1] == {
        JOIN_TYPE_KEY: "LEFT",
        JOIN_TABLE_KEY: "dc.user",
        JOIN_ALIAS_KEY: "u",
        JOIN_ON_KEY: "u.id = alias.user_id",
    }
    # Черновик живёт до «Добавить» — после записи его нет.
    assert app.join_form is None


def test_join_section_appears_only_for_tables_with_chains(alias):
    add_chain(alias)
    assert set(app.workspace.settings[JOINS_KEY]) == {alias.name}


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        (app.JoinLink("LEFT", "", "u", "u.id = alias.user_id"), "выберите таблицу"),
        (app.JoinLink("LEFT", "dc.нет", "u", "u.id = alias.user_id"), "выберите таблицу"),
        # Из алиаса собираются имена колонок и параметров.
        (app.JoinLink("LEFT", "dc.user", "user", "u.id = alias.user_id"), "не годится"),
        (app.JoinLink("LEFT", "dc.user", "u u", "u.id = alias.user_id"), "не годится"),
        (app.JoinLink("LEFT", "dc.user", "", "u.id = alias.user_id"), "не годится"),
        # Алиас своей таблицы занят ею самой.
        (app.JoinLink("LEFT", "dc.user", "alias", "u.id = alias.user_id"), "уже занят"),
        (app.JoinLink("LEFT", "dc.user", "u", "   "), "условие ON"),
    ],
)
def test_join_form_refuses_a_link_it_cannot_write(alias, link, expected):
    app.join_form = app.JoinForm(table=alias.name, name="with_user", links=[link])
    app._submit_join(alias)

    assert expected in app.join_form.error
    assert JOINS_KEY not in app.workspace.settings


def test_chain_needs_a_name(alias):
    app.join_form = app.JoinForm(
        table=alias.name, links=[app.JoinLink("LEFT", "dc.user", "u", "u.id = alias.user_id")]
    )
    app._submit_join(alias)
    assert "укажите название" in app.join_form.error


def test_chain_name_is_unique_within_the_table(alias):
    add_chain(alias)
    add_chain(alias, alias="u2")

    assert len(chains(alias)) == 1
    assert "уже есть" in app.join_form.error


def test_alias_is_suggested_from_the_table_name(alias):
    draft = app.JoinForm(table=alias.name)
    assert app.suggest_alias(draft, alias, "dc.host") == "host"
    # Короткое имя — слово SQL: такой алиас не годится, придумывать за автора нечего.
    assert app.suggest_alias(draft, alias, "dc.user") == ""
    # Занятый алиас разводим номером, а не молча повторяем.
    draft.links = [app.JoinLink("LEFT", "dc.host", "host", "")]
    assert app.suggest_alias(draft, alias, "dc.host") == "host2"


def test_link_can_be_added_and_the_last_one_stays(alias):
    """Цепочка без звеньев — не цепочка: пустое звено заводится заново."""
    app.join_form = app.JoinForm(table=alias.name)
    app._add_link()
    assert len(app.join_form.links) == 2

    app._remove_link(1)
    app._remove_link(0)
    assert len(app.join_form.links) == 1


def read_with_chain(alias, name: str = "GetAliasesWithUser") -> None:
    app.read_form = app.ReadForm(
        table=alias.name,
        name=name,
        annotation="many",
        show={"id"},
        joins={"with_user"},
        joined_show={("with_user", "u", "name")},
        joined_where={("with_user", "u", "id")},
        joined_exact={("with_user", "u", "is_deleted"): "false"},
    )
    app._submit_read(alias)


def test_read_writes_join_keys_only_when_they_are_used(alias):
    """У выборки без join'ов запись остаётся такой же, какой была до раздела."""
    add_chain(alias)

    app.read_form = app.ReadForm(table=alias.name, name="GetAliases", annotation="many")
    app._submit_read(alias)
    plain = entries(alias, "READ")[0]
    assert USED_JOINS_KEY not in plain and JOINED_COLUMNS_KEY not in plain

    read_with_chain(alias)
    joined = entries(alias, "READ")[1]
    assert joined[USED_JOINS_KEY] == ["with_user"]


def test_read_describes_every_joined_column(alias, user):
    """Колонки пишутся все: в файле должно быть видно и то, что не отмечено."""
    add_chain(alias)
    read_with_chain(alias)

    columns = entries(alias, "READ")[0][JOINED_COLUMNS_KEY]
    assert [c[COLUMN_NAME_KEY] for c in columns] == list(user.column_names)
    written = {c[COLUMN_NAME_KEY]: c for c in columns}
    assert {c[JOIN_NAME_KEY] for c in columns} == {"with_user"}
    assert {c[JOIN_ALIAS_KEY] for c in columns} == {"u"}
    assert written["name"][SHOW_KEY] is True
    assert written["id"][WHERE_KEY] is True
    assert written["is_deleted"][EXACT_WHERE_KEY] == "false"
    # Незаполненное поле — `null`, как и у своих колонок.
    assert written["name"][EXACT_WHERE_KEY] is None


def test_editing_returns_joined_flags_to_the_form(alias):
    """Круг «открыть — сохранить» не должен терять отметки приджойненных колонок."""
    add_chain(alias)
    read_with_chain(alias)
    before = entries(alias, "READ")[0]

    app._edit_read(0, alias)
    assert app.read_form.joins == {"with_user"}
    assert app.read_form.joined_show == {("with_user", "u", "name")}
    assert app.read_form.joined_where == {("with_user", "u", "id")}
    assert app.read_form.joined_exact == {("with_user", "u", "is_deleted"): "false"}

    app._submit_read(alias)
    assert entries(alias, "READ")[0] == before


def test_renaming_a_chain_follows_into_the_queries(alias):
    """Выборка ссылается на цепочку по имени: со старым именем она не соберётся."""
    add_chain(alias)
    read_with_chain(alias)

    app._edit_join(0, alias)
    app.join_form.name = "with_owner"
    app._submit_join(alias)

    entry = entries(alias, "READ")[0]
    assert entry[USED_JOINS_KEY] == ["with_owner"]
    assert {c[JOIN_NAME_KEY] for c in entry[JOINED_COLUMNS_KEY]} == {"with_owner"}


def test_removing_a_chain_clears_it_from_the_queries(alias):
    """Ссылка на исчезнувшую цепочку сорвала бы генерацию всего запроса."""
    add_chain(alias)
    read_with_chain(alias)

    app._remove_join(0, alias)

    entry = entries(alias, "READ")[0]
    assert entry[USED_JOINS_KEY] == []
    assert entry[JOINED_COLUMNS_KEY] == []
    assert chains(alias) == []


# ------------------------------------------------------------- копия запроса


DIRECTIONS_TO_COPY = [
    (
        "CREATE",
        "form",
        lambda table: app.CreateForm(table=table.name, name="CreateAlias"),
        app._submit_create,
        app._copy_create,
    ),
    (
        "READ",
        "read_form",
        lambda table: app.ReadForm(table=table.name, name="GetAliases", annotation="many"),
        app._submit_read,
        app._copy_read,
    ),
    (
        "UPDATE",
        "update_form",
        lambda table: app.UpdateForm(table=table.name, name="UpdateAlias", sets={"name"}),
        app._submit_update,
        app._copy_update,
    ),
    (
        "DELETE",
        "delete_form",
        lambda table: app.DeleteForm(
            table=table.name, name="DeleteAlias", mode=app.SOFT_DELETE, sets={"is_deleted"}
        ),
        app._submit_delete,
        app._copy_delete,
    ),
]


@pytest.mark.parametrize(
    ("direction", "attr", "draft", "submit", "copy"),
    DIRECTIONS_TO_COPY,
    ids=[item[0] for item in DIRECTIONS_TO_COPY],
)
def test_copy_repeats_the_record_in_a_new_one(alias, direction, attr, draft, submit, copy):
    """Копия — та же запись новой: сохранение ляжет рядом, а не поверх исходной."""
    setattr(app, attr, draft(alias))
    submit(alias)
    original = dict(entries(alias, direction)[0])

    copy(0, alias)
    form = getattr(app, attr)
    # `editing` пуст — форма предлагает «Добавить», а не «Сохранить».
    assert form.editing is None
    # Имя переносится как есть: придумывать за автора новое здесь нечего.
    assert form.name == original[NAME_KEY]

    form.name = original[NAME_KEY] + "Copy"
    submit(alias)

    listing = entries(alias, direction)
    assert len(listing) == 2
    assert listing[0] == original
    assert listing[1] == {**original, NAME_KEY: original[NAME_KEY] + "Copy"}


def test_copy_of_a_read_carries_its_joins(alias):
    """«Абсолютно те же настройки» — вместе с цепочками и их колонками."""
    add_chain(alias)
    read_with_chain(alias)
    original = dict(entries(alias, "READ")[0])

    app._copy_read(0, alias)
    assert app.read_form.joins == {"with_user"}
    assert app.read_form.joined_show == {("with_user", "u", "name")}

    app.read_form.name = "GetAliasesWithUserCopy"
    app._submit_read(alias)

    copy = entries(alias, "READ")[1]
    assert copy[USED_JOINS_KEY] == original[USED_JOINS_KEY]
    assert copy[JOINED_COLUMNS_KEY] == original[JOINED_COLUMNS_KEY]


def test_copy_saved_under_the_same_name_is_refused(alias):
    """Имя запроса уникально по всему файлу — двойника sqlc не простит."""
    app.form = app.CreateForm(table=alias.name, name="CreateAlias")
    app._submit_create(alias)

    app._copy_create(0, alias)
    app._submit_create(alias)

    assert "уже есть" in app.form.error
    assert len(entries(alias, "CREATE")) == 1


def test_copy_of_a_chain_repeats_its_links(alias):
    """Цепочки соседних таблиц отличаются звеном — копию правят, а не набирают."""
    app.join_form = app.JoinForm(
        table=alias.name,
        name="with_user",
        links=[
            app.JoinLink("INNER", "dc.host", "h", "h.id = alias.id"),
            app.JoinLink("LEFT", "dc.user", "u", "u.id = alias.user_id"),
        ],
    )
    app._submit_join(alias)
    original = dict(chains(alias)[0])

    app._copy_join(0, alias)
    assert app.join_form.editing is None
    assert app.join_form.name == "with_user"
    assert [link.alias for link in app.join_form.links] == ["h", "u"]
    assert [link.type for link in app.join_form.links] == ["INNER", "LEFT"]
    assert [link.on for link in app.join_form.links] == [
        "h.id = alias.id",
        "u.id = alias.user_id",
    ]

    app.join_form.name = "with_user_and_host"
    app._submit_join(alias)

    assert chains(alias)[0] == original
    assert chains(alias)[1] == {**original, NAME_KEY: "with_user_and_host"}


def test_copy_of_a_chain_under_the_same_name_is_refused(alias):
    """Имя цепочки уникально в пределах таблицы — ссылки выборок по нему и ходят."""
    add_chain(alias)

    app._copy_join(0, alias)
    app._submit_join(alias)

    assert "уже есть" in app.join_form.error
    assert len(chains(alias)) == 1


def test_copying_a_chain_does_not_touch_the_queries(alias):
    """Копия — новая цепочка: выборки продолжают ссылаться на исходную."""
    add_chain(alias)
    read_with_chain(alias)

    app._copy_join(0, alias)
    app.join_form.name = "with_owner"
    app._submit_join(alias)

    entry = entries(alias, "READ")[0]
    assert entry[USED_JOINS_KEY] == ["with_user"]
    assert {c[JOIN_NAME_KEY] for c in entry[JOINED_COLUMNS_KEY]} == {"with_user"}

