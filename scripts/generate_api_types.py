"""Deterministic typed Angular response models from Pydantic's authoritative schemas."""
import argparse
import json
import types
from pathlib import Path
from typing import Literal, Union, get_args, get_origin
from pydantic import BaseModel
from app.api.contracts import API_MODELS

OUTPUT = Path(__file__).resolve().parents[1] / "frontend/src/app/core/api/generated-contracts.ts"

def ts_type(annotation: object) -> str:
    if annotation is str:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType, Literal):
        args = get_args(annotation)
        if origin is Literal:
            return " | ".join(json.dumps(arg, ensure_ascii=False) for arg in args)
        return " | ".join(ts_type(arg) for arg in args)
    if origin is list:
        return ts_type(get_args(annotation)[0]) + "[]"
    if annotation is type(None):
        return "null"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "Api" + annotation.__name__.removesuffix("Response")
    raise TypeError(f"Unsupported API annotation: {annotation!r}")

def generate() -> str:
    parts = [
        "// Generated from Pydantic response models. Edit app/api/contracts.py instead.",
        "// Regenerate: python scripts/generate_api_types.py",
        "",
    ]
    for model in API_MODELS:
        parts.append(f"export interface Api{model.__name__.removesuffix('Response')} {{")
        for name, field in model.model_fields.items():
            optional = "" if field.is_required() else "?"
            parts.append(f"  {name}{optional}: {ts_type(field.annotation)};")
        parts.append("}")
        parts.append("")
    return "\n".join(parts)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = generate()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit("Angular contracts are outdated. Run python scripts/generate_api_types.py")
        print("Angular contracts match Pydantic models.")
    else:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(expected, encoding="utf-8")
        print(f"Generated {OUTPUT}")
