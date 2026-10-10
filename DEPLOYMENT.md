# Production checklist

1. Set `BOT_TOKEN`, `WEB_PUBLIC_URL=https://YOUR-DOMAIN`, and `SESSION_COOKIE_SECURE=1`.
2. Keep `WEB_HOST=127.0.0.1`; do not expose port `8080` publicly.
3. Put an HTTPS reverse proxy in front of the application. It must proxy to `http://127.0.0.1:8080` and pass `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers.
4. Restrict `/api/health` to the proxy or internal monitoring. It contains no integration details, but does confirm that the application responds.
5. Configure `ROBOKASSA_MERCHANT_LOGIN`, `ROBOKASSA_PASSWORD_1`, and `ROBOKASSA_PASSWORD_2`.
6. In Robokassa set ResultURL to `https://YOUR-DOMAIN/api/payments/robokassa/result` and use the configured hash algorithm.
7. Set `PAYMENT_SUCCESS_URL` and `PAYMENT_FAIL_URL` to the corresponding pages on your HTTPS domain.
8. Create backups using SQLite's online backup command, for example: `sqlite3 hpoint.db ".backup '/absolute/path/backups/hpoint-backup.db'"`. Do not copy only `hpoint.db` while the application runs: WAL data may be missing. Store the resulting backup outside the application host and regularly test restoration.
9. For Telegram linking, the user gets a code in the site's Profile and sends `/link CODE` to the bot.
10. Do not publish exact home addresses in request text.

The build intentionally does not contain payment credentials or a bot token.
