# SPDX-License-Identifier: MIT
"""Blender operator for exporting the active scene to modern or SU2017 SKP."""

from __future__ import annotations

from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper


class EXPORT_OT_skp(Operator, ExportHelper):
    """Export Blender scene data through the bundled skppy writer."""

    bl_idname = "export_scene.skp"
    bl_label = "Export SketchUp (.skp)"
    bl_options = {"REGISTER"}  # noqa: RUF012

    filename_ext = ".skp"
    filter_glob: StringProperty(default="*.skp", options={"HIDDEN"}, maxlen=255)

    export_scope: EnumProperty(
        name="Objects",
        description="Choose which objects are included in the SKP model",
        items=[
            ("VISIBLE", "Visible", "Export visible, render-enabled scene objects", 0),
            ("SELECTED", "Selected", "Export only selected objects", 1),
            ("SCENE", "Entire Scene", "Export every object in the active scene", 2),
        ],
        default="VISIBLE",
    )
    output_format: EnumProperty(
        name="File Format",
        description="Choose the SketchUp file generation to write",
        items=[
            ("modern", "Modern", "Write the current ZIP-based SketchUp format", 0),
            ("sketchup_2017", "SketchUp Make 2017", "Write the legacy pre-ZIP SketchUp 2017 format", 1),
        ],
        default="modern",
    )
    inches_per_unit: FloatProperty(
        name="Inches per Blender Unit",
        description="39.3701 converts Blender metres to SketchUp inches",
        default=39.37007874015748,
        min=1.0e-6,
        max=1.0e6,
        precision=6,
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Export evaluated geometry with the current modifier stack",
        default=True,
    )
    merge_coplanar_faces: BoolProperty(
        name="Merge Coplanar Faces",
        description="Merge adjacent coplanar polygons with compatible materials and UV mappings, preserving holes",
        default=True,
    )
    export_materials: BoolProperty(
        name="Materials and PBR",
        description="Export material colors, opacity, metallic, and roughness",
        default=True,
    )
    export_textures: BoolProperty(
        name="Embedded Textures",
        description="Embed packed or file-backed images linked to Base Color",
        default=True,
    )
    export_uvs: BoolProperty(
        name="UV Coordinates",
        description="Convert active Blender UV maps into SKP face projections",
        default=True,
    )
    export_layers: BoolProperty(
        name="Collections as Tags",
        description="Map the first object collection or skppy_layer_name property to a SketchUp tag",
        default=True,
    )
    export_cameras: BoolProperty(
        name="Cameras and Markers",
        description="Export cameras and camera timeline markers as saved scenes",
        default=True,
    )
    export_text: BoolProperty(
        name="Text as Annotations",
        description="Export Blender Font objects as SketchUp text annotations",
        default=True,
    )
    export_custom_properties: BoolProperty(
        name="Custom Properties",
        description="Export scalar Blender custom properties as attribute dictionaries",
        default=True,
    )

    def draw(self, context) -> None:
        """Draw grouped geometry, appearance, and metadata settings."""
        del context
        layout = self.layout
        layout.prop(self, "output_format")
        layout.prop(self, "export_scope")
        layout.prop(self, "inches_per_unit")

        geometry = layout.box()
        geometry.label(text="Geometry")
        geometry.prop(self, "apply_modifiers")
        geometry.prop(self, "merge_coplanar_faces")
        geometry.prop(self, "export_text")

        appearance = layout.box()
        appearance.label(text="Appearance")
        appearance.prop(self, "export_materials")
        column = appearance.column()
        column.enabled = self.export_materials
        column.prop(self, "export_textures")
        column.prop(self, "export_uvs")

        metadata = layout.box()
        metadata.label(text="Organization and Metadata")
        metadata.prop(self, "export_layers")
        metadata.prop(self, "export_cameras")
        metadata.prop(self, "export_custom_properties")

    def execute(self, context):
        """Build the public model graph and serialize it atomically."""
        from ..export_builder import BlenderModelBuilder

        try:
            builder = BlenderModelBuilder(
                context,
                export_scope=self.export_scope,
                inches_per_unit=self.inches_per_unit,
                apply_modifiers=self.apply_modifiers,
                export_materials=self.export_materials,
                export_textures=self.export_textures,
                export_uvs=self.export_uvs,
                export_layers=self.export_layers,
                export_cameras=self.export_cameras and self.output_format == "modern",
                export_text=self.export_text and self.output_format == "modern",
                export_custom_properties=self.export_custom_properties and self.output_format == "modern",
                merge_coplanar_faces=self.merge_coplanar_faces,
            )
            model = builder.build()
            model.save(
                self.filepath,
                format=self.output_format,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to export .skp file: {exc}")
            return {"CANCELLED"}

        warning_count = len(builder.warnings)
        summary = (
            f"Exported {builder.exported_objects} object(s) to {self.filepath}; "
            f"ignored {builder.ignored_objects} unsupported object(s)"
        )
        if warning_count:
            summary += f"; {warning_count} conversion warning(s)"
            for warning in builder.warnings[:3]:
                self.report({"WARNING"}, warning)
        self.report({"INFO"}, summary)
        return {"FINISHED"}
