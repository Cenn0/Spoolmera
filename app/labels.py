"""Self-hosted QR labels with an explicit, trusted public base URL."""
import html
import os
import re
from urllib.parse import urlsplit

import qrcode
from qrcode.image.svg import SvgPathImage


def public_base_url() -> str:
    base = os.environ.get("FILAMENT_PUBLIC_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "FILAMENT_PUBLIC_BASE_URL must be an HTTP(S) origin without credentials, path, query or fragment."
        )
    return base


def spool_public_url(uid: str) -> str:
    return f"{public_base_url()}/s/{uid}"


def qr_svg(value: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
        image_factory=SvgPathImage,
    )
    qr.add_data(value)
    qr.make(fit=True)
    return qr.make_image().to_string(encoding="utf-8")


def label_language(query: str | None = None, cookie: str | None = None,
                   accept_language: str = "") -> str:
    """Use an explicit language, the UI preference, or supported browser preferences.

    Only the fixed en/de allowlist is ever reflected in markup or links. Browser
    language ranges honor quality weights and ignore excluded/invalid ranges.
    """
    for choice in (query, cookie):
        if choice in ("en", "de"):
            return choice
    ranges: list[tuple[float, int, str]] = []
    for index, item in enumerate(accept_language.split(",")):
        parts = [part.strip() for part in item.split(";")]
        tag = parts[0].lower()
        if not re.fullmatch(r"[a-z]{1,8}(?:-[a-z0-9]{1,8})*|\*", tag):
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.lower().startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
                break
        language = tag.split("-")[0]
        if 0 <= quality <= 1 and language in ("en", "de", "*"):
            ranges.append((-quality, index, language))
    preferences: list[tuple[float, int, int, str]] = []
    for default_order, language in enumerate(("en", "de")):
        explicit = [item for item in ranges if item[2] == language]
        available = explicit or [item for item in ranges if item[2] == "*"]
        if available:
            quality, index, _ = min(available)
            if quality < 0:
                preferences.append((quality, index, default_order, language))
    return min(preferences)[3] if preferences else "en"


LABEL_TEXT = {
    "en": {
        "aria": "{size} millimeter spool label",
        "remaining": "Remaining",
        "spool": "SPOOL",
        "qr": "QR code opening this spool in Filament Manager",
        "title": "Spool labels",
        "single": "spool label",
        "multiple": "spool labels",
        "print": "Print using your browser (Ctrl/Cmd + P). Set scale to 100% and disable headers/footers.",
        "back": "Back to inventory",
    },
    "de": {
        "aria": "Spulenetikett, {size} Millimeter",
        "remaining": "Restmenge",
        "spool": "SPULE",
        "qr": "QR-Code zum Öffnen dieser Spule in Filament Manager",
        "title": "Spulenetiketten",
        "single": "Spulenetikett",
        "multiple": "Spulenetiketten",
        "print": "Drucke mit deinem Browser (Strg/Cmd + P). Stelle die Skalierung auf 100 % und deaktiviere Kopf- und Fußzeilen.",
        "back": "Zurück zum Bestand",
    },
}


def _label_markup(spool: dict, size: str, language: str) -> str:
    uid = html.escape(spool["uid"], quote=True)
    name = html.escape(spool["name"], quote=True)
    brand = html.escape(spool["brand"], quote=True)
    material = html.escape(spool["material"], quote=True)
    color = html.escape(spool["color_name"], quote=True)
    text = LABEL_TEXT[language]
    physical_size = size.replace("x", " mal " if language == "de" else " by ")
    aria = text["aria"].format(size=physical_size)
    remaining = str(spool["remaining_g"]) if language == "en" else format(spool["remaining_g"], ",").replace(",", ".")
    return f"""<article class="label" aria-label="{aria}">
  <section class="label-info">
    <div class="label-brand">FILAMENT MANAGER</div>
    <div class="label-product">{brand}<br><strong>{name}</strong></div>
    <div class="label-material">{material} · {color}</div>
    <div class="label-weight">{text["remaining"]}: {remaining} g</div>
    <div class="label-id">{text["spool"]} {spool["id"]:06d} · {uid[:8].upper()}</div>
  </section>
  <img src="/api/spools/{uid}/qr.svg" alt="{text["qr"]}">
</article>"""


def labels_html(spools: list[dict], size: str = '60x40', language: str = 'en') -> str:
    if size not in ('60x40', '50x30'):
        raise ValueError('Unsupported label size.')
    if not 1 <= len(spools) <= 100:
        raise ValueError('Select between 1 and 100 spools.')
    if language not in LABEL_TEXT:
        raise ValueError('Unsupported label language.')
    text = LABEL_TEXT[language]
    extra_css = '<link rel="stylesheet" href="/static/label-50x30.css">' if size == '50x30' else ''
    uids = ','.join(html.escape(spool['uid'], quote=True) for spool in spools)
    markup = '\n'.join(_label_markup(spool, size, language) for spool in spools)
    label_count = text['single'] if len(spools) == 1 else text['multiple']
    return f"""<!doctype html>
<html lang="{language}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{text['title']} · {len(spools)}</title>
<link rel="stylesheet" href="/static/label.css">{extra_css}</head>
<body><div class="print-toolbar"><strong>{len(spools)} {label_count}</strong>
<span>{text['print']}</span>
<a href="/">{text['back']}</a>
<a href="/labels?uids={uids}&amp;size=60x40&amp;lang={language}">60 × 40 mm</a>
<a href="/labels?uids={uids}&amp;size=50x30&amp;lang={language}">50 × 30 mm</a>
</div><main>{markup}</main></body></html>"""


def label_html(spool: dict, size: str = '60x40', language: str = 'en') -> str:
    return labels_html([spool], size, language)
