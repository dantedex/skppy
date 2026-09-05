# SPDX-License-Identifier: MIT
"""Clean up data-blocks created by a failed synchronous Blender build."""

from collections.abc import Iterator
from contextlib import contextmanager

import bpy


@contextmanager
def import_transaction() -> Iterator[None]:
    """Remove only newly created IDs when a main-thread build fails.

    Objects and collections are removed before the data-blocks they reference.
    Import builders must never mutate pre-existing data inside this scope.
    """
    kinds = ("objects", "collections", "meshes", "curves", "cameras", "materials", "images")
    previous = {kind: set(getattr(bpy.data, kind)) for kind in kinds}
    try:
        yield
    except Exception:
        for kind in kinds:
            collection = getattr(bpy.data, kind)
            for item in list(collection):
                if item not in previous[kind]:
                    collection.remove(item, do_unlink=True)
        raise
