# Production checklist

1. Set `BOT_TOKEN`.
2. Set `WEB_PUBLIC_URL` to the real HTTPS domain.
3. Configure `YOOKASSA_SHOP_ID` and `YOOKASSA_SECRET_KEY`.
4. In YooKassa set webhook to `https://YOUR-DOMAIN/api/payments/webhook` for successful payments.
5. Set `PAYMENT_RETURN_URL=https://YOUR-DOMAIN/payment/result`.
6. Put the site behind HTTPS/reverse proxy.
7. Back up `hpoint.db`.
8. For Telegram linking, the user gets a code in the site's Profile and sends `/link CODE` to the bot.
9. Do not publish exact home addresses in request text.

The build intentionally does not contain payment credentials or a bot token.
