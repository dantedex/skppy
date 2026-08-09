# SPDX-License-Identifier: MIT
"""Raw SU2017 options-manager writer fixtures."""

import pytest

from skppy import OptionsManager, OptionsProvider
from skppy.legacy_writter.envelope import _options_manager


def test_options_manager_matches_raw_sdk_carchive_payload() -> None:
    manager = OptionsManager(
        [
            OptionsProvider(
                "UnitsOptions",
                {
                    "LengthFormat": 2,
                    "SuppressUnitsDisplay": True,
                    "Precision": 0.125,
                    "UnitName": "inch",
                },
            ),
        ],
    )
    expected = bytes.fromhex(
        "0000000001000000fffeff0c55006e006900740073004f007000740069006f006e007300fffeff0c4c0065006e006700"
        "7400680046006f0072006d00610074000402000000fffeff145300750070007000720065007300730055006e0069007400"
        "730044006900730070006c00610079000701fffeff0950007200650063006900730069006f006e0006000000000000c03f"
        "fffeff0855006e00690074004e0061006d0065000afffeff0469006e0063006800fffeff00"
    )

    assert _options_manager(manager) == expected


def test_options_manager_rejects_unrepresentable_names_and_integers() -> None:
    with pytest.raises(ValueError, match="provider names"):
        _options_manager(OptionsManager([OptionsProvider("", {})]))
    with pytest.raises(ValueError, match="option names"):
        _options_manager(OptionsManager([OptionsProvider("Provider", {"": True})]))
    with pytest.raises(ValueError, match="fit in u32"):
        _options_manager(OptionsManager([OptionsProvider("Provider", {"Value": -1})]))
