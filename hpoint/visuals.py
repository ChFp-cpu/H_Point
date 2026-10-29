"""Local, licensed illustrations. Never avatars, testimonials or portfolios."""
import json
import re
from html import escape
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parents[1] / "assets"
MANIFEST = json.loads((ASSET_ROOT / "photo-sources.json").read_text(encoding="utf-8"))
PHOTO_KEYS = {"trainer", "foreman", "tutor", "beauty", "repair", "events", "studio", "organization"}


def catalog():
    return {key: {field: row[field] for field in ("alt", "focal_point", "width", "height", "sources")}
            for key, row in MANIFEST["photos"].items()}


def assets():
    result = {}
    for row in MANIFEST["photos"].values():
        for source in row["sources"]:
            name = source["path"]
            if not re.fullmatch(r"photos/[a-z]+-(480|960|1600)\.webp", name):
                raise ValueError("Unexpected illustration path")
            path = ASSET_ROOT / name
            if not path.is_file():
                raise ValueError("Missing local illustration")
            result[path.name] = (path, "image/webp")
    return result


def kind_photo(kind):
    return kind if kind in PHOTO_KEYS else "specialist"


def photo(key, class_name="", eager=False, alt=None):
    row = MANIFEST["photos"].get(key, MANIFEST["photos"]["organization"])
    sources = row["sources"]
    srcset = ", ".join("/assets/" + Path(item["path"]).name + " " + str(item["width"]) + "w" for item in sources)
    return ('<figure class="hpPhoto ' + escape(class_name, quote=True) + '"><img class="hpPhotoImage" src="/assets/'
            + escape(Path(sources[0]["path"]).name, quote=True) + '" srcset="' + escape(srcset, quote=True)
            + '" sizes="(max-width:700px) calc(100vw - 36px), 50vw" width="960" height="640" alt="'
            + escape(alt or row["alt"], quote=True) + '" loading="' + ("eager" if eager else "lazy")
            + '" decoding="async"></figure>')
