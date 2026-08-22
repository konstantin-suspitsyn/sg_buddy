"""Генератор `query.sql` для sqlc по настройкам из `schema.json`.

Правила перевода настроек в SQL собраны здесь целиком, чтобы их можно было
прочитать в одном месте:

* запросы идут таблицами, каждая начинается с шапки — полное имя со схемой и в
  тех же кавычках, что в запросах, между двумя линейками; у таблицы, от которой
  ничего не собралось, шапки нет;
* выборка с постраничностью получает парный запрос `Count<имя> :one` — те же
  таблица и условия, а вместо колонок `total_items` и `total_pages`; если такое
  имя в файле уже занято, **файл не перезаписывается вовсе**: двойника sqlc не
  простит, а писать выборку без счётчика — молча менять смысл настроек;
* аннотация запроса берётся из настроек; `one` для вставки и изменения означает
  `RETURNING *`, потому что sqlc обязан вернуть строку;
* колонка пишется с именем таблицы — `"user".id`, `alias.name`. Не везде:
  `INSERT` перечисляет свои колонки, а `UPDATE ... SET` называет изменяемые, —
  там имя таблицы Postgres не примет, и они остаются как есть;
* пустое значение колонки — это параметр `@имя_колонки`, заполненное
  подставляется в SQL как есть (`now()`, `false`, подзапрос);
* **первичный ключ, получающий значение параметром, помечается
  предупреждением** — во вставке и в любом `UPDATE ... SET`, включая мягкое и
  обратное удаление: ключ обычно выдаёт база, а значение извне ломает нумерацию
  молча и рвёт ссылки соседних таблиц. Запрос всё равно пишется — схемы, где
  ключ присваивает приложение, обычны. Ключ в `WHERE` не в счёт: `UpdateById`
  только так и пишется;
* обязательный фильтр даёт `колонка = значение`, необязательный —
  `(значение IS NULL OR колонка = значение)` с приведением типа из DDL, чтобы
  sqlc понимал тип параметра;
* `EXACT WHERE` в READ — самостоятельное условие: если колонка не отмечена ни
  WHERE, ни WHERE OPTIONAL, но поле заполнено, оно всё равно даёт `колонка =
  значение` через `AND`. Если же WHERE или WHERE OPTIONAL отмечены, `EXACT
  WHERE` играет прежнюю роль — переопределяет значение внутри этого условия;
* `custom_where` приклеивается к остальным условиям через `AND`;
* сортировка: обычные колонки дают `ORDER BY кол1, кол2`, необязательные —
  булевы параметры `@order_by_<колонка>::boolean` в одном `CASE`, где вызывающий
  флагом включает нужную. `ELSE` — первая обычная колонка сортировки, а если таких нет,
  первая колонка DDL: без `ELSE` порядок пропал бы совсем. **У `many` порядок
  есть всегда**, даже когда не отмечено ничего, — иначе постраничная выборка
  начинает повторять и терять строки. Счётчику страниц сортировка не достаётся:
  считать она не помогает, а параметры бы добавила;
* join'ы берутся из раздела `JOINS`: выборка называет цепочки, они
  разворачиваются в строки `LEFT JOIN таблица алиас ON ...` по порядку звеньев,
  а условие `ON` идёт в файл ровно так, как написано руками. Колонка
  приджойненной таблицы выходит под именем с алиасом — `o.id AS o_id`: двух
  одинаковых имён в результате sqlc не примет. Это же имя носит её параметр
  (`@o_id`) и по нему же её выбирает сортировка. Столкнуться имена могут и
  после алиаса — своя колонка `alias_id` и `alias.id` приджойненной, — тогда
  второе получает номер (`alias_id_2`) и тоже уходит под ним через `AS`.
  Выборка с join'ом обязана перечислить колонки: `SELECT *` вернул бы столбцы
  всех таблиц вперемешку, поэтому запрос без единой отмеченной колонки
  пропускается;
* режим удаления решает, что за запрос получится: `DELETE` даёт `DELETE FROM`,
  `SOFT DELETE` и `UNDELETE` — одинаковый `UPDATE ... SET`. Обратное удаление
  отличается от мягкого только значениями, которые автор написал колонкам;
* **заполненный `custom_query` отменяет всё остальное**: колонки, фильтры и
  `custom_where` игнорируются, в файл идёт ровно то, что написано руками. Из
  настроек берутся только имя запроса и аннотация — всё прочее, включая
  `RETURNING` и `LIMIT`, автор пишет сам.

Файл перезаписывается целиком: он производный, править его руками бессмысленно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from .ddl import Column, Table
from .settings import (
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
    join_by_name,
)

QUERY_FILENAME = "query.sql"

HEADER = (
    "-- Файл сгенерирован программой SG Buddy https://github.com/konstantin-suspitsyn/sg_buddy",
    "-- Правки будут затёрты при следующей генерации: правьте настройки, а не этот файл.",
)

# Линейка шапки таблицы. Длина постоянная: имена таблиц разной длины, а рваные
# по ширине разделители читаются хуже ровных.
_TABLE_RULE = "-- " + "=" * 57

# Режимы удаления. Мягкое и обратное — оба `UPDATE ... SET`; отличаются только
# значениями, которые автор проставил колонкам, поэтому в генерации они равны.
SOFT_DELETE = "SOFT DELETE"
UNDELETE = "UNDELETE"
SET_MODES = (SOFT_DELETE, UNDELETE)

# Виды соединения. `INNER` первым: это же соединение по умолчанию у самого
# Postgres, когда слово перед JOIN не написано.
JOIN_TYPES = ("INNER", "LEFT", "RIGHT", "FULL")
# Соединения, которые оставляют пустой приджойненную сторону, и те, что оставляют
# пустой свою. `FULL` делает и то и другое.
_OUTER_JOINED = ("LEFT", "FULL")
_OUTER_OWN = ("RIGHT", "FULL")

# Аннотация по умолчанию, если её нет в настройках (у DELETE её нет вовсе).
DEFAULT_ANNOTATION = {"CREATE": "exec", "READ": "many", "UPDATE": "exec", "DELETE": "exec"}

# Сортировка среди отмеченных колонок: одна выбирается именем (`@order_by`), а
# не булевым флагом на каждую — иначе колонок-кандидатов больше, а выбрать
# всё равно можно только одну. Направление — отдельный параметр `order`:
# общий на весь ORDER BY, а не свой на колонку, — в выборке одно направление.
# Значение строкой (`ASC`/`DESC`), не `boolean`: по имени параметра и так не
# видно, что означает `true`, а по строке видно — тем более что это те же
# буквы, что в самом SQL.
# `order` — зарезервированное слово Postgres, поэтому `@order` sqlc не
# принимает («syntax error at or near "order"») — только `sqlc.arg('order')`,
# где имя внутри строки, а не токен SQL.
ORDER_TEXT_PARAM = "@order_by::text"
ORDER_DIRECTION_PARAM = "sqlc.arg('order')::text"
ASCENDING = "ASC"
DESCENDING = "DESC"

# Постраничность: имена параметров фиксированы, иначе их неоткуда взять.
# Тип пишем явно — sqlc не выводит его для параметров LIMIT/OFFSET сам.
# OFFSET считается из номера страницы, а не приходит отдельным параметром —
# вызывающему коду тогда незачем самому умножать `(page-1)*page_limit`.
LIMIT_PARAM = "@page_limit::int"
# В самом OFFSET — обязательно sqlc.arg(), не `@name`: sqlc 1.31 ломает вывод
# параметров, когда в одном арифметическом выражении встречаются два разных
# `@name` (пусть даже один из них — `@page_limit`, уже использованный в LIMIT
# этой же строки) — тогда компиляция падает на "column ... does not exist"
# или "edit stop location is out of bounds". `sqlc.arg('page_limit')` и
# `@page_limit` из LIMIT sqlc сводит к одному параметру сам, по имени.
OFFSET_EXPR = "(sqlc.arg('page')::int-1)*sqlc.arg('page_limit')::int"

# Шапка счётчика к постраничному запросу. Выравнивание по `AS` — часть текста,
# поэтому строки лежат как есть, а не собираются из кусков.
_COUNT_SELECT = (
    "SELECT",
    "    count(*)                                                        AS total_items,",
    "    ceil(count(*)::numeric / GREATEST(@page_limit::int, 1))::bigint AS total_pages",
)

# Идентификаторы, которые обязаны быть в кавычках. Список короткий намеренно:
# кавычить всё подряд — читать невозможно, угадывать — ошибка.
RESERVED = {
    "all", "analyse", "analyze", "and", "any", "array", "as", "asc", "authorization",
    "between", "both", "case", "cast", "check", "collate", "column", "constraint",
    "create", "cross", "current_date", "current_role", "current_time",
    "current_timestamp", "current_user", "default", "deferrable", "desc", "distinct",
    "do", "else", "end", "except", "false", "for", "foreign", "freeze", "from", "full",
    "grant", "group", "having", "ilike", "in", "initially", "inner", "intersect",
    "into", "is", "isnull", "join", "leading", "left", "like", "limit", "localtime",
    "localtimestamp", "natural", "not", "notnull", "null", "offset", "on", "only",
    "or", "order", "outer", "overlaps", "placing", "primary", "references", "returning",
    "right", "select", "session_user", "similar", "some", "table", "then", "to",
    "trailing", "true", "union", "unique", "user", "using", "verbose", "when", "where",
    "window", "with",
}

_SIMPLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class Problem:
    """Запрос, который сгенерировать не удалось или который стоит перечитать."""

    table: str
    query: str
    message: str
    fatal: bool = True
    # Проблема, из-за которой файл не пишется вовсе. Не то же самое, что `fatal`:
    # там пропускается один запрос, а остальные в файл идут.
    blocks_file: bool = False

    def __str__(self) -> str:
        return f"{self.table} · {self.query}: {self.message}"


@dataclass(frozen=True)
class Ordering:
    """Сортировка выборки: флаги, обычные ключи и колонка порядка по умолчанию.

    Считается один раз и здесь: и SQL, и контракт обязаны понимать одинаково,
    по чему выборка упорядочена, когда ни один флаг не выставлен.
    """

    optional: tuple[str, ...] = ()
    plain: tuple[str, ...] = ()
    # Ветка `ELSE`, она же порядок по умолчанию. `None` — сортировки нет вовсе.
    default: str | None = None


@dataclass(frozen=True)
class Join:
    """Звено цепочки: приджойненная таблица под своим алиасом и условие `ON`.

    Условие написано руками и в SQL идёт как есть: разбирать чужой текст,
    чтобы что-то в нём поправить, — гадание, а гадать здесь нельзя.
    """

    type: str
    table: Table
    alias: str
    on: str


@dataclass(frozen=True)
class Field:
    """Колонка выборки: чем она является в SQL и как называется на выходе.

    Своя колонка выходит под своим именем (`id`), колонка приджойненной
    таблицы — под именем с алиасом (`o_id`): в одной выборке встречаются
    `id` обеих таблиц, а двух одинаковых имён в результате sqlc не примет.
    Это же имя становится именем параметра — `@o_id`.
    """

    ref: str
    out: str
    column: Column
    # Настройки этой колонки: show/where/order_by и прочие флаги записи.
    flags: dict
    # Строка может не найтись: колонка приходит со стороны join'а, которую
    # внешнее соединение вправе оставить пустой. На SQL это не влияет, но
    # контракту знать обязательно.
    outer: bool = False


@dataclass(frozen=True)
class Param:
    """Параметр готового запроса: имя, приведение типа из SQL, обязательность."""

    name: str
    cast: str | None = None
    optional: bool = False


class GenerationError(Exception):
    """Сгенерировать нечего — например, в настройках нет ни одного запроса."""


def default_query_path(folder: str | Path) -> Path:
    """`query.sql` кладём в папку схемы, рядом со `schema.json`.

    Своего ключа с путём в настройках нет и не нужно: файл всегда лежит там же,
    где схема и её настройки.
    """
    return Path(folder) / QUERY_FILENAME


# Параметр в готовом SQL: `@имя`, `@имя::тип`, `sqlc.narg('имя')::тип` или
# `sqlc.arg('имя')::тип`. Последняя форма — там, где имя параметра совпадает
# с зарезервированным словом Postgres (`order`): `@order` там, где sqlc
# ожидает идентификатор, ловит `syntax error at or near "order"`, а
# `sqlc.arg('order')` — нет, потому что имя внутри кавычек, не токен SQL.
# У обеих функций sqlc принимает и имя без кавычек (`sqlc.arg(имя)`) — это
# встречается в Custom WHERE, написанном руками, и должно читаться так же,
# как форма с кавычками.
_PARAM = re.compile(
    r"@(?P<named>[a-z_][a-z0-9_]*)(?:::(?P<cast>[a-z][a-z0-9_ ]*))?"
    r"|sqlc\.narg\('(?P<narg>[^']+)'\)(?:::(?P<narg_cast>[a-z][a-z0-9_ ]*))?"
    r"|sqlc\.narg\((?P<narg_bare>[a-z_][a-z0-9_]*)\)(?:::(?P<narg_bare_cast>[a-z][a-z0-9_ ]*))?"
    r"|sqlc\.arg\('(?P<arg>[^']+)'\)(?:::(?P<arg_cast>[a-z][a-z0-9_ ]*))?"
    r"|sqlc\.arg\((?P<arg_bare>[a-z_][a-z0-9_]*)\)(?:::(?P<arg_bare_cast>[a-z][a-z0-9_ ]*))?"
)


def params(sql: str) -> list[Param]:
    """Параметры запроса в порядке появления, без повторов.

    Читаем готовый SQL, а не настройки: параметр приходит и из значения,
    написанного руками (`... WHERE u.external_id = @external_id`), и из
    `custom_query` — в настройках его тогда нет вовсе, а в вызове он есть.
    """
    def cast(group: str) -> str | None:
        # Тип может быть из двух слов (`double precision`), поэтому в шаблоне
        # разрешён пробел — и вместе с ним прилипает пробел перед `=`.
        written = (match.group(group) or "").strip()
        return written or None

    found: dict[str, Param] = {}
    for match in _PARAM.finditer(sql):
        if match.group("named"):
            param = Param(match.group("named"), cast("cast"))
        elif match.group("narg"):
            param = Param(match.group("narg"), cast("narg_cast"), optional=True)
        elif match.group("narg_bare"):
            param = Param(match.group("narg_bare"), cast("narg_bare_cast"), optional=True)
        elif match.group("arg"):
            param = Param(match.group("arg"), cast("arg_cast"))
        else:
            param = Param(match.group("arg_bare"), cast("arg_bare_cast"))
        # Первое вхождение задаёт тип: дальше тот же параметр повторяется без
        # приведения — `sqlc.narg('x')::bool IS NULL OR col = sqlc.narg('x')`.
        found.setdefault(param.name, param)
    return list(found.values())


def ident(name: str) -> str:
    """Имя в кавычках, только если без них нельзя: `dc.user` -> `dc."user"`."""
    parts = []
    for part in name.split("."):
        if _SIMPLE_NAME.match(part) and part not in RESERVED:
            parts.append(part)
        else:
            parts.append('"' + part.replace('"', '""') + '"')
    return ".".join(parts)


def is_alias(name: str) -> bool:
    """Годится ли строка в алиас приджойненной таблицы.

    Правило одно на программу: из алиаса собираются имена колонок выборки и
    параметров (`o_id`, `@o_id`), а они обязаны быть простыми идентификаторами —
    `@"my alias_id"` не бывает.
    """
    name = (name or "").strip()
    return bool(_SIMPLE_NAME.match(name)) and name not in RESERVED


def render(settings: dict, tables: list[Table]) -> tuple[str, list[Problem]]:
    """Собирает текст `query.sql`. Проблемные запросы пропускает, но называет."""
    by_name = {table.name: table for table in tables}
    problems: list[Problem] = []
    blocks: list[str] = []
    # Имена запросов sqlc глобальны по файлу, поэтому собираем их все сразу:
    # счётчику страниц нельзя совпасть ни с одним, даже из другой таблицы.
    taken = query_names(settings)

    for table_name, directions in (settings.get(CRUD_KEY) or {}).items():
        table = by_name.get(table_name)
        if table is None:
            problems.append(
                Problem(table_name, "—", "таблицы нет в схеме — все её запросы пропущены")
            )
            continue

        of_table: list[str] = []
        for direction in ("CREATE", "READ", "UPDATE", "DELETE"):
            for entry in directions.get(direction) or []:
                # Цепочки разбираем здесь, а не внутри сборки: их же читает
                # генератор контракта, и оба обязаны видеть одни и те же звенья.
                joins: list[Join] = []
                if direction == "READ":
                    resolved = read_joins(entry, table, settings, by_name, problems)
                    if resolved is None:
                        continue
                    joins = resolved

                block = entry_sql(direction, entry, table, taken, problems, joins=joins)
                if block:
                    of_table.append(block)

        # Шапку пишем, только если у таблицы что-то собралось: у таблицы без
        # запросов — и у той, где все запросы пропущены, — в файле висел бы
        # заголовок без единой строки под ним.
        if of_table:
            blocks.append(_table_header(table.name))
            blocks += of_table

    if not blocks:
        raise GenerationError("в настройках нет ни одного запроса")

    return "\n".join([*HEADER, "", *blocks]), problems


def generate(
    settings: dict, tables: list[Table], path: str | Path
) -> tuple[Path | None, list[Problem]]:
    """Пишет файл через временный: прерванная запись не должна его порвать.

    Возвращает `None` вместо пути, если писать нельзя: прежний файл в этом
    случае остаётся нетронутым, а причина лежит в списке проблем.
    """
    text, problems = render(settings, tables)

    if any(problem.blocks_file for problem in problems):
        return None, problems

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target, problems


# ---------------------------------------------------------------- один запрос


def query_names(settings: dict) -> set[str]:
    """Имена всех запросов файла — со всех таблиц и всех направлений."""
    return {
        (entry.get(NAME_KEY) or "").strip()
        for directions in (settings.get(CRUD_KEY) or {}).values()
        for entries in directions.values()
        for entry in entries or []
    }


def entry_sql(
    direction: str,
    entry: dict,
    table: Table,
    taken: set[str],
    problems: list[Problem],
    *,
    joins: list[Join] = (),
) -> str | None:
    name = (entry.get(NAME_KEY) or "").strip()
    if not name:
        problems.append(Problem(table.name, "—", f"{direction}: запрос без названия"))
        return None

    annotation = (entry.get(ANNOTATION_KEY) or DEFAULT_ANNOTATION[direction]).strip()

    # Запрос написан руками целиком — из настроек больше ничего не берём и ничего
    # не проверяем: колонки в нём могут вообще не участвовать.
    custom = (entry.get(CUSTOM_QUERY_KEY) or "").strip()
    if custom:
        return _custom_block(name, annotation, custom)

    unknown = [
        col.get(COLUMN_NAME_KEY)
        for col in entry.get(COLUMNS_KEY) or []
        if table.column(col.get(COLUMN_NAME_KEY)) is None
    ]
    if unknown:
        problems.append(
            Problem(table.name, name, "нет таких колонок в схеме: " + ", ".join(unknown))
        )
        return None

    # Занятые имена нужны только выборке — она одна порождает второй запрос.
    builders = {
        "CREATE": _create_sql,
        "READ": partial(_read_sql, taken=taken, joins=joins),
        "UPDATE": _update_sql,
        "DELETE": _delete_sql,
    }
    return builders[direction](entry, table, name, annotation, problems)


def _create_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []
    if not columns:
        problems.append(Problem(table.name, name, "INSERT без колонок"))
        return None

    keys = _key_params(entry, table, COLUMN_VALUE_KEY)
    if keys:
        problems.append(
            Problem(
                table.name,
                name,
                f"первичный ключ приходит параметром: {keys} — обычно ключ "
                "выдаёт база (bigserial, identity, nextval)",
                fatal=False,
            )
        )

    names = ",\n    ".join(ident(col[COLUMN_NAME_KEY]) for col in columns)
    values = ",\n    ".join(
        _value(col.get(COLUMN_VALUE_KEY), col[COLUMN_NAME_KEY]) for col in columns
    )

    body = [
        f"INSERT INTO {ident(table.name)} (",
        f"    {names}",
        ") VALUES (",
        f"    {values}",
        ")",
    ]
    # sqlc не примет `:one` у запроса, которому нечего вернуть.
    return _block(name, annotation, body, returning=annotation == "one")


def _key_params(
    entry: dict, table: Table, value_key: str, flag_key: str | None = None
) -> str:
    """Колонки первичного ключа, значение которым придёт параметром.

    Ключ в большинстве схем выдаёт сама база — `bigserial`, `identity`,
    `DEFAULT nextval(...)`, — и значение извне ломает нумерацию так, что падает
    не виноватый запрос, а следующий. Но запрещать нечего: схемы, где ключ
    присваивает приложение (uuid из кода, ключ из внешней системы), обычны, —
    поэтому здесь только список имён, а решают, что сказать, вызывающие.

    Ключ с написанным руками значением (`nextval(...)`, подзапрос) сюда не
    попадает: автор решил сам, извне оно не приходит. `flag_key` отбирает
    колонки, которым значение вообще присваивается: во вставке это все
    перечисленные, в изменении — только отмеченные `SET`.
    """
    keys = []
    for col in entry.get(COLUMNS_KEY) or []:
        if flag_key is not None and not col.get(flag_key):
            continue
        column = table.column(col.get(COLUMN_NAME_KEY))
        if column is None or not column.is_primary_key:
            continue
        if (col.get(value_key) or "").strip():
            continue
        keys.append(f"@{column.name}")

    return ", ".join(keys)


def _read_sql(
    entry: dict,
    table: Table,
    name: str,
    annotation: str,
    problems: list[Problem],
    *,
    taken: set[str],
    joins: list[Join] = (),
) -> str | None:
    fields = read_fields(entry, table, joins)
    shown = [item for item in fields if item.flags.get(SHOW_KEY)]

    if not shown and joins:
        # `SELECT *` вернул бы колонки всех соединённых таблиц вперемешку и с
        # повторяющимися именами — такой файл sqlc не примет. Угадывать, что из
        # них нужно, нечем: пропускаем запрос и называем причину.
        problems.append(
            Problem(
                table.name,
                name,
                "join есть, а колонки не отмечены: SELECT * дал бы "
                "повторяющиеся имена колонок",
            )
        )
        return None

    if not shown:
        problems.append(
            Problem(table.name, name, "не отмечена ни одна колонка — берём все", fatal=False)
        )

    if shown:
        body = [
            "SELECT",
            "    " + ",\n    ".join(_selected(item) for item in shown),
        ]
    else:
        body = ["SELECT *"]

    where = _where_lines(
        _conditions(fields, EXACT_WHERE_KEY) + _custom_conditions(entry)
    )
    body.append(f"FROM {ident(table.name)}")
    body += _join_lines(joins)
    body += where
    # Сортировка идёт после условий и до постраничности — иначе Postgres не
    # примет запрос, а страницы резались бы до упорядочивания.
    body += _order_block(
        fields,
        table,
        name,
        problems,
        always=annotation == "many",
        paged=bool(entry.get(PAGINATION_KEY)),
    )

    if annotation == "one":
        body.append("LIMIT 1")
        return _block(name, annotation, body)

    if not entry.get(PAGINATION_KEY):
        return _block(name, annotation, body)

    body.append(f"LIMIT {LIMIT_PARAM} OFFSET {OFFSET_EXPR}")
    listing = _block(name, annotation, body)

    # Постраничному запросу нужен парный счётчик: без него неоткуда взять число
    # страниц. Условия у него ровно те же — иначе он считал бы другую выборку.
    count_name = f"Count{name}"
    if count_name in taken:
        # Двойника писать нельзя: sqlc отвергнет файл целиком. Разойтись здесь
        # некуда — пока имя не освободят, файл вообще не перезаписываем, иначе
        # рабочий query.sql сменился бы неполным, без счётчика.
        problems.append(
            Problem(
                table.name,
                name,
                f"имя счётчика {count_name} занято другим запросом",
                blocks_file=True,
            )
        )
        return listing

    return listing + "\n" + _count_block(count_name, table, joins, where)


def _update_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []

    assignments = [
        f"{ident(col[COLUMN_NAME_KEY])} = "
        + _value(col.get(SET_VALUE_KEY), col[COLUMN_NAME_KEY])
        for col in columns
        if col.get(SET_KEY)
    ]
    if not assignments:
        problems.append(Problem(table.name, name, "UPDATE без единой изменяемой колонки"))
        return None

    # Ключ в `WHERE` — обычное дело, `UpdateById` только так и пишется. Речь
    # про `SET`: на первичный ключ ссылаются другие таблицы, и переписывать его
    # значением извне — не то, что обычно имеют в виду.
    keys = _key_params(entry, table, SET_VALUE_KEY, SET_KEY)
    if keys:
        problems.append(
            Problem(
                table.name,
                name,
                f"UPDATE переписывает первичный ключ: {keys} — ключ выдаёт база, "
                "и на него ссылаются другие таблицы",
                fatal=False,
            )
        )

    where = _where_block(entry, table, WHERE_VALUE_KEY)
    if not where:
        problems.append(
            Problem(table.name, name, "UPDATE без WHERE — изменит всю таблицу", fatal=False)
        )

    body = [f"UPDATE {ident(table.name)}", "SET " + ",\n    ".join(assignments)]
    body += where

    return _block(name, annotation, body, returning=annotation == "one")


def _delete_sql(
    entry: dict, table: Table, name: str, annotation: str, problems: list[Problem]
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []
    soft = entry.get(MODE_KEY) in SET_MODES

    where = _where_block(entry, table, WHERE_VALUE_KEY)
    if not where:
        problems.append(
            Problem(
                table.name,
                name,
                "удаление без WHERE — заденет всю таблицу",
                fatal=False,
            )
        )

    if soft:
        assignments = [
            f"{ident(col[COLUMN_NAME_KEY])} = "
            + _value(col.get(SET_VALUE_KEY), col[COLUMN_NAME_KEY])
            for col in columns
            if col.get(SET_KEY)
        ]
        if not assignments:
            problems.append(
                Problem(
                    table.name,
                    name,
                    f"{entry.get(MODE_KEY)} без единой проставляемой колонки",
                )
            )
            return None

        # Оба режима дают `UPDATE ... SET`, и ключ в нём так же не к месту, как
        # в обычном изменении: мягкое удаление помечает строку, а не заводит её
        # заново под другим номером.
        keys = _key_params(entry, table, SET_VALUE_KEY, SET_KEY)
        if keys:
            problems.append(
                Problem(
                    table.name,
                    name,
                    f"{entry.get(MODE_KEY)} переписывает первичный ключ: {keys} — "
                    "ключ выдаёт база, и на него ссылаются другие таблицы",
                    fatal=False,
                )
            )

        body = [f"UPDATE {ident(table.name)}", "SET " + ",\n    ".join(assignments)]
    else:
        body = [f"DELETE FROM {ident(table.name)}"]

    body += where
    return _block(name, annotation, body)


# ---------------------------------------------------------------- части запроса


def read_joins(
    entry: dict,
    table: Table,
    settings: dict,
    by_name: dict[str, Table],
    problems: list[Problem],
) -> list[Join] | None:
    """Звенья цепочек, включённых в выборку. `None` — собрать нельзя.

    Ничего не чинит на ходу: цепочка, у которой пропала таблица или разъехались
    алиасы, останавливает сборку этого запроса. Собрать его «как получится»
    значило бы отдать наружу выборку не того состава, каким она описана.
    """
    query = (entry.get(NAME_KEY) or "—").strip()
    links: list[Join] = []
    # Алиасы не должны сталкиваться ни между собой, ни с именем своей таблицы:
    # `FROM dc."user" ... JOIN dc.role "user"` Postgres не примет.
    aliases = {table.short_name}

    def failed(message: str) -> None:
        problems.append(Problem(table.name, query, message))

    for chain_name in entry.get(USED_JOINS_KEY) or []:
        chain = join_by_name(settings, table.name, chain_name)
        if chain is None:
            failed(f"join {chain_name!r} у таблицы не описан")
            return None

        for link in chain.get(LINKS_KEY) or []:
            joined = by_name.get(link.get(JOIN_TABLE_KEY) or "")
            if joined is None:
                failed(
                    f"join {chain_name!r}: таблицы "
                    f"{link.get(JOIN_TABLE_KEY)!r} нет в схеме"
                )
                return None

            kind = (link.get(JOIN_TYPE_KEY) or JOIN_TYPES[0]).strip().upper()
            if kind not in JOIN_TYPES:
                failed(f"join {chain_name!r}: неизвестный вид соединения {kind!r}")
                return None

            alias = (link.get(JOIN_ALIAS_KEY) or "").strip()
            if not is_alias(alias):
                failed(
                    f"join {chain_name!r}: алиас {alias!r} не годится — из него "
                    "собираются имена колонок и параметров"
                )
                return None
            if alias in aliases:
                failed(f"join {chain_name!r}: алиас {alias!r} уже занят")
                return None

            on = (link.get(JOIN_ON_KEY) or "").strip()
            if not on:
                failed(f"join {chain_name!r}: звено {alias!r} без условия ON")
                return None

            aliases.add(alias)
            links.append(Join(type=kind, table=joined, alias=alias, on=on))

    by_alias = {link.alias: link for link in links}
    for col in entry.get(JOINED_COLUMNS_KEY) or []:
        link = by_alias.get(col.get(JOIN_ALIAS_KEY) or "")
        if link is None or link.table.column(col.get(COLUMN_NAME_KEY)) is None:
            # Настройки колонок разошлись с цепочкой: у звена сменили алиас или
            # таблицу. Выкинуть колонку молча — отдать другую выборку под тем же
            # именем, поэтому пропускаем запрос целиком.
            failed(
                f"колонка {col.get(JOIN_ALIAS_KEY)}.{col.get(COLUMN_NAME_KEY)} "
                "не сходится с join'ами запроса"
            )
            return None

    return links


def read_fields(entry: dict, table: Table, joins: list[Join] = ()) -> list[Field]:
    """Колонки выборки: сперва свои, потом приджойненные — в порядке звеньев."""
    # `RIGHT` и `FULL` сохраняют приджойненную сторону, а свою вправе оставить
    # пустой: тогда пустыми приходят колонки собственной таблицы.
    own_outer = any(link.type in _OUTER_OWN for link in joins)
    # Имена на выходе не должны повторяться, поэтому собираем их по ходу: см.
    # `_unique_out`.
    taken: set[str] = set()

    fields: list[Field] = []
    for col in entry.get(COLUMNS_KEY) or []:
        column = table.column(col.get(COLUMN_NAME_KEY))
        if column is None:
            continue
        fields.append(
            Field(
                ref=field(table, column.name),
                out=_unique_out(column.name, taken),
                column=column,
                flags=col,
                outer=own_outer,
            )
        )

    written = {
        (col.get(JOIN_ALIAS_KEY) or "", col.get(COLUMN_NAME_KEY) or ""): col
        for col in entry.get(JOINED_COLUMNS_KEY) or []
    }
    for link in joins:
        for column in link.table.columns:
            flags = written.get((link.alias, column.name))
            if flags is None:
                continue
            fields.append(
                Field(
                    ref=f"{ident(link.alias)}.{ident(column.name)}",
                    out=_unique_out(f"{link.alias}_{column.name}", taken),
                    column=column,
                    flags=flags,
                    outer=link.type in _OUTER_JOINED,
                )
            )
    return fields


def _unique_out(name: str, taken: set[str]) -> str:
    """Имя на выходе, которого в этой выборке ещё не было.

    Двух одинаковых имён в `SELECT` sqlc не примет, а совпасть они могут и
    после алиаса: у `dc.column_cat` есть своя колонка `alias_id`, и звено с
    алиасом `alias` даёт `alias.id AS alias_id` — то же самое имя. Второму
    вхождению приписываем номер (`alias_id_2`), и в файл оно уходит под ним
    же через `AS`.

    Номер получает именно второе вхождение, а не оба: имя первого — то, что
    выборка возвращала до появления двойника, и менять его значило бы
    переименовать поле, которого спор не касается.
    """
    unique = name
    number = 2
    while unique in taken:
        unique = f"{name}_{number}"
        number += 1
    taken.add(unique)
    return unique


def _selected(item: Field) -> str:
    """Колонка в списке выборки. Имя на выходе задаём, только если оно другое."""
    if item.out == item.column.name:
        return item.ref
    return f"{item.ref} AS {ident(item.out)}"


def _join_lines(joins: list[Join]) -> list[str]:
    """Строки `LEFT JOIN таблица алиас ON ...` — по строке на звено."""
    lines = []
    for link in joins:
        # Условие могли скопировать из готового запроса — вместе с ведущим `ON`
        # и точкой с запятой; иначе в файл ушло бы `ON ON ...`.
        on = re.sub(r"(?i)^on\s+", "", link.on.rstrip(";").strip())
        lines.append(
            f"{link.type} JOIN {ident(link.table.name)} {ident(link.alias)} ON {on}"
        )
    return lines


def _value(written: str | None, column: str) -> str:
    """Заполненное значение идёт в SQL как есть, пустое — параметром."""
    written = (written or "").strip()
    return written or f"@{column}"


def field(table: Table, column: str) -> str:
    """Колонка с именем таблицы: `"user".id`, `alias.name`.

    Имя берём короткое, без схемы: в `FROM dc."user"` таблица видна именно как
    `"user"`. Схема в ссылке тоже допустима, но короче читается.

    Годится не везде: `INSERT` перечисляет свои колонки без имени таблицы, а
    `UPDATE ... SET` требует того же — там квалификация синтаксическая ошибка.
    """
    return f"{ident(table.short_name)}.{ident(column)}"


def ordering(fields: list[Field], table: Table, *, always: bool) -> Ordering:
    """Что и в каком порядке сортирует выборка. Правило одно на SQL и контракт.

    Названы колонки именами выхода (`o_id`, не `id`): по этим же именам
    вызывающий выбирает сортировку параметром `order_by`.
    """
    optional = tuple(
        item.out for item in fields if item.flags.get(ORDER_BY_OPTIONAL_KEY)
    )
    plain = tuple(item.out for item in fields if item.flags.get(ORDER_BY_KEY))

    if not optional and not plain:
        # У выборки списка порядок обязателен: без него постраничность начинает
        # повторять и терять строки. Берём первую колонку DDL.
        if not always:
            return Ordering()
        plain = (table.columns[0].name,)

    return Ordering(optional, plain, plain[0] if plain else table.columns[0].name)


def _order_block(
    fields: list[Field],
    table: Table,
    query: str,
    problems: list[Problem],
    *,
    always: bool,
    paged: bool = False,
) -> list[str]:
    """Строки `ORDER BY ...`.

    `ASC`/`DESC` — модификатор всего выражения `CASE`, а не значение внутри
    него: `CASE` не может вернуть их сам, и относятся они к ветке целиком,
    не к отдельному `WHEN`. Поэтому у каждой колонки, участвующей в
    сортировке, — своя пара `CASE`: один активен при `@order = 'ASC'`,
    другой при `@order = 'DESC'`, и ровно один из них в каждой строке
    не `NULL`. Колонки не делят пару между собой — иначе несколько `WHEN`
    пришлось бы сводить к одному `END ASC`/`END DESC` на всех, а направление
    относится именно к ветке одной колонки.

    Необязательные (выбираемые) колонки решают, сработает ли их пара, через
    `@order_by = 'имя_колонки'`. Обычные колонки сортировки участвуют всегда
    и в этом условии не нуждаются — они не выбираются, а всегда идут следом
    дополнительными ключами.

    У выборки списка (`always`) порядок есть всегда, даже когда не отмечено
    ничего: без `ORDER BY` Postgres волен вернуть строки в любом порядке, и
    постраничная выборка начинает то повторять строки, то терять их. Для
    постраничной выборки без единой отмеченной колонки сортировки это ещё и
    предупреждение: колонка для сортировки взята наугад, а не осознанно.
    """
    if (
        always
        and paged
        and not any(
            item.flags.get(ORDER_BY_KEY) or item.flags.get(ORDER_BY_OPTIONAL_KEY)
            for item in fields
        )
    ):
        problems.append(
            Problem(
                table.name,
                query,
                "постраничность без отмеченной колонки ORDER BY — сортировка "
                "взята по первой колонке DDL",
                fatal=False,
            )
        )

    order = ordering(fields, table, always=always)
    if order.default is None:
        return []

    # Колонка порядка по умолчанию берётся из DDL и своего поля выборки может не
    # иметь — тогда ссылку собираем сами, как для любой своей колонки.
    refs = {item.out: item.ref for item in fields}

    terms: list[str] = []
    for column in order.optional:
        ref = refs.get(column) or field(table, column)
        terms.append(_order_term(ref, column, selectable=True, reverse=False))
        terms.append(_order_term(ref, column, selectable=True, reverse=True))
    for column in order.plain:
        ref = refs.get(column) or field(table, column)
        terms.append(_order_term(ref, column, selectable=False, reverse=False))
        terms.append(_order_term(ref, column, selectable=False, reverse=True))

    lines = [f"{term}," for term in terms[:-1]] + [terms[-1]]
    return [f"ORDER BY {lines[0]}"] + [f"    {line}" for line in lines[1:]]


def _order_term(ref: str, column: str, *, selectable: bool, reverse: bool) -> str:
    """Одна ветка сортировки: своя колонка, своё направление, свой `CASE`.

    Ветка возрастания срабатывает не на точное `= 'ASC'`, а на
    `<> 'DESC'` — иначе пустая строка (zero value Go, когда вызывающий
    забыл проставить `order`) не подошла бы ни одной из двух веток: обе
    вернули бы `NULL` для каждой строки, и сортировка исчезла бы вовсе, а не
    просто взяла бы направление по умолчанию.
    """
    if reverse:
        cond = f"{ORDER_DIRECTION_PARAM} = '{DESCENDING}'"
    else:
        cond = f"{ORDER_DIRECTION_PARAM} <> '{DESCENDING}'"
    if selectable:
        cond = f"{cond} AND {ORDER_TEXT_PARAM} = '{column}'"
    direction = "DESC" if reverse else "ASC"
    return f"CASE WHEN {cond} THEN {ref} END {direction}"


def _where_block(entry: dict, table: Table, value_key: str) -> list[str]:
    """Строки условий запроса без join'ов — изменения и удаления."""
    return _where_lines(
        _conditions(read_fields(entry, table), value_key) + _custom_conditions(entry)
    )


def _conditions(fields: list[Field], value_key: str) -> list[str]:
    """Условия по колонкам. Имя параметра — имя колонки на выходе, не в таблице."""
    conditions: list[str] = []

    for item in fields:
        written = (item.flags.get(value_key) or "").strip()

        if item.flags.get(WHERE_KEY):
            conditions.append(f"{item.ref} = {written or f'@{item.out}'}")
        elif item.flags.get(WHERE_OPTIONAL_KEY):
            # Необязательный фильтр: параметр либо задан, либо условие не работает.
            # Приведение типа нужно, чтобы sqlc не гадал тип sqlc.narg.
            param = written or f"sqlc.narg('{item.out}')"
            conditions.append(
                f"({param}::{item.column.sql_type} IS NULL OR {item.ref} = {param})"
            )
        elif value_key == EXACT_WHERE_KEY and written:
            # EXACT WHERE — самостоятельное условие в READ: колонка не отмечена
            # ни WHERE, ни WHERE OPTIONAL, но значение всё равно должно попасть
            # в запрос через AND, а не молча потеряться.
            conditions.append(f"{item.ref} = {written}")

    return conditions


def _custom_conditions(entry: dict) -> list[str]:
    """Условие, написанное руками, — одним элементом или ни одного."""
    custom = (entry.get(CUSTOM_WHERE_KEY) or "").strip()
    if not custom:
        return []

    # Автор мог вписать условие, скопированное из готового запроса, — вместе с
    # ведущим WHERE и конечной точкой с запятой. Срезаем их, иначе внутри
    # скобок получится `(WHERE ...;)`.
    custom = custom.rstrip(";").strip()
    custom = re.sub(r"(?i)^where\s+", "", custom)
    # В скобках: своё условие может содержать OR и молча расширить выборку.
    return [f"({custom})"]


def _where_lines(conditions: list[str]) -> list[str]:
    """`WHERE ...` / `  AND ...` — или пустой список, если условий нет."""
    if not conditions:
        return []

    return [f"WHERE {conditions[0]}"] + [f"  AND {rest}" for rest in conditions[1:]]


def _count_block(
    name: str, table: Table, joins: list[Join], where: list[str]
) -> str:
    """`CountИмяЗапроса :one` — сколько всего строк и страниц у той же выборки.

    Размер страницы называется `@page_limit`, как в самой выборке: параметр по
    смыслу тот же, и вызывающему коду не приходится помнить второе имя.
    """
    body = [*_COUNT_SELECT, f"FROM {ident(table.name)}", *_join_lines(joins), *where]
    return _block(name, "one", body)


def _table_header(name: str) -> str:
    """Шапка таблицы: полное имя со схемой между двумя линейками.

    Имя экранируется так же, как в самих запросах, чтобы шапку можно было
    сверять с `FROM`/`INSERT INTO` глазами, не держа в уме разницу.
    """
    return "\n".join([_TABLE_RULE, f"-- {ident(name)}", _TABLE_RULE]) + "\n"


def _block(
    name: str, annotation: str, body: list[str], returning: bool = False
) -> str:
    """Заголовок sqlc, тело собранного запроса и `RETURNING`."""
    parts = [*body, "RETURNING *"] if returning else list(body)
    return "\n".join([f"-- name: {name} :{annotation}", *parts]) + ";\n"


def _custom_block(name: str, annotation: str, custom: str) -> str:
    """Запрос, написанный руками: только заголовок sqlc и его собственный текст."""
    # Точку с запятой добавляем, только если её не поставили сами.
    tail = "" if custom.rstrip().endswith(";") else ";"
    return f"-- name: {name} :{annotation}\n{custom}{tail}\n"
