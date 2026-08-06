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

from .ddl import Table
from .settings import (
    ANNOTATION_KEY,
    COLUMN_NAME_KEY,
    COLUMN_VALUE_KEY,
    COLUMNS_KEY,
    CRUD_KEY,
    CUSTOM_QUERY_KEY,
    CUSTOM_WHERE_KEY,
    EXACT_WHERE_KEY,
    MODE_KEY,
    NAME_KEY,
    ORDER_BY_KEY,
    ORDER_BY_OPTIONAL_KEY,
    PAGINATION_KEY,
    SET_KEY,
    SET_VALUE_KEY,
    SHOW_KEY,
    WHERE_KEY,
    WHERE_OPTIONAL_KEY,
    WHERE_VALUE_KEY,
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
                block = entry_sql(direction, entry, table, taken, problems)
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
    direction: str, entry: dict, table: Table, taken: set[str], problems: list[Problem]
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
        "READ": partial(_read_sql, taken=taken),
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


def _read_sql(
    entry: dict,
    table: Table,
    name: str,
    annotation: str,
    problems: list[Problem],
    *,
    taken: set[str],
) -> str | None:
    columns = entry.get(COLUMNS_KEY) or []

    shown = [col[COLUMN_NAME_KEY] for col in columns if col.get(SHOW_KEY)]
    if not shown:
        problems.append(
            Problem(table.name, name, "не отмечена ни одна колонка — берём все", fatal=False)
        )

    if shown:
        body = [
            "SELECT",
            "    " + ",\n    ".join(field(table, column) for column in shown),
        ]
    else:
        body = ["SELECT *"]

    where = _where_block(entry, table, EXACT_WHERE_KEY)
    body.append(f"FROM {ident(table.name)}")
    body += where
    # Сортировка идёт после условий и до постраничности — иначе Postgres не
    # примет запрос, а страницы резались бы до упорядочивания.
    body += _order_block(entry, table, name, problems, always=annotation == "many")

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

    return listing + "\n" + _count_block(count_name, table, where)


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
        body = [f"UPDATE {ident(table.name)}", "SET " + ",\n    ".join(assignments)]
    else:
        body = [f"DELETE FROM {ident(table.name)}"]

    body += where
    return _block(name, annotation, body)


# ---------------------------------------------------------------- части запроса


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


def ordering(entry: dict, table: Table, *, always: bool) -> Ordering:
    """Что и в каком порядке сортирует выборка. Правило одно на SQL и контракт."""
    columns = entry.get(COLUMNS_KEY) or []
    optional = tuple(
        col[COLUMN_NAME_KEY] for col in columns if col.get(ORDER_BY_OPTIONAL_KEY)
    )
    plain = tuple(col[COLUMN_NAME_KEY] for col in columns if col.get(ORDER_BY_KEY))

    if not optional and not plain:
        # У выборки списка порядок обязателен: без него постраничность начинает
        # повторять и терять строки. Берём первую колонку DDL.
        if not always:
            return Ordering()
        plain = (table.columns[0].name,)

    return Ordering(optional, plain, plain[0] if plain else table.columns[0].name)


def _order_block(
    entry: dict, table: Table, query: str, problems: list[Problem], *, always: bool
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
    columns = entry.get(COLUMNS_KEY) or []
    if (
        always
        and entry.get(PAGINATION_KEY)
        and not any(col.get(ORDER_BY_KEY) or col.get(ORDER_BY_OPTIONAL_KEY) for col in columns)
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

    order = ordering(entry, table, always=always)
    if order.default is None:
        return []

    terms: list[str] = []
    for column in order.optional:
        terms.append(_order_term(table, column, selectable=True, reverse=False))
        terms.append(_order_term(table, column, selectable=True, reverse=True))
    for column in order.plain:
        terms.append(_order_term(table, column, selectable=False, reverse=False))
        terms.append(_order_term(table, column, selectable=False, reverse=True))

    lines = [f"{term}," for term in terms[:-1]] + [terms[-1]]
    return [f"ORDER BY {lines[0]}"] + [f"    {line}" for line in lines[1:]]


def _order_term(table: Table, column: str, *, selectable: bool, reverse: bool) -> str:
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
    return f"CASE WHEN {cond} THEN {field(table, column)} END {direction}"


def _where_block(entry: dict, table: Table, value_key: str) -> list[str]:
    """Строки `WHERE ...` / `  AND ...` — или пустой список, если условий нет."""
    conditions: list[str] = []

    for col in entry.get(COLUMNS_KEY) or []:
        name = col[COLUMN_NAME_KEY]
        written = (col.get(value_key) or "").strip()

        if col.get(WHERE_KEY):
            conditions.append(f"{field(table, name)} = {written or f'@{name}'}")
        elif col.get(WHERE_OPTIONAL_KEY):
            # Необязательный фильтр: параметр либо задан, либо условие не работает.
            # Приведение типа нужно, чтобы sqlc не гадал тип sqlc.narg.
            param = written or f"sqlc.narg('{name}')"
            column = table.column(name)
            cast = f"::{column.sql_type}" if column is not None else ""
            conditions.append(
                f"({param}{cast} IS NULL OR {field(table, name)} = {param})"
            )
        elif value_key == EXACT_WHERE_KEY and written:
            # EXACT WHERE — самостоятельное условие в READ: колонка не отмечена
            # ни WHERE, ни WHERE OPTIONAL, но значение всё равно должно попасть
            # в запрос через AND, а не молча потеряться.
            conditions.append(f"{field(table, name)} = {written}")

    custom = (entry.get(CUSTOM_WHERE_KEY) or "").strip()
    if custom:
        # Автор мог вписать условие, скопированное из готового запроса, —
        # вместе с ведущим WHERE и конечной точкой с запятой. Срезаем их,
        # иначе внутри скобок получится `(WHERE ...;)`.
        custom = custom.rstrip(";").strip()
        custom = re.sub(r"(?i)^where\s+", "", custom)
        # В скобках: своё условие может содержать OR и молча расширить выборку.
        conditions.append(f"({custom})")

    if not conditions:
        return []

    return [f"WHERE {conditions[0]}"] + [f"  AND {rest}" for rest in conditions[1:]]


def _count_block(name: str, table: Table, where: list[str]) -> str:
    """`CountИмяЗапроса :one` — сколько всего строк и страниц у той же выборки.

    Размер страницы называется `@page_limit`, как в самой выборке: параметр по
    смыслу тот же, и вызывающему коду не приходится помнить второе имя.
    """
    body = [*_COUNT_SELECT, f"FROM {ident(table.name)}", *where]
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
