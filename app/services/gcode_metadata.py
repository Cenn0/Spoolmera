"""Bounded metadata inspection; never execute sliced files or infer a physical spool.

The result is an estimate only. A caller must explicitly map each used tool to a spool.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MAX_FILE = 16 * 1024 * 1024
MAX_TOOLS = 8
GRAMS = re.compile(rb"(?im)^[ \t]*;[ \t]*filament used \[g\][ \t]*[:=][ \t]*([0-9., \t]+)[ \t]*$")
SINGLE = re.compile(rb"(?im)^[ \t]*;[ \t]*(?:filament_weight_g|estimated_filament_weight_g)[ \t]*[:=][ \t]*([0-9.]+)[ \t]*$")


def grams_int(value: str) -> int:
    try:
        d = Decimal(value.strip())
        if not d.is_finite() or not 0 < d <= 100000:
            raise ValueError("Filament estimate must be positive and bounded.")
        rounded = int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if rounded < 1:
            raise ValueError("At least one estimated gram required.")
        return rounded
    except (InvalidOperation, ValueError, ArithmeticError):
        raise ValueError("Invalid filament weight.") from None


def gcode_tool_estimates(data: bytes) -> list[dict]:
    if not data or len(data) > MAX_FILE:
        raise ValueError("G-code must be nonempty and at most 16 MiB.")
    sample = data[:131072] + b"\n" + data[-131072:]
    matches = GRAMS.findall(sample)
    if not matches:
        singles = SINGLE.findall(sample)
        if len(set(singles)) != 1 or not singles:
            return []
        return [{"tool": 0, "estimated_g": grams_int(singles[0].decode("ascii"))}]
    variants: set[tuple[str, ...]] = set()
    for match in matches:
        try:
            values = tuple(s.strip() for s in match.decode("ascii").split(","))
        except UnicodeDecodeError:
            return []
        variants.add(values)
    if len(variants) != 1:
        return []  # conflicting slicer metadata must not be applied
    weights = next(iter(variants))
    if len(weights) > MAX_TOOLS:
        raise ValueError("More tools than the supported maximum.")
    output = []
    for idx, value in enumerate(weights):
        if not value:
            raise ValueError("Empty material weight.")
        try:
            decimal = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid per-tool material estimate.") from exc
        if decimal == 0:
            continue
        amount = grams_int(value)
        if amount > 0:
            output.append({"tool": idx, "estimated_g": amount})
    return output


def three_mf_plate_estimates(data: bytes) -> list[dict]:
    if not data or len(data) > MAX_FILE:
        raise ValueError("3MF must be nonempty and at most 16 MiB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > 250:
                raise ValueError("3MF contains too many entries.")
            candidate = archive.getinfo("Metadata/slice_info.config")
            if candidate.file_size > 262144:
                raise ValueError("3MF slice metadata exceeds the size limit.")
            xml = archive.read(candidate)
    except (zipfile.BadZipFile, KeyError, RuntimeError) as exc:
        raise ValueError("3MF does not contain supported sliced metadata.") from exc
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("External XML declarations are not supported.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("Invalid 3MF slice metadata.") from exc
    plates = []
    for number, plate in enumerate(root.iter("plate"), start=1):
        entries = []
        for filament in plate.iter("filament"):
            tool = int(filament.get("id", "0")) - 1
            value = filament.get("used_g", "")
            if not 0 <= tool < 16 or not value:
                continue
            try:
                amount = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("Invalid 3MF material estimate.") from exc
            if amount == 0:
                continue
            entries.append({"tool": tool, "estimated_g": grams_int(value)})
        if entries:
            if len(entries) > MAX_TOOLS or len({x["tool"] for x in entries}) != len(entries):
                raise ValueError("3MF plate tool mapping is ambiguous.")
            plates.append({"plate": number, "materials": entries})
    return plates
