# SPDX-License-Identifier: MIT
"""Runtime-class dispatch and recursive resolution for legacy archives."""

from __future__ import annotations

from .binary import (
    ArchiveObjectHandle,
)
from .errors import UnsupportedLegacyObjectError
from .object_readers import OBJECT_READERS
from .session import LegacyArchiveSession
from .parser_types import (
    SupportedObjectPayload,
)
from .schema import require_verified_schema
from .read_context import ObjectReadContext


def read_supported_object(session: LegacyArchiveSession, class_versions: dict[str, int]) -> SupportedObjectPayload:
    """Read one supported object through the stateful archive dispatch table."""
    context = create_object_read_context(session, class_versions)
    handle = session.read_object_handle()
    return context.resolve(handle)


def create_object_read_context(session: LegacyArchiveSession, class_versions: dict[str, int]) -> ObjectReadContext:
    """Create one recursive resolver context shared by an archive section."""
    context: ObjectReadContext

    # Readers recurse through the same closure when an object's body contains
    # another tagged object. One shared context keeps class versions and table
    # identity consistent at every nesting depth.
    def resolve(handle: ArchiveObjectHandle) -> SupportedObjectPayload:
        return resolve_supported_object(
            session,
            handle,
            class_versions,
            context=context,
        )

    context = ObjectReadContext(session, class_versions, resolve)
    return context


def resolve_supported_object(
    session: LegacyArchiveSession,
    handle: ArchiveObjectHandle,
    class_versions: dict[str, int],
    *,
    context: ObjectReadContext | None = None,
) -> SupportedObjectPayload:
    """Resolve one previously read handle and register any new object payload."""
    if handle.kind == "object_ref":
        # Object references point at a body already consumed elsewhere. Return
        # the shared value without advancing the stream a second time.
        if handle.object_index is not None:
            return session.objects.get(handle.object_index, handle)
        return handle

    if context is None:
        context = create_object_read_context(session, class_versions)
    previous_object_index = context.current_object_index
    context.current_object_index = handle.object_index
    try:
        value = _read_supported_object_from_handle(
            session,
            handle,
            class_versions,
            context,
        )
    finally:
        # Recursive inline objects temporarily replace the current owner. The
        # parent must be restored before its remaining base fields are read.
        context.current_object_index = previous_object_index
    # Publish only complete objects. Recursive children are registered by their
    # own resolve calls while this parent is still being decoded.
    if handle.kind == "new_object" and handle.object_index is not None:
        session.store_object(handle.object_index, value)
    return value


def _read_supported_object_from_handle(
    session: LegacyArchiveSession,
    handle: ArchiveObjectHandle,
    class_versions: dict[str, int],
    context: ObjectReadContext,
) -> SupportedObjectPayload:
    if handle.kind == "object_ref":
        if handle.object_index is not None:
            return session.objects.get(handle.object_index, handle)
        return handle
    if handle.kind != "new_object":
        return handle

    class_name = handle.class_name
    # Validate before consuming the body: using a nearby schema usually keeps
    # reads looking plausible while silently shifting every later object.
    if class_name is not None and handle.schema is not None:
        require_verified_schema(
            class_name,
            handle.schema,
            file_version=session.file_version,
            offset=session.tell(),
            object_index=handle.object_index,
        )
    if class_name in OBJECT_READERS.keys():
        return OBJECT_READERS[class_name](context, handle)

    # Skipping an unknown body is unsafe because CArchive does not provide a
    # universal payload length. Fail at the first unknown class with context.
    raise _unsupported_legacy_object_error(session, handle)


def _unsupported_legacy_object_error(
    session: LegacyArchiveSession, handle: ArchiveObjectHandle
) -> UnsupportedLegacyObjectError:
    return UnsupportedLegacyObjectError(
        class_name=handle.class_name,
        offset=session.reader.tell(),
        schema=handle.schema,
        class_index=handle.class_index,
        object_index=handle.object_index,
        tag_kind=handle.tag.kind,
    )
