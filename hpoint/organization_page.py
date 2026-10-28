"""Public organisation page rendered solely from the publication allowlist."""
from html import escape
from .seo import canonical_url
from .theme import SYSTEM_THEME_CSS, SYSTEM_THEME_META


def document(profile, public_url):
    """Never accept a private dashboard as this function's input."""
    title = escape(str(profile["title"]))
    description = escape(str(profile.get("description", "")))
    canonical = escape(canonical_url(public_url).rstrip("/") + profile["url"], quote=True)
    services = []
    for item in profile.get("services", []):
        price = f'{int(item["price_rub"]):,}'.replace(",", " ")
        services.append('<article class="orgService"><h3>' + escape(str(item["title"])) + '</h3>'
            '<p class="orgMultiline">' + escape(str(item.get("description", ""))) + '</p>'
            '<div class="orgServiceMeta"><b>' + price + ' тест. ₽</b><span>'
            + str(int(item["duration_minutes"])) + ' мин.</span></div></article>')
    details = ''.join('<div class="orgContact"><b>' + label + '</b><p class="orgMultiline">'
                     + escape(str(profile.get(field, ""))) + '</p></div>'
                     for field, label in (("contact", "Связаться"), ("address", "Где мы работаем"))
                     if profile.get(field))
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">'
        '<title>' + title + ' — H-Point</title><meta name="description" content="'
        + escape(str(profile.get("description", ""))[:200], quote=True) + '">'
        '<link rel="canonical" href="' + canonical + '"><meta property="og:type" content="website">'
        '<meta property="og:title" content="' + title + ' — H-Point"><meta property="og:url" content="' + canonical + '">'
        '<link rel="icon" type="image/png" sizes="192x192" href="/assets/favicon-192.png">'
        + SYSTEM_THEME_META + '<style>' + SYSTEM_THEME_CSS + r'''
        html{touch-action:pan-x pan-y}body{margin:0;background:var(--hp-background);color:var(--hp-text-primary);font-family:Manrope,Arial,sans-serif}
        .orgPage{max-width:1000px;margin:auto;padding:24px;min-width:0}.orgHeader{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:36px}
        .orgHeader img{width:160px;height:auto}.orgLink{color:var(--hp-accent-text);font-weight:700;text-decoration:none}.orgHero,.orgService,.orgContacts{background:var(--hp-surface);border:1px solid var(--hp-border);border-radius:22px;padding:28px}
        .orgEyebrow{color:var(--hp-accent-text);font-size:12px;font-weight:750;letter-spacing:.08em}.orgHero h1{font-size:clamp(30px,5vw,50px);line-height:1.15;letter-spacing:-.04em;margin:12px 0 20px;overflow-wrap:anywhere}
        .orgMultiline{white-space:pre-line;overflow-wrap:anywhere;line-height:1.65;color:var(--hp-text-secondary)}.orgPage h2{font-size:24px;margin:30px 0 16px}.orgPage h3{font-size:19px;margin:0 0 10px;overflow-wrap:anywhere}
        .orgServices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.orgServiceMeta{display:flex;flex-wrap:wrap;gap:16px;border-top:1px solid var(--hp-border);padding-top:16px;margin-top:18px}.orgServiceMeta span,.orgNote{color:var(--hp-text-secondary)}
        .orgContacts{margin-top:24px;display:grid;gap:18px}.orgContact p{margin:6px 0 0}.orgNote{font-size:12px;line-height:1.6;margin-top:24px}.orgFooter{margin:30px 0 12px;font-size:13px}
        @media(max-width:600px){.orgPage{padding:18px}.orgHeader{margin-bottom:24px}.orgHeader img{width:130px}.orgHeader a{font-size:12px}.orgHero,.orgService,.orgContacts{padding:20px}.orgServices{grid-template-columns:1fr}}
        </style></head><body><main class="orgPage"><header class="orgHeader"><a href="/"><img src="/assets/hpoint-logo-dark.webp" alt="H-Point" width="160" height="53"></a><a class="orgLink" href="/#/activities">Активности и услуги →</a></header>
        <section class="orgHero"><span class="orgEyebrow">''' + escape(str(profile.get("kind_title", "Организация")))
        + '</span><h1>' + title + '</h1><p class="orgMultiline">' + description + '</p></section>'
        + '<h2>Наши услуги</h2><section class="orgServices">' + (''.join(services) or '<p>Услуги скоро появятся.</p>') + '</section>'
        + ('<section class="orgContacts">' + details + '</section>' if details else '')
        + '<p class="orgNote">Сейчас H-Point работает в тестовом режиме. Цены указаны в тестовых рублях; оплата через эту страницу не проводится.</p>'
        + '<footer class="orgFooter"><a class="orgLink" href="/#/profile">Создать свой кабинет в H-Point →</a></footer></main>'
        '<script src="/assets/hpoint-public.js?v=20261028-work1"></script></body></html>')
