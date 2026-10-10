#!/usr/bin/env python3
"""Validate local Markdown links and committed README screenshot assets.

No network calls or external Python dependencies. Runs against the Git checkout.
"""
from __future__ import annotations

from pathlib import Path
import re
import struct
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"""!?\[[^\]\n]*\]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)""")
IMG = re.compile(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)
CAPTURES = (
    "filaments-dark.png",
    "spools-dark.png",
    "spools-light.png",
    "locations-dark.png",
    "spools-mobile-dark.png",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def local_path(markdown: Path, address: str) -> Path | None:
    if address.startswith(("#", "//")):
        return None
    uri = urlsplit(address.strip("<>"))
    if uri.scheme or uri.netloc:
        return None
    if not uri.path:
        return None
    return (markdown.parent / unquote(uri.path)).resolve()


def main() -> int:
    errors: list[str] = []
    markdown_files = sorted(
        (*ROOT.glob("*.md"), *ROOT.joinpath("docs").rglob("*.md"))
    )
    for markdown in markdown_files:
        content = markdown.read_text(encoding="utf-8")
        addresses = [match.group(1) for match in LINK.finditer(content)]
        addresses += [match.group(1) for match in IMG.finditer(content)]
        for address in addresses:
            destination = local_path(markdown, address)
            if destination is None:
                continue
            if not destination.is_relative_to(ROOT):
                errors.append(f"{markdown.relative_to(ROOT)}: link escapes checkout: {address}")
            elif not destination.is_file():
                errors.append(f"{markdown.relative_to(ROOT)}: missing local link: {address}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in CAPTURES:
        relative = f"docs/screenshots/{name}"
        image = ROOT / relative
        if relative not in readme:
            errors.append(f"README.md: screenshot not embedded: {relative}")
        if not image.is_file():
            errors.append(f"Missing screenshot: {relative}")
            continue
        with image.open("rb") as source:
            header = source.read(24)
        if len(header) != 24 or not header.startswith(PNG_SIGNATURE):
            errors.append(f"Invalid PNG signature/header: {relative}")
            continue
        width, height = struct.unpack(">II", header[16:24])
        if not 0 < width <= 10000 or not 0 < height <= 10000:
            errors.append(f"Invalid PNG dimensions: {relative}")

    obsolete_repository = 'https://github.com/Cenn0/' + 'Filament' + 'Manager'
    for markdown in markdown_files:
        if obsolete_repository in markdown.read_text(encoding='utf-8'):
            errors.append(f'{markdown.relative_to(ROOT)}: outdated repository URL')

    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"Documentation validation failed: {len(errors)} issue(s).")
        return 1
    print(f"Documentation OK: {len(markdown_files)} Markdown files and "
          f"{len(CAPTURES)} real UI screenshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
