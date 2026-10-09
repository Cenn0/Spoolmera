"""Slice a tiny fixture through a fresh, disposable loopback API and isolated worker."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_http import DisposableClient


def run(base: str) -> None:
    client = DisposableClient(base)
    client.wait_ready()
    client.setup(os.environ["FILAMENT_BOOTSTRAP_TOKEN"])
    assert "ci" in client.call("/api/slicing/profiles")["profiles"]
    mesh = Path(__file__).resolve().parents[1] / "tests/fixtures/slicer/cube.stl"
    result = client.call("/api/slicing/slice?profile=ci", "POST", mesh.read_bytes(), timeout=90)
    assert isinstance(result, bytes) and 0 < len(result) <= 16 * 1024 * 1024
    text = result.decode("utf-8")
    assert any(line.startswith("G1 ") for line in text.splitlines()), "Slicer returned no toolpath"
    assert ";" in text and "E" in text, "Slicer output is not expected textual extrusion G-code"
    print("Slicer smoke passed: real STL -> isolated PrusaSlicer -> authenticated API G-code download.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    run(parser.parse_args().base)
