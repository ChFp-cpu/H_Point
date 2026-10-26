# H-Point release: email access and test-money workflows

This release keeps the requester as the only person who can confirm completed help.

## Behaviour

- Registration and login use a verified email. Telegram sign-in endpoints and old sign-in links return410. The bot is an optional linked client for a verified email profile; linking keeps its existing user ID.
- The approved one-time cleanup removes explicitly linked Telegram users without verified email, cancels their active help with refunds and ends the old sessions of Telegram-linked profiles. Verified email profiles survive. Cleanup runs only after a fresh protected PostgreSQL backup with both application workers stopped.
- The public wallet and all new purchases use test money only. Historical real funds remain in the ledger, are hidden and cannot pay for new features. Card checkout is disabled.
- Paid help must reserve test funds within5minutes of creation. The reserve button is offered immediately. Production maintenance checks expiry every10seconds; reads and reserve attempts also check the deadline.
- Confirmed paid help pays85% to the helper and records15% as platform test income exactly once. Cancellation returns the whole reserve. Both participants can cancel current help, while completed help cannot be cancelled.
- Both participants are offered a review after completion. Historical rows whose helper was deleted do not show an impossible review.
- Free help between the same pair earns/charges HP once per rolling24hours in either direction; repeat help can finish and receive reviews without HP settlement.
- Helper mode explicitly enables readiness and shows tasks. Saved address/point replaces automatic GPS prompts. An unresolved point is explained and does not silently lock a helper out through a radius filter.
- Help cards and chat headings use the task title and requester name. Internal IDs remain in APIs/callbacks.
- Requests and chats accept up to3 JPEG/PNG/WebP photos, up to3MB each. The server decodes and re-encodes images, strips EXIF/GPS, bounds dimensions and checks access on every photo read.
- Published events expose participant names/profile IDs to signed-in users, without email/phone details.
- Commercial workspaces support coach, organisation, contractor and other profiles; services, clients, appointments, cancellations and metrics. Trial7days, then490test RUB per30days. Renewal is explicit and idempotent; expired workspaces remain readable.
- Health GET/HEAD actually query the database and return503 on failure.

## Validation

Automated Python suites cover auth, wallet sources/migrations, deadlines, commission, disputes, request lifecycle, ratings, photos/events, commercial workspaces and concurrency. PostgreSQL tests run in separate random schemas in an isolated temporary database. A production dump was restored into an isolated database to verify migration totals, source consistency, idempotency and the authorised Telegram cleanup.

Current browser suites (synthetic email profiles only):

```
HPOINT_QA_TEST_FUNDS=1 python tests/run_theme_qa.py tests/workflows_browser.cjs
python tests/run_theme_qa.py tests/media_browser.cjs
HPOINT_QA_TEST_FUNDS=1 python tests/run_theme_qa.py tests/commercial_browser.cjs
```

They cover the combined help/reserve/payout/review flow, email-only entry, no automatic GPS, mobile navigation, both themes and320/390/768/1440px widths, photo privacy and event participants, and commercial trial/renewal. Older browser scripts document the preceding Telegram-login interface and are superseded by these suites.

No real payment or real withdrawal is offered or performed. Test emails are intercepted in the local browser harness. Production email delivery configuration is checked without printing credentials.

## Release procedure

Commit and push the exact source, archive the commit, verify source checksums and back up code/images/database. Build before stopping the old workers. Stop app/bot, take a fresh final dump, initialise the new schema, run the approved cleanup once and start both workers. Verify health, disabled Telegram checkout/login, source features and zero bot restarts. Keep the protected backup for recovery; never restore a database over subsequent writes without assessing those writes.
