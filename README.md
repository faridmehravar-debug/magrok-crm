# МАГРОК CRM

Telegram CRM for private sales tracking. Requires `BOT_TOKEN` and `OWNER_ID` environment variables. Start: `python bot.py`.

For Railway production, attach a persistent volume mounted at `/data` and set `DB_PATH=/data/magrok.db` **before recording real client data**. Without persistent storage, SQLite records may be lost on redeploy.

The bot currently uses command-based entry for clients, products, orders and payments; menu buttons show lists and reports.
