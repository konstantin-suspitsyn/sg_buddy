"""Генератор `.proto` по настройкам из `schema.json`.

Контракт описывает те же запросы, что и `query.sql`, поэтому правила перевода
привязаны к собранному SQL, а не к настройкам напрямую:

* `package` и `option go_package` — то, что спросил мастер и записал в
  `schema.json`; из имени схемы Postgres они не выводятся. Нет ответа — нет и
  строки: пустыми они файл сломают;
* на таблицу — сообщение со всеми её колонками: это строка, какой её вернёт
  `SELECT *` и `RETURNING *`;
* на запрос — пара сообщений `<Имя>Request`/`<Имя>Response` и метод в сервисе
  таблицы `<Таблица>Service`;
* поля запроса — параметры **готового SQL** в порядке появления. Читаем их из
  запроса, а не из настроек: параметр приходит и из значения, написанного руками
  (`... WHERE u.external_id = @external_id`), и из `custom_query`;
* тип параметра ищется по порядку: колонка своей таблицы, приведение из SQL
  (`@id::uuid`), колонка того же имени в других таблицах схемы — параметр часто
  приходит из подзапроса по соседней таблице. Не нашлось нигде — `string`
  и строка в проблемах;
* необязательный фильтр (`sqlc.narg`) и колонка, допускающая `NULL`, дают
  `optional`-поле;
* ответ зависит от аннотации: `exec` — пустое сообщение, `one` — одна строка,
  `many` — `repeated`; у `DELETE` строки нет никогда;
* **постраничность описывается целиком**: в запрос добавляются `page_limit` и
  `page` (номер страницы, `OFFSET` считается из него в SQL); строки постраничного
  ответа лежат в поле `data` (не `rows`), а рядом — поле `pagination` сообщением
  `Pagination` (одно на файл: `page`, `per_page`, `total_items`, `total_pages`).
  `total_items`/`total_pages` берутся из парного счётчика `Count<имя>`;
* выборка с явным списком колонок получает своё сообщение строки `<Имя>Row` —
  в ответе должно быть видно ровно то, что выгружается, а не вся таблица;
* сортировка: выбираемая колонка и направление приходят готовыми параметрами
  SQL — `order_by` и `order` (оба `string`), — тип берётся из приведения в
  запросе, второй раз генератор его не выбирает. `order` принимает ровно
  `ASC`/`DESC`, не `bool`: по имени параметра не видно, что значит `true`,
  а по строке видно. Обоим полям генератор добавляет строку с
  допустимыми значениями. Обычные колонки сортировки параметрами не
  становятся и по полям не видны — шапка запроса называет порядок по
  умолчанию;
* над каждым сообщением — строка-комментарий: что за запрос и что в сообщении
  лежит. По имени `GetAliasesRow` этого не видно, а контракт читают чаще, чем
  настройки, из которых он собран.

Запрос, который не собрался в SQL, не попадает и в контракт: причина та же и
формулирует её генератор SQL. Файл перезаписывается целиком.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import query_gen
from .ddl import Column, Table
from .query_gen import GenerationError, Problem
from .settings import (
    ANNOTATION_KEY,
    COLUMN_NAME_KEY,
    COLUMNS_KEY,
    CRUD_KEY,
    DIRECTIONS,
    GO_PACKAGE_KEY,
    PROTO_PACKAGE_KEY,
    MODE_KEY,
    NAME_KEY,
    PAGINATION_KEY,
    SHOW_KEY,
)

HEADER = (
    "// Файл сгенерирован программой SG Buddy https://github.com/konstantin-suspitsyn/sg_buddy",
    "// Правки будут затёрты при следующей генерации: правьте настройки, а не этот файл.",
)

# Шапка таблицы — как в query.sql, только комментарий протобуфовский.
_TABLE_RULE = "// " + "=" * 57

SYNTAX = 'syntax = "proto3";'
TIMESTAMP = "google.protobuf.Timestamp"
TIMESTAMP_IMPORT = 'import "google/protobuf/timestamp.proto";'

# Постраничность в запросе. Имена те же, что у параметров SQL.
PAGE_PARAMS = ("page_limit", "page")
PAGE_REQUEST = (("int32", "page_limit"), ("int32", "page"))

# Постраничность в ответе — одно сообщение на файл, а не пара счётчиков в
# каждом Response: `page`/`per_page` в ответе дублируют то, что вызывающий
# сам прислал в запросе, `total_items`/`total_pages` — из парного счётчика.
PAGINATION_MESSAGE = "Pagination"
PAGINATION_FIELDS = (
    ("int32", "page"),
    ("int32", "per_page"),
    ("int64", "total_items"),
    ("int64", "total_pages"),
)

# Postgres -> proto. Сопоставление по началу типа: `varchar(255)` и `varchar` —
# одно и то же. Порядок важен: `integer` обязан проверяться раньше `int`.
_TYPES = (
    ("bigserial", "int64"),
    ("bigint", "int64"),
    ("int8", "int64"),
    ("smallserial", "int32"),
    ("smallint", "int32"),
    ("serial", "int32"),
    ("integer", "int32"),
    ("int4", "int32"),
    ("int2", "int32"),
    ("int", "int32"),
    ("boolean", "bool"),
    ("bool", "bool"),
    ("double precision", "double"),
    ("float8", "double"),
    ("real", "float"),
    ("float4", "float"),
    # numeric и money — строкой: в double они теряют точность, а это деньги.
    ("numeric", "string"),
    ("decimal", "string"),
    ("money", "string"),
    ("timestamptz", TIMESTAMP),
    ("timestamp", TIMESTAMP),
    ("date", TIMESTAMP),
    ("time", TIMESTAMP),
    ("bytea", "bytes"),
    ("character varying", "string"),
    ("varchar", "string"),
    ("character", "string"),
    ("char", "string"),
    ("text", "string"),
    ("uuid", "string"),
    ("jsonb", "string"),
    ("json", "string"),
    ("inet", "string"),
)

_WORD = re.compile(r"[^0-9A-Za-z]+")

# Чем запрос является — для строки над сообщением. Удаление ещё и по режиму:
# мягкое и обратное — не то же самое, что физическое.
_KINDS = {
    "CREATE": "Вставка",
    "READ": "Выборка",
    "UPDATE": "Изменение",
    "DELETE": "Удаление",
}
_DELETE_KINDS = {
    query_gen.SOFT_DELETE: "Мягкое удаление",
    query_gen.UNDELETE: "Обратное удаление",
}


@dataclass
class _Field:
    """Поле сообщения. Номера расставляются при печати, по порядку."""

    type: str
    name: str
    repeated: bool = False
    optional: bool = False
    # Строка над полем. Нужна там, где имени мало: флаг сортировки сам по себе
    # не говорит, по какой колонке он упорядочит выборку.
    comment: str | None = None


@dataclass
class _Built:
    """Что дал один запрос: сообщения, метод сервиса и нужна ли строка таблицы."""

    messages: list[str] = field(default_factory=list)
    rpc: str = ""
    uses_row: bool = False
    uses_pagination: bool = False


def render(settings: dict, tables: list[Table]) -> tuple[str, list[Problem]]:
    """Собирает текст `.proto`. Несобравшиеся запросы пропускает, но называет."""
    by_name = {table.name: table for table in tables}
    problems: list[Problem] = []
    taken = query_gen.query_names(settings)
    index = _column_index(tables)

    sections: list[str] = []
    uses_pagination = False

    for table_name, directions in (settings.get(CRUD_KEY) or {}).items():
        table = by_name.get(table_name)
        if table is None:
            problems.append(
                Problem(table_name, "—", "таблицы нет в схеме — все её запросы пропущены")
            )
            continue

        built = [
            result
            for direction in DIRECTIONS
            for entry in directions.get(direction) or []
            if (result := _entry(direction, entry, table, taken, index, problems))
            is not None
        ]
        if not built:
            continue

        uses_pagination = uses_pagination or any(item.uses_pagination for item in built)
        sections.append(_section(table, built, problems))

    if not sections:
        raise GenerationError("в настройках нет ни одного запроса")

    # Сообщение постраничности общее для всего файла, поэтому не в секции
    # таблицы, а перед всеми ими — ровно один раз, если хоть кому-то нужно.
    if uses_pagination:
        sections.insert(0, _pagination_message())

    body = "\n\n".join(sections)
    head = [*HEADER, "", SYNTAX]

    # Обе шапки спрашивает мастер и по имени схемы не выводит. В старых
    # настройках их нет — тогда нет и строк: пустые `package ;` и
    # `option go_package = ""` protoc не примет.
    proto_package = (settings.get(PROTO_PACKAGE_KEY) or "").strip()
    if proto_package:
        head += ["", f"package {proto_package};"]

    go_package = (settings.get(GO_PACKAGE_KEY) or "").strip()
    if go_package:
        head += ["", f'option go_package = "{go_package}";']

    if TIMESTAMP in body:
        head += ["", TIMESTAMP_IMPORT]

    # Перевод строки в конце — как в query.sql: файл без него ломает `git diff`
    # и часть редакторов.
    return "\n".join([*head, "", body]) + "\n", problems


def generate(
    settings: dict, tables: list[Table], path: str | Path
) -> tuple[Path, list[Problem]]:
    """Пишет файл через временный: прерванная запись не должна его порвать."""
    text, problems = render(settings, tables)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target, problems


# ---------------------------------------------------------------- один запрос


def _entry(
    direction: str,
    entry: dict,
    table: Table,
    taken: set[str],
    index: dict[str, list[tuple[str, Column]]],
    problems: list[Problem],
) -> _Built | None:
    """Сообщения и метод одного запроса. `None` — запрос не собрался в SQL."""
    name = (entry.get(NAME_KEY) or "").strip()

    # Контракт описывает то, что реально уйдёт в базу, поэтому спрашиваем SQL у
    # его генератора. Свои правила завели бы вторую версию тех же правил — вместе
    # с правилами и все проблемы: предупреждение вроде «постраничность без
    # ORDER BY» относится и к .proto ровно так же, как к query.sql.
    sql_problems: list[Problem] = []
    sql = query_gen.entry_sql(direction, entry, table, taken, sql_problems)
    problems.extend(sql_problems)
    if sql is None:
        return None

    annotation = (
        entry.get(ANNOTATION_KEY) or query_gen.DEFAULT_ANNOTATION[direction]
    ).strip()
    paged = bool(entry.get(PAGINATION_KEY)) and direction == "READ" and annotation == "many"

    kind = _kind(direction, entry)
    # Сортировку спрашиваем у генератора SQL: правило `ELSE` — его, и контракт
    # обязан называть ту же колонку, что запрос.
    order = query_gen.ordering(entry, table, always=direction == "READ" and annotation == "many")
    request = _request(sql, table, name, paged, index, order, problems)
    row_type, row_message, uses_row = _row(
        direction, entry, table, name, annotation, kind, problems
    )
    response = _response(row_type, table, annotation, paged)

    messages = [
        _message(f"{name}Request", request, _request_comment(kind, name, order))
    ]
    if row_message is not None:
        messages.append(row_message)
    messages.append(
        _message(f"{name}Response", response, _response_comment(kind, name, annotation, paged))
    )

    return _Built(
        messages=messages,
        rpc=f"  rpc {name}({name}Request) returns ({name}Response);",
        uses_row=uses_row,
        uses_pagination=paged,
    )


def _request(
    sql: str,
    table: Table,
    query: str,
    paged: bool,
    index: dict[str, list[tuple[str, Column]]],
    order: query_gen.Ordering,
    problems: list[Problem],
) -> list[_Field]:
    """Поля запроса: параметры SQL, а следом — постраничность."""
    fields: list[_Field] = []

    for param in query_gen.params(sql):
        # Постраничность добавляем сами и всегда парой: в SQL те же параметры
        # встречаются ещё и в счётчике, порядок там ни о чём не говорит.
        if param.name in PAGE_PARAMS:
            continue

        proto, optional = _param_type(param, table, query, index, problems)
        # У полей выбора колонки и направления по имени не видно, что можно
        # выбрать — это единственные параметры, которым нужна подсказка.
        if param.name == "order_by" and order.optional:
            comment = "допустимые значения: " + ", ".join(order.optional)
        elif param.name == "order":
            comment = f"допустимые значения: {query_gen.ASCENDING}, {query_gen.DESCENDING}"
        else:
            comment = None
        fields.append(
            _Field(
                proto,
                param.name,
                optional=optional and proto != TIMESTAMP,
                comment=comment,
            )
        )

    if paged:
        fields += [_Field(proto, name) for proto, name in PAGE_REQUEST]
    return fields


def _param_type(
    param: query_gen.Param,
    table: Table,
    query: str,
    index: dict[str, list[tuple[str, Column]]],
    problems: list[Problem],
) -> tuple[str, bool]:
    """Тип параметра и признак `optional`.

    Порядок источников: своя колонка, потом приведение, написанное в SQL, потом
    колонка того же имени в других таблицах схемы. Приведение выше чужой колонки
    намеренно: его автор написал руками именно про этот параметр, а совпадение
    имён — всего лишь догадка.
    """
    column = table.column(param.name)
    if column is not None:
        return _column_type(column, table.name, query, problems), (
            param.optional or column.nullable
        )

    cast = _proto_type(param.cast or "")
    if cast is not None:
        return cast, param.optional

    foreign = _foreign_column(param.name, table.name, query, index, problems)
    if foreign is not None:
        # Обязательность берём от параметра, а не от чужой колонки: `NULL` там
        # говорит про хранение в той таблице, а не про этот вызов.
        return _column_type(foreign, table.name, query, problems), param.optional

    problems.append(
        Problem(
            table.name,
            query,
            f"параметр @{param.name} не нашёлся ни в одной таблице схемы и написан "
            "без приведения типа: поле объявлено string",
            fatal=False,
        )
    )
    return "string", param.optional


def _foreign_column(
    name: str,
    own_table: str,
    query: str,
    index: dict[str, list[tuple[str, Column]]],
    problems: list[Problem],
) -> Column | None:
    """Колонка того же имени в другой таблице схемы.

    Параметр часто приходит из подзапроса по соседней таблице
    (`... WHERE u.external_id = @external_id`): там имя колонки и есть имя
    параметра, и тип честнее взять оттуда, чем объявлять поле строкой.
    """
    found = [(owner, column) for owner, column in index.get(name, []) if owner != own_table]
    if not found:
        return None

    kinds = {_proto_type(column.sql_type) or "string" for _, column in found}
    if len(kinds) > 1:
        # Одно имя с разными типами в разных таблицах — угадать нельзя, но и
        # молчать нельзя: берём первую по порядку схемы и говорим об этом.
        where = ", ".join(f"{owner}.{column.name}" for owner, column in found)
        problems.append(
            Problem(
                own_table,
                query,
                f"параметр @{name} есть в разных таблицах с разными типами ({where}) — "
                f"тип взят из {found[0][0]}",
                fatal=False,
            )
        )
    return found[0][1]


def _column_index(tables: list[Table]) -> dict[str, list[tuple[str, Column]]]:
    """Колонки всей схемы по имени: `external_id` -> [(`dc.user`, Column)]."""
    index: dict[str, list[tuple[str, Column]]] = {}
    for table in tables:
        for column in table.columns:
            index.setdefault(column.name, []).append((table.name, column))
    return index


def _row(
    direction: str,
    entry: dict,
    table: Table,
    query: str,
    annotation: str,
    kind: str,
    problems: list[Problem],
) -> tuple[str | None, str | None, bool]:
    """Тип строки ответа: имя сообщения, своё сообщение строки и нужна ли таблица.

    `RETURNING *` и `SELECT *` возвращают таблицу целиком — для них годится
    сообщение таблицы. Выборка с отмеченными колонками возвращает меньше, и
    описывать её сообщением таблицы значило бы обещать поля, которых не будет.
    """
    if not _returns_row(direction, annotation):
        return None, None, False

    table_message = _camel(table.short_name)
    if direction != "READ":
        return table_message, None, True

    shown = [
        col[COLUMN_NAME_KEY]
        for col in entry.get(COLUMNS_KEY) or []
        if col.get(SHOW_KEY) and table.column(col[COLUMN_NAME_KEY]) is not None
    ]
    if not shown or len(shown) == len(table.columns):
        return table_message, None, True

    fields = [
        _column_field(table.column(name), table.name, query, problems) for name in shown
    ]
    comment = f"{kind} {query}: строка ответа — только отмеченные колонки."
    return f"{query}Row", _message(f"{query}Row", fields, comment), False


def _response(
    row_type: str | None, table: Table, annotation: str, paged: bool
) -> list[_Field]:
    """Поля ответа: строки и, если запрос постраничный, объект пагинации.

    У постраничного ответа строки лежат в `data`, а не в `rows` — так с ним
    рядом однозначно читается `pagination`, тоже объектом, а не парой отдельных
    счётчиков.
    """
    fields: list[_Field] = []

    if row_type is not None:
        if annotation == "many":
            fields.append(_Field(row_type, "data" if paged else "rows", repeated=True))
        else:
            fields.append(_Field(row_type, _snake(table.short_name)))

    if paged:
        fields.append(_Field(PAGINATION_MESSAGE, "pagination"))
    return fields


def _pagination_message() -> str:
    """Сообщение `Pagination` — одно на файл, используют все постраничные ответы."""
    fields = [_Field(proto, name) for proto, name in PAGINATION_FIELDS]
    return _message(
        PAGINATION_MESSAGE, fields, "Постраничность: одна на файл, поля одни и те же везде."
    )


def _kind(direction: str, entry: dict) -> str:
    """Чем запрос является, по-русски: «Выборка», «Мягкое удаление»."""
    if direction == "DELETE":
        return _DELETE_KINDS.get(entry.get(MODE_KEY) or "", _KINDS["DELETE"])
    return _KINDS[direction]


def _request_comment(kind: str, query: str, order: query_gen.Ordering) -> str:
    """Строка над `<Имя>Request`. Порядок называем: по полям его не видно.

    Обычные колонки сортировки параметрами не становятся — они зашиты в запрос,
    и без этой строки вызывающий не узнает, в каком порядке придут строки.
    """
    if order.default is None:
        return f"{kind} {query}: параметры вызова."

    keys = ", ".join(order.plain) or order.default
    return f"{kind} {query}: параметры вызова. Порядок по умолчанию — {keys}."


def _response_comment(kind: str, query: str, annotation: str, paged: bool) -> str:
    """Строка над `<Имя>Response` — что в ответе лежит на самом деле."""
    if paged:
        return f"{kind} {query}: страница данных и пагинация."
    if annotation == "many":
        return f"{kind} {query}: все найденные строки."
    if annotation == "one":
        return f"{kind} {query}: одна строка."
    return f"{kind} {query}: ответ пустой — запрос ничего не возвращает."


def _returns_row(direction: str, annotation: str) -> bool:
    """Вернёт ли запрос строки. У `exec` их нет, у `DELETE` — никогда."""
    if direction == "READ":
        return annotation in ("one", "many")
    if direction in ("CREATE", "UPDATE"):
        # `one` в этих направлениях означает `RETURNING *`.
        return annotation == "one"
    return False


# ---------------------------------------------------------------- части файла


def _section(table: Table, built: list[_Built], problems: list[Problem]) -> str:
    """Всё, что относится к одной таблице: шапка, сервис и сообщения.

    Сервис идёт первым: он — оглавление таблицы, по нему видно, какие запросы
    вообще есть. Сообщения ниже читают, когда уже знают, что ищут.
    """
    blocks = [f"{_TABLE_RULE}\n// {table.name}\n{_TABLE_RULE}"]

    service = [f"service {_camel(table.short_name)}Service {{"]
    service += [item.rpc for item in built]
    service.append("}")
    blocks.append("\n".join(service))

    if any(item.uses_row for item in built):
        fields = [
            _column_field(column, table.name, table.short_name, problems)
            for column in table.columns
        ]
        blocks.append(
            _message(
                _camel(table.short_name),
                fields,
                f"Строка таблицы {table.name}: все колонки, как их вернёт SELECT *.",
            )
        )

    for item in built:
        blocks += item.messages

    return "\n\n".join(blocks)


def _message(name: str, fields: list[_Field], comment: str) -> str:
    """Сообщение с полями по порядку. Номера — от единицы, без пропусков.

    Над каждым сообщением строка-комментарий: по имени `GetAliasesRow` не
    видно, чей он и что в нём, а контракт читают чаще, чем настройки.
    """
    if not fields:
        return f"// {comment}\nmessage {name} {{}}"

    lines = [f"// {comment}", f"message {name} {{"]
    for number, item in enumerate(fields, start=1):
        if item.comment:
            lines.append(f"  // {item.comment}")
        prefix = "repeated " if item.repeated else "optional " if item.optional else ""
        lines.append(f"  {prefix}{item.type} {item.name} = {number};")
    lines.append("}")
    return "\n".join(lines)


def _column_field(
    column: Column, table_name: str, query: str, problems: list[Problem]
) -> _Field:
    proto = _column_type(column, table_name, query, problems)
    # У сообщений (Timestamp) присутствие и так различимо — `optional` им незачем.
    return _Field(proto, column.name, optional=column.nullable and proto != TIMESTAMP)


def _column_type(
    column: Column, table_name: str, query: str, problems: list[Problem]
) -> str:
    proto = _proto_type(column.sql_type)
    if proto is None:
        problems.append(
            Problem(
                table_name,
                query,
                f"тип {column.sql_type} колонки {column.name} неизвестен — "
                "поле объявлено string",
                fatal=False,
            )
        )
        return "string"
    return proto


def _proto_type(sql_type: str) -> str | None:
    lowered = (sql_type or "").strip().lower()
    for prefix, proto in _TYPES:
        if lowered.startswith(prefix):
            return proto
    return None


def _camel(name: str) -> str:
    """`column_cat` -> `ColumnCat`."""
    return "".join(part[:1].upper() + part[1:] for part in _WORD.split(name) if part)


def _snake(name: str) -> str:
    """`ColumnCat` -> `column_cat`; имя колонки уже в нужном виде."""
    return "_".join(part.lower() for part in _WORD.split(name) if part)
