#!/usr/bin/env python3
"""Select an exact GHCR image digest in an existing private Docker Compose .env.

This intentionally never fetches a mutable tag, starts containers, or selects
an image automatically. Obtain a promoted digest from the verified GitHub
Actions run, review it, and explicitly apply it.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile

IMAGE_NAME = "ghcr.io/cenn0/spoolmera"
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?SPOOLMERA_IMAGE\s*=")


def pin_env(contents: str, image: str) -> str:
    """Change only SPOOLMERA_IMAGE; refuse ambiguous duplicate assignments."""
    lines = contents.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if IMAGE_ASSIGNMENT.match(line)]
    if len(matches) > 1:
        raise ValueError("Multiple SPOOLMERA_IMAGE assignments; resolve manually")
    assignment = f"SPOOLMERA_IMAGE={image}\n"
    if matches:
        lines[matches[0]] = assignment
    else:
        if contents and not contents.endswith("\n"):
            lines.append("\n")
        lines.append(assignment)
    return "".join(lines)


def apply_env(env_file: Path, image: str) -> None:
    """Atomically replace an existing regular env file with mode 0600."""
    if env_file.is_symlink() or not env_file.is_file():
        raise ValueError("Refusing a missing, non-regular, or symlinked .env file")
    old = env_file.read_text(encoding="utf-8")
    new = pin_env(old, image)
    if new == old:
        return
    # Keep private credentials out of stdout, temporary names and Git commits.
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            prefix=".spoolmera-env-", dir=env_file.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            os.fchmod(temporary.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            temporary.write(new)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, env_file)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--digest", required=True,
        help="Promoted multi-platform digest (sha256 followed by 64 lowercase hex characters)"
    )
    parser.add_argument(
        "--env-file", type=Path, default=Path(".env"),
        help="Existing private Compose environment file (default: .env)"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write only SPOOLMERA_IMAGE to the existing .env (default: preview only)"
    )
    arguments = parser.parse_args(argv)
    if not DIGEST_PATTERN.fullmatch(arguments.digest):
        parser.error("Expected exactly sha256: followed by 64 lowercase hex characters")

    image = f"{IMAGE_NAME}@{arguments.digest}"
    if arguments.apply:
        try:
            apply_env(arguments.env_file, image)
        except (OSError, UnicodeError, ValueError) as error:
            parser.error(str(error))
        print(f"Selected {image} in {arguments.env_file}. No containers were restarted.")
    else:
        print(f"Preview only: SPOOLMERA_IMAGE={image}")
        print("Use --apply to update an existing private .env; then review backup and migration prerequisites.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
