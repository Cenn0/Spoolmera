"""Self-hosted QR labels with an explicit, trusted public base URL."""
import html
import os
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


def label_html(spool: dict, size: str = '60x40') -> str:
    if size not in ('60x40','50x30'):
        raise ValueError('Unsupported label size.')
    extra_css = '<link rel="stylesheet" href="/static/label-50x30.css">' if size == '50x30' else ''
    physical_size = size.replace('x',' by ')
    uid = html.escape(spool["uid"], quote=True)
    name = html.escape(spool["name"], quote=True)
    brand = html.escape(spool["brand"], quote=True)
    material = html.escape(spool["material"], quote=True)
    color = html.escape(spool["color_name"], quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spool label · {uid}</title>
<link rel="stylesheet" href="/static/label.css">{extra_css}
</head>
<body>
<div class="print-toolbar"><strong>Spool label</strong>
  <span>Print using your browser (Ctrl/Cmd + P). Set scale to 100% and disable headers/footers.</span>
  <a href="/?spool={uid}">Back to inventory</a>
  <a href="/labels/{uid}?size=60x40">60 × 40 mm</a>
  <a href="/labels/{uid}?size=50x30">50 × 30 mm</a>
</div>
<main class="label" aria-label="{physical_size} millimeter spool label">
  <section class="label-info">
    <div class="label-brand">FILAMENT MANAGER</div>
    <div class="label-product">{brand}<br><strong>{name}</strong></div>
    <div class="label-material">{material} · {color}</div>
    <div class="label-weight">Remaining: {spool["remaining_g"]} g</div>
    <div class="label-id">SPOOL {spool["id"]:06d} · {uid[:8].upper()}</div>
  </section>
  <img src="/api/spools/{uid}/qr.svg" alt="QR code opening this spool in Filament Manager">
</main>
</body>
</html>"""
