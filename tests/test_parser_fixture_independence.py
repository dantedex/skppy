# SPDX-License-Identifier: MIT
"""Guard parser fixtures against sharing production wire constants."""

import re
from pathlib import Path


def test_modern_parser_fixtures_do_not_import_production_tag_enum() -> None:
    """Keep fixture bytes stable when the production tag table changes."""
    tests_dir = Path(__file__).parent
    production_enum_name = "Tlv" + "Tag"
    prohibited_import = re.compile(
        r"from\s+skppy\.parser\.tlv\s+import"
        rf"(?:[^\n]*\b{production_enum_name}\b|\s*\([^)]*\b{production_enum_name}\b)"
    )
    offenders = []
    for path in tests_dir.rglob("test_*.py"):
        if path == Path(__file__):
            continue
        if prohibited_import.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)

    assert offenders == []


def test_parser_fixtures_pack_integer_width_and_endianness_explicitly() -> None:
    """Reject ambiguous integer byte conversion in binary parser fixtures."""
    tests_dir = Path(__file__).parent
    ambiguous_conversion = ".to_" + "bytes("
    offenders = []
    for path in tests_dir.rglob("test_*.py"):
        if path == Path(__file__):
            continue
        if ambiguous_conversion in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(tests_dir)))

    assert offenders == []
