"""Public organisation page rendered solely from the publication allowlist."""
from html import escape
from .seo import canonical_url
from .theme import SYSTEM_THEME_CSS, SYSTEM_THEME_META
from . import visuals


ORG_CSS = r'''
html{touch-action:pan-x pan-y;scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:var(--hp-background);color:var(--hp-text-primary);font-family:Manrope,Arial,sans-serif}
.orgPage{max-width:1120px;margin:auto;padding:28px 28px 36px;min-width:0;box-sizing:border-box}
.orgPage *{box-sizing:border-box}.orgPage a:focus-visible{outline:2px solid var(--hp-focus);outline-offset:5px}
.orgHeader{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:46px}
.orgHeader img{display:block;width:145px;height:auto}.orgLink{color:var(--hp-accent-text);font-weight:750;font-size:13px;line-height:1.5;text-decoration:none;min-height:44px;display:inline-flex;align-items:center;gap:8px}
.orgLink:hover{text-decoration:underline;text-underline-offset:4px}.orgHero{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:48px;align-items:center;margin-bottom:48px}
.orgHeroCopy{min-width:0}.orgIdentity{display:flex;gap:12px;align-items:center;margin-bottom:22px}
.orgMark{flex:0 0 44px;width:44px;height:44px;display:grid;place-items:center;border-radius:14px;background:var(--hp-hover);color:var(--hp-accent-text);font-size:17px;font-weight:800;letter-spacing:-.04em}
.orgEyebrow{color:var(--hp-accent-text);font-size:11px;line-height:1.65;font-weight:750;letter-spacing:.065em;text-transform:uppercase}
.orgIdentity small{display:block;font-size:11px;color:var(--hp-text-secondary);line-height:1.5;margin-top:2px}
.orgHero h1{font-size:clamp(32px,4vw,54px);font-weight:800;line-height:1.12;letter-spacing:-.05em;margin:0 0 20px;overflow-wrap:anywhere}
.orgMultiline{white-space:pre-line;overflow-wrap:anywhere;line-height:1.75;color:var(--hp-text-secondary)}
.orgHeroCopy>.orgMultiline{font-size:15px;margin:0 0 22px;max-width:510px}.orgActions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-top:24px}
.orgAction{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:13px 20px;background:var(--hp-accent);color:var(--hp-accent-contrast);border-radius:13px;text-decoration:none;font-size:13px;line-height:1.5;font-weight:800;white-space:normal;text-align:center;transition:background .18s,transform .18s}
.orgAction:hover{filter:brightness(.97)}.orgActions>.orgLink{font-size:12px}.orgVisual{position:relative;min-width:0}
.orgHeroPhoto{height:380px;border-radius:68px 24px 24px 24px}.orgHeroPhoto img{height:100%;aspect-ratio:auto;object-fit:cover}
.orgPhotoNote{position:absolute;left:16px;bottom:16px;padding:7px 10px;border-radius:9px;font-size:10px;line-height:1.5;font-weight:700;background:var(--hp-surface);color:var(--hp-text-secondary)}
.orgSectionHead{display:flex;align-items:end;justify-content:space-between;gap:20px;margin:0 0 20px}.orgSectionHead h2,.orgContacts h2{font-size:29px;line-height:1.25;letter-spacing:-.035em;margin:0;font-weight:800}
.orgSectionHead p{margin:9px 0 0;font-size:13px;line-height:1.7;color:var(--hp-text-secondary)}.orgSectionHead .orgLink{flex-shrink:0}
.orgServices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.orgServices:has(>.orgService:only-child){grid-template-columns:1fr}
.orgService{background:var(--hp-surface);border:0;border-radius:20px;padding:26px;min-width:0;display:flex;flex-direction:column;box-shadow:var(--hp-shadow)}
.orgService .orgEyebrow{font-size:10px;letter-spacing:.03em;text-transform:none;margin-bottom:12px}
.orgService h3{font-size:21px;font-weight:800;line-height:1.35;letter-spacing:-.025em;margin:0 0 12px;overflow-wrap:anywhere}.orgService>.orgMultiline{font-size:13px;margin:0 0 24px}
.orgServiceMeta{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-top:auto;padding-top:20px;border-top:1px solid var(--hp-border)}
.orgServiceMeta b{font-size:20px;font-weight:800;letter-spacing:-.03em;overflow-wrap:anywhere}.orgServiceMeta span{font-size:11px;color:var(--hp-text-secondary)}
.orgService .orgLink{margin-top:13px;align-self:start;font-size:12px}.orgEmpty{grid-column:1/-1;padding:30px;border-radius:20px;background:var(--hp-surface);color:var(--hp-text-secondary);font-size:14px;line-height:1.7}
.orgContacts{scroll-margin-top:24px;margin-top:40px;display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1fr);gap:40px;padding:30px 32px;border-radius:24px;background:var(--hp-hover)}
.orgContactsIntro>p{font-size:13px;line-height:1.75;color:var(--hp-text-secondary);margin:12px 0 0;max-width:350px}.orgContactList{display:grid;gap:20px;min-width:0}
.orgContact b{font-size:12px;font-weight:800}.orgContact p{font-size:14px;margin:6px 0 0}.orgNote{color:var(--hp-text-secondary);font-size:11px;line-height:1.75;margin-top:26px;max-width:760px}
.orgFooter{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:28px 0 0;padding-top:20px;border-top:1px solid var(--hp-border)}
.orgCredits{color:var(--hp-text-secondary);font-size:10px;line-height:1.7}.orgCredits summary{cursor:pointer;padding:10px 0}.orgCredits a{color:var(--hp-accent-text);text-underline-offset:3px}.orgCredits p{max-width:420px;margin:5px 0}
@media(max-width:900px){.orgHero{gap:28px}.orgHeroPhoto{height:340px}.orgHero h1{font-size:38px}.orgContacts{gap:24px;padding:26px}}
@media(max-width:640px){.orgPage{padding:18px 18px 28px}.orgHeader{gap:12px;margin-bottom:28px}.orgHeader img{width:117px}.orgHeader>.orgLink{font-size:11px;min-width:0}.orgHero{grid-template-columns:1fr;gap:24px;margin-bottom:32px}.orgIdentity{margin-bottom:17px}.orgHero h1{font-size:34px}.orgHeroCopy>.orgMultiline{font-size:14px;margin-bottom:18px}.orgHeroPhoto{height:260px;border-radius:42px 20px 20px 20px}.orgActions{margin-top:18px}.orgSectionHead{align-items:start}.orgSectionHead h2,.orgContacts h2{font-size:26px}.orgSectionHead .orgLink{font-size:11px}.orgServices{grid-template-columns:1fr;gap:12px}.orgService{padding:22px}.orgService h3{font-size:20px}.orgContacts{grid-template-columns:1fr;gap:22px;margin-top:28px;padding:24px}.orgNote{margin-top:22px}.orgFooter{align-items:start;flex-direction:column;gap:2px}.orgEmpty{padding:24px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.orgAction{transition:none}}
'''


def document(profile, public_url):
    """Use published fields only; never serialize a private dashboard."""
    title = escape(str(profile["title"]))
    description = escape(str(profile.get("description", "")))
    kind_title = escape(str(profile.get("kind_title", "Специалист")))
    canonical = escape(canonical_url(public_url).rstrip("/") + profile["url"], quote=True)
    photo_key = visuals.kind_photo(profile.get("kind", "other"))
    illustration = visuals.MANIFEST["photos"][photo_key]
    initials = ''.join(word[0] for word in str(profile["title"]).split()[:2]) or 'H'
    contact_fields = (("contact", "Связаться"), ("address", "Где мы работаем"))
    details = ''.join('<div class="orgContact"><b>' + label + '</b><p class="orgMultiline">'
                      + escape(str(profile.get(field, ""))) + '</p></div>'
                      for field, label in contact_fields if profile.get(field))
    contact_button = '<a class="orgAction" href="#orgContacts">Связаться</a>' if profile.get("contact") else ''
    contact_heading = "Обсудим вашу задачу" if profile.get("contact") else "Где мы работаем"
    contact_intro = ("Уточните детали и договоритесь об удобном времени напрямую с организацией."
                     if profile.get("contact") else "Место работы, указанное организацией.")
    services = []
    for item in profile.get("services", []):
        price = f'{int(item["price_rub"]):,}'.replace(",", " ")
        services.append('<article class="orgService"><span class="orgEyebrow">' + kind_title + '</span><h3>'
            + escape(str(item["title"])) + '</h3>'
            + ('<p class="orgMultiline">' + escape(str(item.get("description", ""))) + '</p>' if item.get("description") else '')
            + '<div class="orgServiceMeta"><b>' + price + ' тест. ₽</b><span>'
            + str(int(item["duration_minutes"])) + ' мин.</span></div>'
            + ('<a class="orgLink" href="#orgContacts">Обсудить услугу <span aria-hidden="true">↗</span></a>' if profile.get("contact") else '') + '</article>')
    credits = ('<details class="orgCredits"><summary>Об иллюстрации</summary><p>Фото направления, не портфолио организации. '
               '<a href="' + escape(illustration["source_url"], quote=True) + '" target="_blank" rel="noopener noreferrer">'
               + escape(illustration["photographer"]) + '</a> · '
               '<a href="https://www.pexels.com/license/" target="_blank" rel="noopener noreferrer">Pexels License</a></p></details>')
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">'
        '<title>' + title + ' — H-Point</title><meta name="description" content="'
        + escape(str(profile.get("description", ""))[:200], quote=True) + '">'
        '<link rel="canonical" href="' + canonical + '"><meta property="og:type" content="website">'
        '<meta property="og:title" content="' + title + ' — H-Point"><meta property="og:url" content="' + canonical + '">'
        '<link rel="icon" type="image/png" sizes="192x192" href="/assets/favicon-192.png">'
        '<link rel="stylesheet" href="/assets/hpoint-editorial.css?v=20261030-mobile3">'
        + SYSTEM_THEME_META + '<style>' + SYSTEM_THEME_CSS + ORG_CSS + '</style></head><body><main class="orgPage">'
        '<header class="orgHeader"><a href="/" aria-label="На главную H-Point"><img src="/assets/hpoint-logo-dark.webp" alt="H-Point" width="145" height="48"></a>'
        '<a class="orgLink" href="/#/activities">Все услуги <span aria-hidden="true">↗</span></a></header>'
        '<section class="orgHero"><div class="orgHeroCopy"><div class="orgIdentity"><span class="orgMark" aria-hidden="true">'
        + escape(initials.upper()) + '</span><div><span class="orgEyebrow">' + kind_title
        + '</span><small>Для работы · H-Point</small></div></div><h1>' + title + '</h1>'
        + ('<p class="orgMultiline">' + description + '</p>' if description else '')
        + '<div class="orgActions">' + contact_button
        + '<a class="orgLink" href="#orgServices">Смотреть услуги <span aria-hidden="true">↓</span></a></div></div>'
        + '<div class="orgVisual">' + visuals.photo(photo_key, class_name="orgHeroPhoto", eager=True)
        + '<span class="orgPhotoNote">Фото направления</span></div></section>'
        + '<section aria-labelledby="orgServicesTitle" id="orgServices"><div class="orgSectionHead"><div><h2 id="orgServicesTitle">Услуги</h2>'
        '<p>Предложения и условия, опубликованные организацией.</p></div></div><div class="orgServices">'
        + (''.join(services) or '<div class="orgEmpty">Пока нет опубликованных услуг. Они появятся здесь, когда организация добавит предложения.</div>') + '</div></section>'
        + ('<section class="orgContacts" id="orgContacts" aria-labelledby="orgContactsTitle"><div class="orgContactsIntro"><h2 id="orgContactsTitle">' + contact_heading + '</h2>'
           '<p>' + contact_intro + '</p></div><div class="orgContactList">' + details + '</div></section>' if details else '')
        + '<p class="orgNote">Сейчас H-Point работает в тестовом режиме. Цены указаны в тестовых рублях; оплата через эту страницу не проводится.</p>'
        + '<footer class="orgFooter"><a class="orgLink" href="/#/profile">Открыть свой кабинет в H-Point <span aria-hidden="true">↗</span></a>'
        + credits + '</footer></main><script src="/assets/hpoint-public.js?v=20261030-mobile3"></script></body></html>')
