# SPDX-License-Identifier: MIT
"""Replace completed files without truncating an existing destination."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def atomic_write(path: Path, data: bytes) -> None:
    """Write beside the resolved destination, then atomically replace it.

    Existing symlinks keep pointing at their target, and existing permission
    bits are retained. A failed write or replacement removes the temporary file.
    """
    destination = path.resolve()
    temporary = NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False)
    temporary_path = Path(temporary.name)
    try:
        with temporary as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.exists():
            temporary_path.chmod(destination.stat().st_mode & 0o777)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
