# МАГРОК CRM

Telegram CRM for private sales tracking. Requires `BOT_TOKEN` and `OWNER_ID` environment variables. Start: `python bot.py`.

For Railway production, attach a persistent volume mounted at `/data` and set `DB_PATH=/data/magrok.db` **before recording real client data**. Without persistent storage, SQLite records may be lost on redeploy.

The bot currently uses command-based entry for clients, products, orders and payments; menu buttons show lists and reports.

## Лиды (обновление)

В главном меню появилась кнопка «🎯 Лиды» и команда `/leads`.
Добавление: название → телефон (или `-`) → источник (кнопки) → интересующий товар.
В карточке лида доступны этап, редактирование, дата следующего контакта,
заметки, история и перевод в клиента. «Контакты на сегодня» показывает
запланированные и просроченные контакты. `/cancel` отменяет ввод.

Обновление не удаляет старые таблицы SQLite: при запуске создаются только
новые `leads` и `lead_events`. Не меняйте `DB_PATH` и не удаляйте Railway Volume.
Перед первым обновлением рекомендуется выгрузить CSV через `/export` и
сделать резервную копию файла SQLite из `/data`.

Внимание: импорт прайса в этом обновлении не включён: исходный прайс
не входил в ZIP репозитория.
