# SG Buddy

![Release](https://img.shields.io/github/actions/workflow/status/konstantin-suspitsyn/sg_buddy/release.yml?label=release)
![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/konstantin-suspitsyn/sg_buddy/main/.github/badges/coverage.json)
![Release version](https://img.shields.io/github/v/release/konstantin-suspitsyn/sg_buddy)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)

![SG Buddy](sgbuddy/assets/hacker_dog.png)

Локальная GUI-программа: читает DDL-схему Postgres (`schema.sql`) и по настройкам
генерирует sqlc-запросы (`query.sql`) и protobuf-контракт (`*.proto`).

Готово: разбор DDL, интерфейс с формами Create / Read / Update / Delete и Join
по каждой таблице, генераторы `query.sql` и `*.proto`.

Что появилось в каждой версии — в [CHANGELOG.md](CHANGELOG.md).

## Запуск

```bash
uv run sgbuddy
```

Откроется браузер на `http://127.0.0.1:8080`. Отдельным окном (без вкладки
в браузере):

```bash
uv run sgbuddy --native
```

Работает одинаково на Windows, Linux и macOS — единственное требование
Python 3.11+ и `uv`.

## Как это работает

1. Указать папку со схемой (`schema.sql`), путь будущего `.proto` и его
   `package` с `option go_package`. Выбранное запоминается в `schema.json`
   рядом со схемой и предлагается при следующем запуске.
2. Слева появится список таблиц. У каждой пять действий: **Create**, **Read**,
   **Update**, **Delete** — запросы, и **Join** — связи с другими таблицами.
   Добавленную запись можно отредактировать, скопировать или удалить.
3. Кнопки «Сгенерировать query.sql» и «Сгенерировать .proto» пишут оба файла из
   настроек, которые сейчас в программе, — сохранять их отдельно не нужно.
   Запрос, который собрать нельзя, пропускается с объяснением под сводкой, а не
   роняет генерацию целиком.

### Join

Цепочка описывает связь таблицы, а не отдельный запрос: её включают в себя
несколько выборок. Вид соединения (`INNER`, `LEFT`, `RIGHT`, `FULL`) и таблица
выбираются списком, условие `ON` пишется руками. Звеньев в цепочке столько,
сколько таблиц присоединяется по порядку, — связь «многие ко многим» это два
звена: связующая таблица и целевая.

Включённая в выборку цепочка добавляет колонки приджойненных таблиц: их можно
показывать, фильтровать по ним и сортировать наравне со своими. В результат они
выходят под именем с алиасом (`t.name AS t_name`) — двух одинаковых имён в одной
выборке sqlc не примет.

## Тестовые данные

`test_data/tables_model/schema.sql` — схема, на которой проверяется программа.

## Тесты

```bash
uv run pytest
```

Прогоняются и в CI — на Linux и Windows.
