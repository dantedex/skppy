# SPDX-License-Identifier: MIT
"""Finalize legacy scene payloads into the shared model scene list."""

from __future__ import annotations

from ..data_structure.model import Model
from ..data_structure.scene_data import Scene

from .parser_types import SceneState
from .scene_pages import RecoveredSceneState


def populate_scenes(
    model: Model,
    direct_scenes: tuple[SceneState, ...],
    recovered_scenes: tuple[RecoveredSceneState, ...],
) -> None:
    """Prefer direct scene objects while preserving bounded recovery payloads."""
    direct_by_offset = {scene.payload_start_offset: scene for scene in direct_scenes}
    consumed_offsets: set[int] = set()
    for recovered in recovered_scenes:
        direct = direct_by_offset.get(recovered.payload_start_offset)
        if direct is not None:
            consumed_offsets.add(recovered.payload_start_offset)
            model.scenes.append(
                _finalize_scene(
                    direct,
                    scene_id=len(model.scenes) + 1,
                    raw_payload=recovered.raw_tail_payload,
                )
            )
            continue
        model.scenes.append(
            Scene(
                id=len(model.scenes) + 1,
                name=recovered.name,
                description=recovered.description,
                flags=recovered.flags_u32 or 0,
                show_in_slideshow=(
                    recovered.include_in_animation if recovered.include_in_animation is not None else True
                ),
                raw_payload=recovered.raw_tail_payload,
            )
        )
    for direct in direct_scenes:
        if direct.payload_start_offset not in consumed_offsets:
            model.scenes.append(_finalize_scene(direct, scene_id=len(model.scenes) + 1))


def _finalize_scene(
    archived_scene: SceneState,
    *,
    scene_id: int,
    raw_payload: bytes | None = None,
) -> Scene:
    archived_scene.scene.id = scene_id
    archived_scene.scene.raw_payload = raw_payload
    return archived_scene.scene
