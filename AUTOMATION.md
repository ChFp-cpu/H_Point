# Автоматизация H-Point

## Что происходит автоматически

- GitHub Actions запускает тесты, синтаксическую проверку, Compose validation и `pip-audit` для каждого PR и push в `main`.
- Push в `main` запускает deployment на VPS только после успешного CI.
- Deployment разворачивает точный commit SHA, пересобирает контейнеры и проверяет `/api/health`.
- GitHub проверяет production health endpoint каждые пять минут и при ошибке уведомляет Telegram.
- Dependabot раз в неделю создаёт PR для обновления Python-зависимостей и GitHub Actions.
- Скрипт backup делает PostgreSQL dump, SHA-256 файл и хранит последние 14 дней.

## Однократная настройка VPS

Выполните на VPS под пользователем с `sudo`:

```bash
sudo adduser --disabled-password --gecos '' hpoint-deploy
sudo usermod -aG docker hpoint-deploy
sudo mkdir -p /opt/hpoint /var/backups/hpoint
sudo chown -R hpoint-deploy:hpoint-deploy /opt/hpoint /var/backups/hpoint
```

Добавьте публичный SSH-ключ GitHub deploy key в `/home/hpoint-deploy/.ssh/authorized_keys` и дайте ему права `600`. Клонируйте репозиторий в `/opt/hpoint`, создайте production `.env` по `.env.example`, затем один раз выполните:

```bash
cd /opt/hpoint
docker compose up -d --build
```

Добавьте ежедневный backup в crontab пользователя `hpoint-deploy`:

```cron
15 3 * * * cd /opt/hpoint && BACKUP_DIR=/var/backups/hpoint BACKUP_RETENTION_DAYS=14 ./scripts/backup-postgres.sh >> /var/backups/hpoint/backup.log 2>&1
```

Скопируйте резервные копии во внешнее хранилище. VPS не должен быть единственным местом хранения базы.

## GitHub Secrets

В репозитории откройте **Settings → Secrets and variables → Actions** и создайте:

| Secret | Значение |
|---|---|
| `DEPLOY_HOST` | `45.91.250.221` |
| `DEPLOY_USER` | `hpoint-deploy` |
| `DEPLOY_PATH` | `/opt/hpoint` |
| `DEPLOY_SSH_PRIVATE_KEY` | закрытая часть deploy key |
| `DEPLOY_KNOWN_HOSTS` | результат `ssh-keyscan -H 45.91.250.221`, проверенный с VPS-консоли |
| `TELEGRAM_NOTIFY_BOT_TOKEN` | токен `@hppoint_bot` |
| `TELEGRAM_NOTIFY_CHAT_ID` | ваш числовой Telegram ID |

Создайте GitHub Environment `production` и добавьте этих же пользователей как required reviewers, если хотите подтверждать каждый production deploy вручную.

## Первая публикация

После настройки Secrets выполните merge в `main` или запустите workflow **Deploy H-Point** вручную в разделе Actions. Последующие push в `main` будут проходить полный CI и deploy автоматически.
