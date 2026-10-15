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
MAX_XML_ELEMENTS = 4096
MAX_XML_DEPTH = 32
MAX_XML_PLATES = 64
GRAMS = re.compile(rb"(?im)^[ \t]*;[ \t]*filament used \[g\][ \t]*[:=]([0-9., \t]+)$")
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
    # One traversal, with structural limits, rather than rescanning nested plates.
    # Nested plates are invalid: they would ambiguously reuse the same filaments.
    plates = []
    stack = [(root, 0, None)]
    elements = 0
    while stack:
        node, depth, active_plate = stack.pop()
        elements += 1
        if elements > MAX_XML_ELEMENTS or depth > MAX_XML_DEPTH:
            raise ValueError("3MF slice metadata exceeds structural limits.")
        if node.tag == "plate":
            if active_plate is not None:
                raise ValueError("Nested 3MF plates are not supported.")
            if len(plates) >= MAX_XML_PLATES:
                raise ValueError("3MF slice metadata contains too many plates.")
            active_plate = len(plates)
            plates.append({"plate": active_plate + 1, "materials": []})
        elif node.tag == "filament" and active_plate is not None:
            try:
                tool = int(node.get("id", "0")) - 1
            except ValueError as exc:
                raise ValueError("Invalid 3MF material identifier.") from exc
            value = node.get("used_g", "")
            if 0 <= tool < 16 and value:
                try:
                    amount = Decimal(value)
                except InvalidOperation as exc:
                    raise ValueError("Invalid 3MF material estimate.") from exc
                if amount != 0:
                    entries = plates[active_plate]["materials"]
                    if len(entries) >= MAX_TOOLS or any(item["tool"] == tool for item in entries):
                        raise ValueError("3MF plate tool mapping is ambiguous.")
                    entries.append({"tool": tool, "estimated_g": grams_int(value)})
        # The file is size-capped; limit tree depth and count before processing.
        for child in reversed(node):
            stack.append((child, depth + 1, active_plate))
    return [plate for plate in plates if plate["materials"]]
