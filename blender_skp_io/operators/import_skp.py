# SPDX-License-Identifier: MIT
"""
IMPORT_OT_skp -- Blender operator for importing SketchUp .skp and .skm files.
"""

from __future__ import annotations

import queue
import threading
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from .. import skppy


class IMPORT_OT_skp(Operator, ImportHelper):
    """Import a SketchUp model or standalone material"""

    bl_idname = "import_scene.skp"
    bl_label = "Import SketchUp (.skp/.skm)"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012

    # ImportHelper provides the 'filepath' property via the mixin
    filename_ext = ".skp"
    filter_glob: StringProperty(default="*.skp;*.skm", options={"HIDDEN"}, maxlen=255)

    scale: FloatProperty(
        name="Scale",
        description="Scale factor applied to all geometry (0.0254 converts inches to metres)",
        default=0.0254,
        min=0.0001,
        max=100.0,
        step=1,
        precision=4,
    )

    merge_vertices: BoolProperty(
        name="Merge Vertices",
        description="Weld coincident vertices after import",
        default=True,
    )

    smooth_edges: BoolProperty(
        name="Smooth Edges",
        description="Apply SketchUp smooth/soft edge shading when present",
        default=True,
    )

    import_materials: BoolProperty(
        name="Import Materials",
        description="Create Blender materials from SketchUp material definitions",
        default=True,
    )

    import_vray_materials: BoolProperty(
        name="Use Render Materials",
        description="Prefer V-Ray and Enscape PBR values when present; otherwise use SketchUp material appearance",
        default=False,
    )

    import_cameras: BoolProperty(
        name="Import Cameras",
        description="Create Blender camera objects from SketchUp saved views",
        default=True,
    )

    triangulation_mode: EnumProperty(
        name="Faces",
        description="How to tessellate imported polygons",
        items=[
            ("NGONS", "NGons", "Keep polygons as-is (n-gons)", 0),
            (
                "QUADS",
                "Quads",
                "Convert to quads where possible, triangles elsewhere",
                1,
            ),
            ("TRIS", "Triangles", "Triangulate all faces", 2),
        ],
        default="NGONS",
    )

    import_by_layers: BoolProperty(
        name="Import by Layers",
        description="Create a Blender collection for each SketchUp layer/tag",
        default=False,
    )

    flatten_hierarchy: BoolProperty(
        name="Flatten Hierarchy",
        description="Import all objects at the root level without Empty parents",
        default=False,
    )

    use_collection_instances: BoolProperty(
        name="Reuse Component Collections",
        description="Build reusable components once as Blender collection instances for much faster imports",
        default=False,
    )

    use_background_parse: BoolProperty(
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def invoke(self, context, event):
        """Open the file browser and request responsive background parsing."""
        self.use_background_parse = True
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        """Import synchronously for scripts or start a modal interactive import."""
        if self.use_background_parse and context.window is not None and not bpy.app.background:
            self.use_background_parse = False
            return self._start_background_import(context)
        return self._execute_synchronously(context)

    def modal(self, context, event):
        """Poll the parser worker while Blender continues processing UI events."""
        if event.type == "ESC":
            self._request_cancellation()
            self._finish_progress(context)
            self.report({"INFO"}, "SketchUp import cancelled")
            return {"CANCELLED"}

        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        try:
            outcome, payload = self._parse_results.get_nowait()
        except queue.Empty:
            elapsed = time.monotonic() - self._parse_started_at
            self._update_progress(
                context,
                5.0,
                f"Parsing SketchUp file ({elapsed:.0f}s)",
            )
            return {"RUNNING_MODAL"}

        if outcome == "error":
            self._finish_progress(context)
            self.report({"ERROR"}, f"Failed to parse SketchUp file: {payload}")
            return {"CANCELLED"}
        if outcome == "cancelled":
            self._finish_progress(context)
            self.report({"INFO"}, "SketchUp import cancelled")
            return {"CANCELLED"}

        try:
            if outcome == "material":
                self._update_progress(context, 75.0, "Building Blender material")
                bl_mat = self._build_material(payload)
                result = self._finish_material_import(bl_mat)
            else:
                self._update_progress(context, 50.0, "Building Blender scene")
                builder = self._build_scene(context, payload)
                result = self._finish_import(context, builder)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to build Blender data: {exc}")
            result = {"CANCELLED"}
        finally:
            self._finish_progress(context)
        return result

    def cancel(self, context):
        """Release modal timer and progress UI if Blender cancels the operator."""
        self._request_cancellation()
        self._finish_progress(context)

    def _start_background_import(self, context):
        """Start pure-Python parsing in a worker and enter Blender's modal loop."""
        self._parse_results = queue.SimpleQueue()
        self._parse_started_at = time.monotonic()
        self._cancel_event = threading.Event()
        self._begin_progress(context, "Parsing SketchUp file")

        worker = threading.Thread(
            target=self._parse_worker,
            args=(self.filepath, self.import_vray_materials, self._parse_results, self._cancel_event),
            name="skppy-parser",
            daemon=True,
        )
        self._parse_thread = worker
        worker.start()

        window_manager = context.window_manager
        self._timer = window_manager.event_timer_add(0.1, window=context.window)
        window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @staticmethod
    def _parse_worker(filepath, import_vray_materials, results, cancel_event) -> None:
        """Parse without touching Blender data and publish one worker outcome."""
        try:
            outcome = IMPORT_OT_skp._load_source(
                filepath,
                cancellation_check=cancel_event.is_set,
                import_vray_materials=import_vray_materials,
            )
            results.put(outcome)
        except skppy.LoadCancelledError:
            results.put(("cancelled", None))
        except Exception as exc:
            results.put(("error", exc))

    @staticmethod
    def _load_source(filepath, *, cancellation_check=None, import_vray_materials=False):
        """Load a model or material package, including incorrectly named SKM files."""
        try:
            model = skppy.load(
                filepath,
                cancellation_check=cancellation_check,
                import_vray_materials=import_vray_materials,
            )
            return "model", model
        except skppy.InvalidSkpError as model_error:
            try:
                material = skppy.load_material(filepath, import_vray_materials=import_vray_materials)
            except skppy.InvalidSkmError:
                raise model_error
            return "material", material

    def _request_cancellation(self) -> None:
        """Signal the cooperative parser scope owned by this operator."""
        event = getattr(self, "_cancel_event", None)
        if event is not None:
            event.set()

    def _execute_synchronously(self, context):
        """Preserve blocking semantics for Python and background-mode callers."""
        self._begin_progress(context, "Parsing SketchUp file")

        try:
            outcome, payload = self._load_source(self.filepath, import_vray_materials=self.import_vray_materials)
        except Exception as exc:
            self._finish_progress(context)
            self.report({"ERROR"}, f"Failed to parse SketchUp file: {exc}")
            return {"CANCELLED"}

        try:
            if outcome == "material":
                self._update_progress(context, 75.0, "Building Blender material")
                bl_mat = self._build_material(payload)
                return self._finish_material_import(bl_mat)
            self._update_progress(context, 50.0, "Building Blender scene")
            builder = self._build_scene(context, payload)
            return self._finish_import(context, builder)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to build Blender data: {exc}")
            return {"CANCELLED"}
        finally:
            self._finish_progress(context)

    @staticmethod
    def _build_material(material):
        """Create a persistent Blender data-block for a standalone material."""
        from ..scene_builder import BlenderSceneBuilder

        bl_mat = BlenderSceneBuilder.build_material(material)
        bl_mat.use_fake_user = True
        return bl_mat

    def _finish_material_import(self, bl_mat):
        """Report a completed standalone material import."""
        self.report({"INFO"}, f"Imported material {bl_mat.name!r} from {self.filepath}")
        return {"FINISHED"}

    def _build_scene(self, context, model):
        """Build Blender data on the main thread and return the scene builder."""
        from ..scene_builder import BlenderSceneBuilder

        builder = BlenderSceneBuilder(
            model=model,
            context=context,
            scale=self.scale,
            import_materials=self.import_materials,
            merge_vertices=self.merge_vertices,
            smooth_edges=self.smooth_edges,
            import_cameras=self.import_cameras,
            triangulation_mode=self.triangulation_mode,
            import_by_layers=self.import_by_layers,
            flatten_hierarchy=self.flatten_hierarchy,
            use_collection_instances=self.use_collection_instances,
            progress_callback=lambda fraction, message: self._update_progress(
                context,
                50.0 + fraction * 50.0,
                message,
            ),
        )
        builder.build()
        return builder

    def _finish_import(self, context, builder):
        """Report, select, and frame objects created by a completed build."""

        n = len(builder.created_objects)
        if n == 0:
            self.report({"WARNING"}, "Import finished but no geometry was created")
            return {"FINISHED"}

        self.report({"INFO"}, f"Imported {n} object(s) from {self.filepath}")

        # Background execution has no screen or 3D viewport to select and frame.
        # Scene construction is already complete, so this optional UI step must
        # not turn a successful import into a reported build failure.
        if bpy.app.background or context.screen is None:
            return {"FINISHED"}

        # Select the imported objects and zoom to them in any open 3D view.
        bpy.ops.object.select_all(action="DESELECT")
        for obj in builder.created_objects:
            obj.select_set(True)
        context.view_layer.objects.active = builder.created_objects[0]
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        with context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_selected()
                        break
                break

        return {"FINISHED"}

    def _begin_progress(self, context, message: str) -> None:
        """Initialize Blender's status-bar progress display."""
        self._progress_active = True
        self._timer = None
        context.window_manager.progress_begin(0.0, 100.0)
        self._update_progress(context, 1.0, message)

    def _update_progress(self, context, value: float, message: str) -> None:
        """Update status text and request a UI redraw from the main thread."""
        context.window_manager.progress_update(min(max(value, 0.0), 100.0))
        if context.workspace is not None:
            context.workspace.status_text_set(message)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

    def _finish_progress(self, context) -> None:
        """Remove timers and restore Blender's normal status display."""
        timer = getattr(self, "_timer", None)
        if timer is not None:
            context.window_manager.event_timer_remove(timer)
            self._timer = None
        if getattr(self, "_progress_active", False):
            context.window_manager.progress_end()
            self._progress_active = False
        if context.workspace is not None:
            context.workspace.status_text_set(None)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column()
        col.prop(self, "scale")
        col.separator()

        col.label(text="Geometry")
        col.prop(self, "merge_vertices")
        col.prop(self, "smooth_edges")
        col.prop(self, "triangulation_mode")
        col.prop(self, "flatten_hierarchy")
        instance_row = col.row()
        instance_row.enabled = not self.flatten_hierarchy and not self.import_by_layers
        instance_row.prop(self, "use_collection_instances")
        col.separator()

        col.label(text="Scene")
        col.prop(self, "import_materials")
        col.prop(self, "import_vray_materials")
        col.prop(self, "import_cameras")
        col.prop(self, "import_by_layers")
