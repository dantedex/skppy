# SPDX-License-Identifier: MIT
import zipfile

import pytest

from skppy.data_structure.document import SkpDocument, SkpZipEntry
from skppy.data_structure.header import SkpHeader


def _header() -> SkpHeader:
    return SkpHeader(
        product_name="SketchUp",
        version_string="{26.1.103}",
        version_tuple=(26, 1, 103),
        vff_magic="VFF",
        vff_field_1=0,
        vff_field_2=0,
        vff_field_3=0,
        vff_field_4=0,
        zip_offset=0,
    )


def test_document_dump_zip_extracts_files_and_directories(tmp_path):
    archive = tmp_path / "model.skp"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("model.dat", b"model")
        zf.writestr("textures/", b"")
        zf.writestr("textures/brick.txt", b"brick")

    entries = [
        SkpZipEntry("model.dat", 5, 5, 0, False),
        SkpZipEntry("textures/", 0, 0, 0, True),
        SkpZipEntry("textures/brick.txt", 5, 5, 0, False),
    ]
    document = SkpDocument(
        filepath=str(archive),
        header=_header(),
        zip_entries=entries,
        model_entry=entries[0],
    )

    output = document.dump_zip(str(tmp_path / "out"))

    assert output == tmp_path / "out"
    assert (output / "model.dat").read_bytes() == b"model"
    assert (output / "textures").is_dir()
    assert (output / "textures" / "brick.txt").read_bytes() == b"brick"


def test_document_dump_zip_rejects_zip_slip_entries(tmp_path):
    archive = tmp_path / "model.skp"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", b"nope")

    document = SkpDocument(
        filepath=str(archive),
        header=_header(),
        zip_entries=[SkpZipEntry("../escape.txt", 4, 4, 0, False)],
        model_entry=None,
    )

    with pytest.raises(ValueError, match="outside output directory"):
        document.dump_zip(str(tmp_path / "out"))
