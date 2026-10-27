"""Small public search resources. Private SPA routes never enter the sitemap."""
from html import escape
from urllib.parse import urlsplit

DESCRIPTION = "H-Point — помощь рядом: найдите помощника, создайте заявку и общайтесь в чате. Регистрация и вход по email."


def canonical_url(public_url):
    parsed=urlsplit(str(public_url).strip())
    if parsed.scheme not in {"http","https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Expected a public HTTP(S) origin")
    return parsed.scheme+"://"+parsed.netloc+"/"


def head_metadata(public_url):
    home=escape(canonical_url(public_url),quote=True)
    description=escape(DESCRIPTION,quote=True)
    return ('<link rel="canonical" href="'+home+'">'
            '<meta name="description" content="'+description+'">'
            '<meta property="og:type" content="website">'
            '<meta property="og:site_name" content="H-Point">'
            '<meta property="og:title" content="H-Point — помощь рядом">'
            '<meta property="og:description" content="'+description+'">'
            '<meta property="og:url" content="'+home+'">')


def robots_txt(public_url):
    return ("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /auth/\n"
            "Sitemap: "+canonical_url(public_url)+"sitemap.xml\n")


def sitemap_xml(public_url):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>'+escape(canonical_url(public_url))+'</loc></url></urlset>\n')


def removed_section_document(public_url):
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow">'
            '<link rel="icon" type="image/png" sizes="192x192" href="/assets/favicon-192.png">'
            '<title>H-Point — раздел закрыт</title></head>'
            '<body style="font-family:system-ui,sans-serif;max-width:560px;margin:15vh auto;padding:24px">'
            '<h1>Этот раздел закрыт</h1><p>Продолжите на главной странице H-Point.</p>'
            '<a href="'+escape(canonical_url(public_url),quote=True)+'">На главную</a></body></html>')
