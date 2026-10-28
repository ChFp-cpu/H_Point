# Organisation workspace

Existing personal workspaces keep their owner IDs, clients, services, bookings,
trial dates and renewals. Regular additive migrations create team membership,
invitations, objects, tasks, estimates, shifts and explicit public profiles.
An account can own a workspace and join other organisations. The selected
organisation is checked on every read and mutation, including linked records
and assigned employees. Email account IDs can be negative.

| Action | Owner | Administrator | Employee |
| --- | --- | --- | --- |
| View organisation records | Yes | Yes | Yes |
| Manage objects, tasks, bookings and shifts | Yes | Yes | Yes |
| Manage clients, services, estimates and publication | Yes | Yes | No |
| Invite or remove employees | Yes | Yes | No |
| Appoint administrators or manage administrators | Yes | No | No |
| Renew subscription or delete organisation | Yes | No | No |
| Leave organisation | Delete organisation instead | Yes | Yes |

Invitations are tied to the recipient's verified email and expire after seven
days. Accepting an invitation does not send an email, spend money or start
another trial. Leaving or removal revokes access; expired subscriptions retain
read access and allow leaving. A new organisation never gains another trial by
deleting and recreating its original profile.

Bookings assigned to the same employee cannot overlap. Employee shifts cannot
overlap one another; bookings may take place inside a shift. Cancelled bookings
do not block a slot. Objects track dates, client, employee and planned/actual
cost. Tasks track object, employee, due date and status.

Estimates accept 1–100 lines. Unit prices and costs round to cents before
multiplication; quantities and markup use decimal arithmetic. Each line rounds
to cents, then markup applies to the subtotal. The displayed live calculation
matches the saved calculation. CSV and print exports contain the saved lines
and totals. Estimates and performance figures are accounting records only:
they never debit client wallets or imply received payments. All amounts remain
test rubles. Completed bookings use a 30-day period; task totals and approved
estimate totals are explicitly labelled as all-time figures.

Publication is opt-in separately for the organisation page and each service.
Only published, active services of an active organisation appear in Activities.
Public `/organizations/<slug>` and `/api/organizations/<slug>` responses use a
field allowlist. Client records, internal notes, estimates, objects, invitations
and employees' emails never enter these responses. Removing publication,
deleting the organisation or expiry closes public access.

## H-Point+

PRO remains available. The header and profile display PRO only while its
entitlement is active. H-Point+ displays expiry, days remaining, effects and
purchased periods immediately after purchase. Active subscriptions renew only
through an explicit confirmation with the current term token. Replaying a
purchase key cannot charge again or switch products; a stale browser tab cannot
silently add another term. PRO adds 8 to helper priority and 10 to request
priority in automatic matching. It does not change ratings or guarantee replies.
Historical More Responses purchases retain their request priority of 50; new
request promotion uses 100. These entitlements and their history are preserved.

## Verification

Use isolated synthetic accounts, never production records:

```powershell
python -m unittest discover -s tests -v
python tests/run_theme_qa.py tests/organization_workspace_browser.cjs
$env:HPOINT_QA_TEST_FUNDS='1'
python tests/run_theme_qa.py tests/subscriptions_browser.cjs
```

The PostgreSQL CI job also runs `test_commercial_team.py` and
`test_commercial_concurrency.py`. HTTP tests cover anonymous publication,
escaped organisation content, membership denial, subscription status and
invalid purchase metadata. The original work-page, header, chat-scroll, startup
and theme suites cover regressions in forms, focus, accounts and responsive UI.
