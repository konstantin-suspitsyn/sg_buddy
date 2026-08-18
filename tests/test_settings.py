"""Формат `schema.json`: порядок шапки, пути, чтение старых файлов, миграция."""

from __future__ import annotations

import json

import pytest

from sgbuddy import settings as st


HEAD = (
    st.DESCRIPTION_KEY,
    st.SCHEMA_FOLDER_KEY,
    st.SAVE_PROTO_KEY,
    st.PROTO_PACKAGE_KEY,
    st.GO_PACKAGE_KEY,
)


# ----------------------------------------------------------------------- шапка


def test_head_keys_come_first_and_in_order():
    """Первые пять ключей — то, что мастер спрашивает до разбора схемы."""
    data = st.default_settings("C:/dc", "C:/dc/api.proto", "example.com/pkg", "api.v1")
    assert tuple(data)[:5] == HEAD


def test_with_paths_keeps_head_first_over_existing_content():
    """Файл могли править руками: шапка обязана остаться сверху, а не где придётся."""
    old = {st.CRUD_KEY: {}, "чужой ключ": 1, st.SCHEMA_FOLDER_KEY: "C:/old"}
    data = st.with_paths(old, "C:/dc", "C:/dc/api.proto", "example.com/pkg", "api.v1")
    assert tuple(data)[:5] == HEAD
    assert data[st.SCHEMA_FOLDER_KEY] == "C:\\dc"
    # Всё, чего мастер не спрашивал, переносится как есть.
    assert data["чужой ключ"] == 1
    assert st.CRUD_KEY in data


def test_description_is_a_signature_not_a_field():
    """`description` — подпись программы: что бы в нём ни лежало, оно переписывается."""
    data = st.with_paths({st.DESCRIPTION_KEY: "своё"}, "C:/dc", "C:/dc/api.proto")
    assert data[st.DESCRIPTION_KEY] == st.DESCRIPTION


# ------------------------------------------------------------------------ пути


def test_paths_are_written_with_backslashes():
    """Путь из файла копируют в проводник — разделитель в файле один."""
    assert st.windows_path("C:/dc/schema") == "C:\\dc\\schema"
    assert st.windows_path("C:\\dc\\schema") == "C:\\dc\\schema"


def test_packages_are_not_paths():
    """Слэши в `go_package` — часть имени импорта, ломать их нельзя."""
    data = st.with_paths({}, "C:/dc", "C:/dc/api.proto", "example.com/pkg;pkg", "api.v1")
    assert data[st.GO_PACKAGE_KEY] == "example.com/pkg;pkg"
    assert data[st.PROTO_PACKAGE_KEY] == "api.v1"


def test_settings_path_is_next_to_the_schema(tmp_path):
    assert st.settings_path(tmp_path).name == st.SETTINGS_FILENAME
    assert st.settings_path(tmp_path).parent == tmp_path


# ------------------------------------------------------------- чтение и запись


def test_save_and_load_roundtrip(tmp_path):
    data = st.default_settings(tmp_path, tmp_path / "api.proto")
    data[st.CRUD_KEY] = {'dc."user"': {"CREATE": [{st.NAME_KEY: "CreateUser"}]}}

    path = st.save_settings(data, st.settings_path(tmp_path))
    assert st.load_settings(path) == data


def test_saved_file_is_readable_json_with_cyrillic(tmp_path):
    """Пояснение в файле читают глазами: `\\u0424` вместо букв там не нужен."""
    path = st.save_settings(st.default_settings("C:/dc", "C:/dc/api.proto"), tmp_path / "s.json")
    text = path.read_text(encoding="utf-8")
    assert "SG Buddy" in text
    assert "\\u" not in text
    assert text.endswith("\n")
    assert json.loads(text)


def test_saving_leaves_no_temporary_file(tmp_path):
    """Пишем через временный, но после записи в папке только сам файл."""
    st.save_settings({"a": 1}, tmp_path / "s.json")
    assert [p.name for p in tmp_path.iterdir()] == ["s.json"]


@pytest.mark.parametrize(
    "header",
    [
        "// Файл создан программой SG Buddy\n// Правки затираются\n",
        # Пустой строки между шапкой и телом могло и не быть.
        "// Файл создан программой SG Buddy\n",
        "\n\n",
        "",
    ],
)
def test_old_jsonc_header_is_stripped(tmp_path, header):
    """Файлы прежнего формата начинались со строк `//` — падать на них нельзя."""
    path = tmp_path / "schema.json"
    path.write_text(header + '{"a": 1}\n', encoding="utf-8")
    assert st.load_settings(path) == {"a": 1}


def test_load_rejects_non_object(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        st.load_settings(path)


# -------------------------------------------------------------------- разделы


def test_directions_are_created_only_on_write():
    """От простого просмотра в файл не должны падать пустые разделы всех таблиц."""
    data = {}
    assert st.directions_of(data, "dc.alias") == {}
    assert st.entries_of(data, "dc.alias", "CREATE") == []
    assert data == {}

    section = st.ensure_directions(data, "dc.alias")
    assert tuple(section) == st.DIRECTIONS
    assert data[st.CRUD_KEY]["dc.alias"] is section


def test_ensure_directions_keeps_what_is_already_there():
    data = {st.CRUD_KEY: {"dc.alias": {"CREATE": [{st.NAME_KEY: "CreateAlias"}]}}}
    section = st.ensure_directions(data, "dc.alias")
    assert section["CREATE"] == [{st.NAME_KEY: "CreateAlias"}]
    assert section["READ"] == []


def test_all_entries_walks_the_whole_file():
    """Имена запросов уникальны по всему файлу, поэтому обход — по всем таблицам."""
    data = {
        st.CRUD_KEY: {
            "dc.alias": {"CREATE": [{st.NAME_KEY: "A"}], "READ": [{st.NAME_KEY: "B"}]},
            "dc.host": {"DELETE": [{st.NAME_KEY: "C"}]},
        }
    }
    found = [(table, direction, index, e[st.NAME_KEY]) for table, direction, index, e in st.all_entries(data)]
    assert found == [
        ("dc.alias", "CREATE", 0, "A"),
        ("dc.alias", "READ", 0, "B"),
        ("dc.host", "DELETE", 0, "C"),
    ]


# -------------------------------------------------------------------- миграция


def test_flat_crud_is_moved_under_tables():
    """Старый формат лежит на дисках: `CRUD -> CREATE -> [{Table: ...}]`."""
    old = {
        st.CRUD_KEY: {
            "CREATE": [
                {"Table": "dc.alias", st.NAME_KEY: "CreateAlias"},
                {"Table": "dc.host", st.NAME_KEY: "CreateHost"},
            ],
            "READ": [{"Table": "dc.alias", st.NAME_KEY: "GetAliases"}],
        }
    }
    data = st.migrate_crud(old)

    assert set(data[st.CRUD_KEY]) == {"dc.alias", "dc.host"}
    alias_section = data[st.CRUD_KEY]["dc.alias"]
    assert tuple(alias_section) == st.DIRECTIONS
    assert alias_section["CREATE"] == [{st.NAME_KEY: "CreateAlias"}]
    assert alias_section["READ"] == [{st.NAME_KEY: "GetAliases"}]
    # Таблица теперь ключом выше — внутри записи ей делать нечего.
    assert "Table" not in alias_section["CREATE"][0]


def test_entry_without_table_is_not_lost():
    """Записи без таблицы уходят в `?`, а не выбрасываются молча."""
    data = st.migrate_crud({st.CRUD_KEY: {"CREATE": [{st.NAME_KEY: "Orphan"}]}})
    assert data[st.CRUD_KEY]["?"]["CREATE"] == [{st.NAME_KEY: "Orphan"}]


def test_current_format_is_left_alone():
    data = {st.CRUD_KEY: {"dc.alias": {"CREATE": [{st.NAME_KEY: "CreateAlias"}]}}}
    assert st.migrate_crud(dict(data)) == data


def test_migration_of_empty_settings_is_harmless():
    assert st.migrate_crud({}) == {}
