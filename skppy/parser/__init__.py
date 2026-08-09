# SPDX-License-Identifier: MIT
"""
Binary SKP parsers.

This package contains all code responsible for decoding the TLV/binary
content of ``model.dat`` into the data-structure objects defined in
:mod:`skppy.data_structure`.

Public API
----------
parse_model
    Full model.dat -> :class:`~skppy.data_structure.model.Model` pipeline.
parse_entities
    Decode an 0x1388 entities payload into an
    :class:`~skppy.data_structure.entities.Entities` object.
parse_definitions
    Decode the 0x01F9 definitions block into a list of
    :class:`~skppy.data_structure.entities.ComponentDefinition` objects.
parse_materials
    Decode the 0x01F7 materials block (including ZIP-resident material.xml
    files) into a list of :class:`~skppy.data_structure.materials.Material`
    objects.
"""

from .model_parser import parse_model
from .entities import parse_entities
from .definitions import parse_definitions
from .material_parser import parse_materials

__all__ = [
    "parse_definitions",
    "parse_entities",
    "parse_materials",
    "parse_model",
]
