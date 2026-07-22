from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("ids", nargs="+")
    args = parser.parse_args()
    root = ET.parse(args.file).getroot()
    wanted = set(args.ids)
    found: set[str] = set()
    for element in root:
        record_id = element.attrib.get("id")
        if record_id in wanted:
            ET.indent(element, space="    ")
            print(ET.tostring(element, encoding="unicode"))
            found.add(record_id)
    missing = wanted - found
    if missing:
        print(f"MISSING: {', '.join(sorted(missing))}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
