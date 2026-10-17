# Production deployment

The production configuration uses PostgreSQL, Caddy with automatic TLS, and separate website and Telegram bot containers. They share the same database, but only the `bot` container polls Telegram.

## Before first launch

1. Copy `.env.example` to `.env`; keep `.env` only on the server and set its mode to `600`.
2. Set `APP_ENV=production`, `CADDY_DOMAIN`, `WEB_PUBLIC_URL=https://YOUR-DOMAIN`, `BOT_TOKEN`, and `BOT_USERNAME` without `@`.
3. Generate a long database password. Set `POSTGRES_PASSWORD` and set `DATABASE_URL=postgresql://hpoint:URL_ENCODED_PASSWORD@db:5432/hpoint`.
4. Set `SESSION_COOKIE_SECURE=1`. Production startup refuses insecure cookies, HTTP public URLs, SQLite, an untrusted proxy configuration, or a missing Telegram bot name.
5. Point the domain's A record to the VPS public IPv4 address. Open only TCP ports 80 and 443 in the VPS firewall; do not expose PostgreSQL or port 8080.
6. Start the stack with `docker compose up -d --build`, then check `docker compose ps` and `docker compose logs --tail=100 app bot caddy`.

## Telegram and payments

- In BotFather set the bot's name and username. The website sign-in flow opens `https://t.me/BOT_USERNAME?start=login_TOKEN`; no Telegram Login Widget domain configuration is required for this flow.
- The existing profile flow remains available: users can generate a code on the site and send `/link CODE` to the bot.
- In Robokassa configure ResultURL as `https://YOUR-DOMAIN/api/payments/robokassa/result`. Set merchant credentials only in `.env`; never place them in the repository.

## Start and stop Telegram independently

The website keeps working when the bot is stopped:

```sh
docker compose stop bot
docker compose start bot
docker compose logs -f bot
```

Run exactly one Telegram poller for one bot token. Do not also start `python run.py` or `python run_bot.py` on a computer while the production `bot` container is running with the same token.

## Backups and recovery

Create an encrypted or access-restricted backup location outside the checkout and run the backup script daily:

```sh
export BACKUP_DIR=/srv/hpoint-backups
sh scripts/backup-postgres.sh
```

Copy the resulting `.dump` and `.sha256` files to separate storage. Test restoration on a separate PostgreSQL instance before relying on a backup. To restore: `pg_restore --clean --if-exists --no-owner -d TARGET_DATABASE hpoint-TIMESTAMP.dump`.

## Operational checks

```sh
docker compose ps
curl -fsS https://YOUR-DOMAIN/api/health
docker compose exec db pg_isready -U hpoint -d hpoint
```

Do not put exact home addresses into public request text. The website map intentionally rounds coordinates and does not send request details in its discovery API.

The build intentionally does not contain payment credentials or a bot token.
