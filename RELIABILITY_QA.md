# H-Point release: stable conversations and simpler navigation

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

Commit and push the exact source, archive the commit, verify source checksums and back up code/images/database. Build before stopping the old workers. Stop app/bot, take a fresh final dump, initialise the new schema, run the approved cleanup only for the original email migration, and start both workers. Routine releases must preserve accounts and sessions. Verify health, disabled Telegram checkout/login, source features and zero bot restarts. Keep the protected backup for recovery; never restore a database over subsequent writes without assessing those writes.


## Work page and chat follow-up

- Main navigation is Home, Help, Work (`#/work`, only when a company exists), Activities. Work has its own page with services, private clients, appointments and subscription. A private overview on Home shows metrics and upcoming appointments when a workspace exists.
- Chat keeps a stable, per-account/per-request textarea with autocomplete disabled. Text and photo sends clear only their original unchanged draft and cannot replace another opened conversation.
- Home places the current step and promotion in one column, recent tasks beside it, and League below. Mobile shows step, promotion, recent tasks, League.
- Raster favicon variants are publicly served from `/favicon.ico` and `/assets/favicon-{48,192}.png`. Activities use the labelled generated meeting illustration.
- Caddy allows the application's bounded photo/event JSON uploads while keeping the32KB cap for other routes. Reload/recreate Caddy after config changes.
- `scripts/set_test_balances.py --target 10000 --batch-key UNIQUE_KEY` appends test-only ledger corrections for all existing users in one transaction. The batch key is one-time: replays preserve later spending. It never changes reserves or historical real balances. The authorised2026-10-26 production batch used `hpoint-test-balance-10000-20261026`; do not use a new key to replay it.

Browser regressions: `chat_autofill_browser.cjs`, `home_order_browser.cjs`, `work_page_browser.cjs`; run using `tests/run_theme_qa.py`. PostgreSQL tests also cover exact balance adjustment, replay and concurrent reserve creation.

New registrations receive10000test RUB once (`REGISTRATION_BONUS_RUB=10000`). This is independent of the one-time existing-user balance correction and does not refill wallets on login.


## 27 October 2026 follow-up

- Helper readiness, selected categories, radius and availability save atomically; background refresh preserves unsaved controls. The settings open from “Настроить помощь”, without a separate navigation section. Pausing automatic offers keeps manually sent responses.
- A request accepts multiple responses. Each candidate has a private conversation with the requester before selection. Selecting one helper keeps the other conversations as history. Only the requester confirms completion; both selected participants can cancel. Applicants can withdraw their own response.
- The selected conversation appears above the chat list. Enter sends; Shift+Enter adds a line. Text and photo drafts belong to the account and actual conversation, including while another send is pending. Closed conversations are archived per participant and can be restored; a new incoming message reopens the recipient’s conversation.
- Visible chat polls every second with one in-flight request. Unchanged sync payloads do not rebuild the workspace; incremental message updates keep the composer, focus and scroll stable. The obsolete helper banner was removed.
- Users without a company create one in Profile; Work navigation is hidden until creation. Deletion requires confirmation and removes private workspace records while preserving payment/trial history, preventing repeated free trials. Home keeps the private work summary.
- Commercial access gates writes after expiry; history remains readable. PRO and request promotion change matching/listing priority, with explicit expiry checks. All payments and the 15% paid-help fee remain test funds.
- The linked bot has site, chats, help and cancel actions. Pending linking can be cancelled on the website or in the bot. Email remains the only registration and login method.
- Public metadata describes the current product. `/robots.txt`, `/sitemap.xml` and raster favicons are publicly crawlable. Removed `/games` responds410 and noindex for GET/HEAD; private routes are excluded from the sitemap. Search-engine results and favicon caches require recrawling.
- A calmer sage palette, shorter headings and fewer decorative elements preserve the existing functions. Manrope is served locally, the logos use compressed WebP, and maps load only when needed. Unavailable external maps do not delay initial rendering or login.

Validation includes full Python tests, isolated PostgreSQL concurrency tests and a production dump restored into a temporary database. Existing users, sessions, wallet ledger, requests, chats, messages, photos and commercial data retain exact fingerprints after migration; a second initialisation is idempotent. No account cleanup or balance reset belongs to this release.

Current browser suites use disposable local databases and synthetic email users:

```text
python tests/run_theme_qa.py tests/helper_stability_browser.cjs
python tests/run_theme_qa.py tests/marketplace_chat_browser.cjs
python tests/run_theme_qa.py tests/chat_archive_browser.cjs
python tests/run_theme_qa.py tests/startup_browser.cjs
python tests/run_theme_qa.py tests/theme_browser.cjs
python tests/run_theme_qa.py tests/home_order_browser.cjs
python tests/run_theme_qa.py tests/work_page_browser.cjs
HPOINT_QA_TEST_FUNDS=1 python tests/run_theme_qa.py tests/commercial_browser.cjs
```

Local release checks: 327 Python tests passed (40 PostgreSQL-only skips), plus 37 PostgreSQL tests and 6 commercial concurrency cases across SQLite/PostgreSQL. Browser checks include helper settings26, chat archive/account-switch29, startup23, homepage order31, work page40, commercial27, paid-help workflow29 and media23, with no JavaScript errors. The marketplace chat suite passed40 checks, including incoming delivery in642ms and an8.5-second idle DOM/focus check. The theme/authentication suite passed108 checks, including72 responsive screens, email verification, logout/login, password reset and removed-route deep links.


## Stable header and first paint

- The current workspace exclusively owns the header. H-Point+ and legacy purchase callbacks fetch billing data without invoking the previous balance/header renderers. Navigation and action nodes remain stable; the desktop balance reserves156px and uses tabular numbers.
- The HTML hides legacy hooks before first paint and shows a neutral loading state. Initialisation begins after the three current feature modules execute and waits briefly for the local font. A failed module shows a retry action. Current data no longer passes through hidden dashboard renderers, including on account changes.
- Light/dark surfaces, podium cards, crowns, avatars, map/status icons, tracking and work panels use theme variables. Secondary text has stronger contrast; headings and important names carry the visual emphasis.
- The public welcome and registration explain Help and Work in two short blocks. Search metadata reflects both. Page pinch zoom is disabled through the viewport, touch-action and gesture handlers; ordinary touch/wheel scrolling remains enabled.
- Message lists preserve their actual DOM and scroll position across full refreshes for the same account/conversation. Own text/photo sends follow the newest message; incoming messages preserve a position in history. Image loading respects that choice.

Validation:327 Python tests passed locally (40 PostgreSQL-only skips);664 live-theme/contrast checks;48 header/cold-reload checks including delayed assets;25 long-chat scroll checks;55 startup/welcome/gesture checks including native touch pinch and touch scroll;29 archive/account-switch checks;108 responsive/email-auth checks;29 paid-help workflow checks;40 marketplace chat checks. Browser suites reported no JavaScript errors.
