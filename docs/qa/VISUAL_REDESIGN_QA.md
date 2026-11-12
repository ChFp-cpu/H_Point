# H-Point visual redesign

The existing application, routes and business rules are retained. The refreshed
interface covers Home, Help (requests, matching, chats, map and preferences),
Activities/services, the nine professional Work profiles, public organisations,
profile, wallet and H-Point+. Manrope and the native system theme remain in use.

## Main sources

- `assets/hpoint-visuals.js`: responsive illustrations, Home, Help headers and
  category navigation, request illustrations and Work entry.
- `assets/hpoint-editorial.css`: shared typography, spacing, cards, responsive
  composition, readable system themes, reduced motion and stable mobile wallet.
- `assets/hpoint-commercial.js`, `assets/hpoint-professional.js`: profession
  chooser, contextual overview, real upcoming work and existing tools.
- `assets/hpoint-organizations.js`: published services, truthful profession
  filters, photographed categories and real Home previews.
- `hpoint/visuals.py`, `hpoint/web.py`, `hpoint/organization_page.py`: local asset
  allowlist, actual route integration and public organisation layout.
- `hpoint/commercial_team.py`: adds the existing public organisation kind to the
  public service DTO; private CRM data and permissions are unchanged.

## Photography

16 distinct Pexels photographs, 34 local WebP sizes (480/960 px, with 1600 px for
two hero photos), 996,694 bytes combined. The subjects are community help, moving,
training, construction, teaching, beauty, electronics repair, events, a creative
studio, teamwork, independent work, digital help, pets, gardening and cooking.

Every author, source page, licence, download origin, dimension and SHA-256 is
recorded in `assets/photo-sources.json`; readable credits are in
`assets/photos/CREDITS.md`. Pexels licence: <https://www.pexels.com/license/>.
Images are thematic illustrations. They never stand in for real avatars,
customers, testimonials or portfolios. Service illustrations are labelled
“Фото направления”. Existing private task/chat images keep their server checks.

Below-the-fold images lazy-load; responsive srcset, sizes, intrinsic dimensions,
alt text and neutral error states are provided. Runtime image requests are local.

## Checks

Use the disposable local database; no production fixtures or messages:

```powershell
python -m unittest discover -s tests -v
python tests/run_theme_qa.py tests/editorial_browser.cjs
python tests/run_theme_qa.py tests/work_visual_browser.cjs
python tests/run_theme_qa.py tests/services_visual_browser.cjs
python tests/run_theme_qa.py tests/public_organization_visual_browser.cjs
python tests/run_theme_qa.py tests/professional_workspace_browser.cjs
python tests/run_theme_qa.py tests/theme_contrast_browser.cjs
python tests/run_theme_qa.py tests/header_stability_browser.cjs
python tests/run_theme_qa.py tests/chat_scroll_browser.cjs
```

The visual suites cover 320/375/768/1024/1440 px, live light/dark changes, long
titles, empty accounts, real publication/unpublication, category/search actions,
actual decoded local photographs, form drafts and responsive navigation.
Screenshots are written to `.theme-qa/` (not committed). Python tests additionally
cover photograph provenance/integrity, public-page escaping and existing paid-help
settlement: paid help does not award HP. No new financial behaviour is introduced.

### Local validation on 29 October 2026

- Python: 381 passed; 98 PostgreSQL-only cases skipped locally and covered by the
  PostgreSQL CI job. No local Python failures.
- Overall editorial UI: 1,164 checks passed across the welcome page, Home, Help,
  profile, wallet, subscriptions, Activities and League, including actual request
  creation steps, category filtering and sending a message in a seeded chat.
- Work visual layout: 39 checks; existing professional tools: 80 checks.
- Published services: 53 checks, including publication state, filters and search.
- Public organisations: 60 checks, including responsive themes, honest empty
  states, private-data exclusion and a deliberately failed photograph request.
- System-theme contrast: 664 checks; stable header: 48 checks.
- Chat scrolling, drafts and focus: 25 checks; initial loading and local-only
  startup assets: 57 checks.

These browser checks use temporary databases and synthetic local accounts. They
do not register users, send messages or create organisations on the live site.
Automated viewport checks are supplemented with desktop and mobile screenshots.
Physical iOS/Android devices have not been used for this release.

### Mobile welcome follow-up on 30 October 2026

The published-site check exposed an older mobile theme rule that hid the welcome
photograph even though the new photo markup was present. The editorial layer now
explicitly shows its own compact cover, removes obsolete overlays and minimum
height, and keeps sign-in and registration actions before the photograph.
The browser regression checks actual photo visibility and decoding at every
viewport/theme combination, rather than only checking that image markup exists.
The release asset query is advanced to `20261030-visual2` to refresh cached styles.
The updated editorial suite passed 1,226 checks; the eight photo/public-page
Python tests also passed. The old decorative grid and ring are removed from the
welcome hero so that the photograph and primary actions remain the focus.

### Mobile Home and profile follow-up on 30 October 2026

Home now follows the same document order on phones as on desktop. The previous
flex ordering moved new category/service sections above the main actions.
Both “Нужна помощь” and “Хочу помочь” are verified on the first mobile screen,
including real clicks, existing/empty accounts and the Work summary: 477 checks.

The profile header's grid items now fill their own cells. The inherited centred
alignment could place the profile label across the PRO cell on narrow screens.
The whole word “Профиль”, PRO, wallet fields and 44 px support/request actions are
checked at 320–900 px with normal and long balances: 1,107 checks, plus 48 existing
header stability checks. No JavaScript errors were reported.
The asset query is `20261030-mobile3`; the eight photo/public-page tests passed.
