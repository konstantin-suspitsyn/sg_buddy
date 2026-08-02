# SG Buddy

![SG Buddy](sgbuddy/assets/hacker_dog.png)

Локальная GUI-программа: читает DDL-схему Postgres (`schema.sql`) и по настройкам
генерирует sqlc-запросы (`query.sql`) и protobuf-контракт (`*.proto`).

Готово: разбор DDL, интерфейс с формами Create / Read / Update / Delete по каждой
таблице и генератор `query.sql`. Генератор `.proto` ещё не написан.

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

## Тестовые данные

`test_data/tables_model/schema.sql` — схема, на которой проверяется программа.
