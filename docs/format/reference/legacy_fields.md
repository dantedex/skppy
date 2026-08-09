# Legacy Field Layouts

This reference lists the serialized members of every pre-ZIP runtime class
currently supported by `skppy`. Rows are in wire order. The class schema is
written as `v`; version gates refer to that class unless a row says otherwise.

The tables describe bytes, not Python implementation attributes. A derived
class starts with its serialized base-class body, so the base appears as the
first member rather than duplicating the same rows in every derived table.

## Type notation

| Type | Wire representation |
| --- | --- |
| `bool` | One-byte archive boolean |
| `u8`, `u16`, `u32`, `u64`, `i32` | Little-endian integer of the stated width |
| `sparse_u64` | One presence-mask byte followed by the selected bytes of a `u64` |
| `f32`, `f64` | Little-endian IEEE-754 value |
| `Point3`, `Vector3` | Three `f64` values |
| `Plane4` | Four `f64` values |
| `RGBA` | Four bytes in red, green, blue, alpha order |
| `GUID` | 16 uninterpreted bytes |
| `legacy_string` | Length-prefixed UTF-16 string described in [legacy container](legacy_container.md) |
| `object<T>` | Archive object tag followed by a body only when the tag introduces a new object |
| `object_ref<T>` | Archive object reference; `null` is allowed where the description says so |
| `inline<T>` | A serialized class body with no separate object tag at this position |
| `counted<T>` | `u32` count followed by that many values |
| `terminated<T>` | Values ending with the terminator named in the description |

## Common bases and root model

### `CEntity`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `legacy_flags` | `u32` | Historical entity flags. | `v == 1` |
| `attribute_container` | `object<CAttributeContainer>` | Optional attributes owned by this entity. | `v > 2` |
| `persistent_id` | `u64` | Fixed-width persistent identifier. | `v == 4` |
| `persistent_id` | `sparse_u64` | Sparse persistent identifier. | `v > 4` |

Schemas `0` and `2` have an empty body. In the SU3–8 maps, schema `2` is used
by SU3 and schema `3` stores only the attribute-container member.

### `CDrawingElement`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `material` | `object_ref<CMaterial>` | Front or primary display material; null means no material. | Always |
| `hidden` | `bool` | Element visibility flag. | `v != 0` |
| `casts_shadows` | `bool` | Whether the element casts shadows. | `v > 5` |
| `receives_shadows` | `bool` | Whether the element receives shadows. | `v > 5` |
| `soft` | `bool` | Soft-edge state. | `v > 6` |
| `smooth` | `bool` | Smooth-edge state. | `v > 7` |
| `locked` | `bool` | Lock state. | `v > 8` |
| `obsolete_reference_present` | `bool` | Announces a historical reference. | `v == 2` |
| `obsolete_reference` | `object_ref<?>` | Historical reference with no current public mapping. | `v == 2` and preceding flag is true |
| `layer` | `object_ref<CLayer>` | Owning layer/tag reference. | `v > 3` |

When schemas `0`–`5` omit the two shadow booleans, their decoded defaults are
true. Older schemas also derive smooth state from the stored soft state.

### `CComponentBehavior`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `is_2d` | `bool` | Whether placement is constrained to a plane. Older schemas imply true. | `v >= 3` |
| `cuts_opening` | `bool` | Whether placed instances cut an opening. | Always |
| `snap_to` | `u32` | Placement-plane mode. Schema `1` implies zero. | `v >= 2` |
| `camera_flags` | `u8` | Bit 0 faces the camera; bit 1 makes shadows face the sun. | `v > 3` |
| `no_scale_mask` | `u32` | Axes on which instance scaling is disabled. | `v >= 5` |

### `CSketchUpModel`

`CSketchUpModel` is the untagged root object. Its members include complete
embedded class bodies and object-bearing sections; the referenced class tables
define those bodies.

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `prologue_word_1` | `u32` | Confirmed root word whose semantics remain unnamed. | model `v >= 7` |
| `prologue_word_2` | `u32` | Second confirmed unnamed root word. | model `v >= 7` |
| `license_product_family` | `u32` | Product-family value recorded by the save target. | model `v >= 18` |
| `next_persistent_id` | `u64` | Next persistent entity identifier. | model `v >= 26` |
| `thumbnail_dib` | `object<CDib>` | Root thumbnail image object. | model `v > 3` |
| `redefine_thumbnail_on_save` | `bool` | Thumbnail regeneration state. | model `v > 3` |
| `root_behavior` | `inline<CComponentBehavior>` | Root component placement behavior. | Always |
| `description` | `legacy_string` | Model description. | Always |
| `options` | `inline<COptionsManager>` | Model option providers; older schemas place this in the tail. | model `v >= 21` |
| `model_properties` | `object<CAttributeContainer>` | Root attribute dictionaries. | model `v >= 21` |
| `camera_leading_object` | `object<?>` | Extra root-camera-section object, observed as null or `CDib`. | model `v >= 21` |
| `camera` | `object<CCamera>` or `inline<old camera>` | Root camera; model schemas below 11 use the older untagged body. | Always |
| `rendering_options` | `inline<CRenderingOptions>` | Root rendering state, including its `CEntity` base. | Always |
| `obsolete_vertex_count` | `u32` | Historical root vertex count. | Always |
| `validity_check_performed` | `u32` | Saved validity-check state. | model `v >= 18` |
| `root_component` | `inline<CComponent>` | Root materials, layers, definitions, and entities. | Always |
| `shadow_info` | `inline<CShadowInfo>` | Model shadow and geolocation state. | Always |
| `pages` | `inline<CPageList>` | Saved scenes; older schemas use an inline counted page array. | model `v >= 12` |
| `legacy_pages` | `counted<object<CViewPage>>` | Saved scenes before `CPageList`. | model `v < 12` |
| `model_axes` | `inline<CSketchCS>` | Model drawing axes, including the drawing-element base. | Always |
| `state_words` | `u32[16]` | Sixteen confirmed model-state words with no public semantic names. | Always |
| `tail_options` | `inline<COptionsManager>` | Model option providers at their older location. | model `v < 21` |
| `dimension_style` | `inline<CDimensionStyle>` | Default dimension style. | model `v >= 8` |
| `text_style` | `inline<CTextStyle>` | Default text style. | model `v >= 10` |
| `fonts` | `inline<CFontManager>` | Font registry. | Always |
| `line_styles` | `inline<CLineStyleManager>` | Custom line-style registry. | model `v >= 29` |
| `background_image` | `object<CBackgroundImage>` | Default model background image. | model `v == 13` or `v > 14` |
| `styles` | `inline<CSkpStyleManager>` | Named style registry. | model `v >= 14` |
| `watermarks` | `inline<CWatermarkManager>` | Watermark registry. | model `v >= 16` |
| `final_state` | `u32` | Late model-state word. | model `v >= 20` |
| `final_flag` | `bool` | Late model-state flag. | model `v >= 22` |

## Attributes and technical face data

### `CAttribute`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `attribute_code` | `u32` | Technical attribute discriminator/state value. | `v == 0` |

### `CAttributeContainer`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `entries` | `terminated<object<CAttribute>>` | Attribute objects, including named dictionaries and face UV data; a null object tag terminates the sequence. | `v == 0` |

### `CAttributeNamed`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `prefix` | `u32` | Technical dictionary prefix value. | Always |
| `name` | `legacy_string` | Dictionary name. | Always |
| `entries` | `terminated<(legacy_string, CTypedValue)>` | Key/value entries; an empty key terminates the sequence. | Always |
| `suffix` | `u32` | Technical dictionary suffix value. | `v > 0` |

The field-body reader is also used for unregistered root dictionaries after
their entity base has been consumed.

### `CFaceTextureCoords`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `attribute_flags` | `u32` | Attribute-level texture-coordinate flags. | Always |
| `front_transform` | `f64[9]` | Homogeneous front-side UVQ transform. | Always |
| `front_origin` | `Point3` | Front projection origin or direction carrier. | `v > 0` |
| `back_transform` | `f64[9]` | Homogeneous back-side UVQ transform. | `v > 1` |
| `back_origin` | `Point3` | Back projection origin or direction carrier. | `v > 1` |
| `front_pins` | `counted<(f64, f64, f64, f64)>` | Front texture/model coordinate pin pairs. | `v > 2` |
| `back_pins` | `counted<(f64, f64, f64, f64)>` | Back texture/model coordinate pin pairs. | `v > 2` |
| `front_flags` | `u32` | Bit `0x01` enables the side and bit `0x02` selects stored projection direction. | `v > 3` |
| `back_flags` | `u32` | Back-side equivalent of `front_flags`. | `v > 3` |

## Geometry and construction

### `CVertex`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `position` | `Point3` | Vertex position in model coordinates. | `v == 0` |

### `CEdge`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Visibility, material, layer, and edge-state flags. | Always |
| `start_vertex` | `object<CVertex>` | Start vertex; SU3 may reuse the previous edge's end through a chained edge reference. | Always |
| `end_vertex` | `object<CVertex>` | End vertex. | Always |
| `curve` | `object<CCurve>` | Optional owning curve. | `v >= 2` |

### `CEdgeUse`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `edge` | `object_ref<CEdge>` | Edge traversed by this loop use. | Always |
| `reversed` | `bool` | Reverses traversal relative to edge direction. | Always |
| `loop` | `object_ref<CLoop>` | Owning loop reference. | Always |
| `obsolete_reference_1` | `object_ref<?>` | Historical topology reference. | `v == 0` |
| `obsolete_reference_2` | `object_ref<?>` | Second historical topology reference. | `v == 0` |

### `CLoop`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `is_outer` | `bool` | Marks the outer face boundary. | Always |
| `is_convex` | `bool` | Cached convexity state. | Always |
| `edge_uses` | `terminated<object<CEdgeUse>>` | Directed boundary uses; a null object tag terminates the sequence. | Always |

### `CFace`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Entity, front material, visibility, and layer state. | Always |
| `plane` | `Plane4` | Face plane equation. | Always |
| `loops` | `counted<object<CLoop>>` | Outer loop first, followed by inner loops. | Always |
| `back_material` | `object_ref<CMaterial>` | Optional back-side material. | `v > 2` |

### `CCurve`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `first_edge` | `object_ref<CEdge>` | First edge of the historical SU3 range representation. | `v == 3` |
| `last_edge` | `object_ref<CEdge>` | Last edge of the historical SU3 range representation. | `v == 3` |
| `is_polygon` | `bool` | Whether the curve is polygonal. | `v in {3, 4}` |
| `edge_count` | `u32` | Number of owned edges; concrete edge links are supplied by edge curve references. | `v in {3, 4}` |

### `CArcCurve`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `curve` | `inline<CCurve>` | Shared curve base and edge ownership. | Always |
| `center` | `Point3` | Arc center. | `v >= 1` |
| `normal` | `Vector3` | Arc-plane normal. | `v >= 1` |
| `x_axis` | `Vector3` | Radius direction at zero angle. | `v >= 1` |
| `start_angle` | `f64` | Start parameter in radians. | `v >= 1` |
| `end_angle` | `f64` | End parameter in radians. | `v >= 1` |
| `y_axis` | `Vector3` | Second in-plane arc axis. | `v >= 1` |

### `CConstructionGeometry`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Complete payload of this base-only construction entity. | `v == 0` |

### `CConstructionPoint`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Visibility, material, and layer state. | Always |
| `position` | `Point3` | Guide point position. | `v == 0` |
| `reference_position` | `Point3` | Other endpoint of the optional guide segment. | `v == 0` |
| `has_reference_position` | `bool` | Whether `reference_position` is active. | `v == 0` |

### `CConstructionLine`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Visibility, material, and layer state. | Always |
| `origin` | `Point3` | Point on the guide line. | Always |
| `direction` | `Vector3` | Guide direction. | Always |
| `start_parameter` | `f64` | Lower parametric bound. | `v == 1` outside SU3 |
| `end_parameter` | `f64` | Upper parametric bound. | `v == 1` outside SU3 |
| `stipple_pattern` | `u32` | Guide display pattern. | `v == 1` outside SU3 |

### `CPolyline3d`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Visibility, material, and layer state. | Always |
| `points` | `counted<Point3>` | Ordered polyline positions. | `v == 0` |

### `CSectionPlane`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Visibility, material, and layer state. | Always |
| `plane` | `Plane4` | Section plane equation. | `v in {2, 3}` |
| `name` | `legacy_string` | Section-plane display name. | `v >= 3` and file target `>= 18` |
| `symbol` | `legacy_string` | Section-plane symbol. | `v >= 3` and file target `>= 18` |

## Components and collections

### `CComponent`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Component-level entity, material, layer, and display state. | Always |
| `materials` | `inline<CMaterialManager>` | Materials scoped to this component. | `v == 11` |
| `layers` | `inline<CLayerManager>` | Layers and active layer scoped to this component. | `v == 11` |
| `definitions` | `inline<CDefinitionList>` | Nested component definitions. | `v == 11` |
| `entities` | `counted<object<CEntity>>` | Top-level component entities. | `v == 11` |
| `relationships` | `counted<object<CRelationship>>` | Graph bookkeeping relationships. | `v == 11` |
| `active_section_plane` | `object<CSectionPlane>` | Active section plane, optionally introduced inline. | `v == 11` |

### `CComponentDefinition`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `component` | `inline<CComponent>` | Definition-owned materials, layers, definitions, entities, and relationships. | Always |
| `guid` | `GUID` | Stable definition identifier. | `v in {10, 11}` |
| `name` | `legacy_string` | Definition name. | `v in {10, 11}` |
| `description` | `legacy_string` | Definition description. | `v in {10, 11}` |
| `loaded_from` | `legacy_string` | Informational source path; consumers must not follow it. | `v in {10, 11}` |
| `timestamp` | `u32` | Saved source timestamp. | `v in {10, 11}` |
| `modified` | `bool` | Modification state. | `v in {10, 11}` |
| `insertion_point` | `Point3` | Definition insertion point. | `v in {10, 11}` |
| `behavior` | `inline<CComponentBehavior>` | Placement, opening, billboard, and scale behavior. | `v in {10, 11}` |
| `definition_type` | `u32` | Definition category; confirmed values identify ordinary, group, and image definitions. | `v in {10, 11}` |
| `thumbnail` | `object<CThumbnail>` | Optional definition preview. | `v in {10, 11}` |

### `CComponentInstance`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Entity, material, visibility, and layer state. | Always |
| `definition` | `object<CComponentDefinition>` | Referenced definition. | Always |
| `transform` | `f64[13]` | Legacy component placement transform. | Always |
| `name` | `legacy_string` | Optional instance name. | `v > 3` |
| `guid` | `GUID` | Instance GUID. | `v >= 5` |

### `CGroup`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `component_instance` | `inline<CComponentInstance>` | Complete placed-component body interpreted as a group. | `v == 1` |

### `CImage`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `component_instance` | `inline<CComponentInstance>` | Complete placed-component body interpreted as an image placement. | `v == 1` |

### `CDefinitionList`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `definitions` | `counted<object<CComponentDefinition>>` | Definition references; a first occurrence may introduce the full object inline. | `v == 0` |

### `CRelationship`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `source` | `object_ref<CEntity>` | Relationship source. | `v == 0` |
| `target` | `object_ref<CEntity>` | Relationship target. | `v == 0` |

### `CRelationshipMap`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `relationships` | `counted<object<CRelationship>>` | Relationship objects retained as valid source/target pairs. | `v == 0` |

## Materials, images, layers, and line styles

### `CMaterial`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `name` | `legacy_string` | Material name. | `v == 12` |
| `has_texture` | `bool` | Announces the inline texture body. | `v == 12` |
| `texture` | `inline<CTexture>` | Optional texture and embedded image. | `v == 12` and preceding flag is true |
| `used_by_layer` | `bool` | Whether this material is layer display state. | `v == 12` |
| `color` | `RGBA` | Base display color. | `v == 12` |
| `display_name` | `legacy_string` | Additional saved material string. | `v == 12` |
| `material_type` | `u32` | Material category. | `v == 12` |
| `colorize_type` | `u32` | Texture colorization mode. | `v == 12` |
| `transparency` | `f64` | Transparency amount, not opacity. | `v == 12` |
| `use_transparency` | `bool` | Enables the transparency scalar. | `v == 12` |

When transparency is enabled, public opacity is `clamp(1 - transparency)`;
otherwise opacity is `1.0`.

### `CMaterialManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `materials` | `counted<object<CMaterial>>` | Material registry in archive order. | Always |
| `current_material` | `object_ref<CMaterial>` | Runtime selection state, not a separate public material. | `v >= 2` |

### `CTexture`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `has_inline_dib` | `bool` | Announces an untagged `CDib` body in older layouts. | `v < 5` |
| `inline_dib` | `inline<CDib>` | Older embedded image body. | `v < 5` and preceding flag is true |
| `entity` | `inline<CEntity>` | Common entity state in newer layouts. | `v >= 5` |
| `dib` | `object<CDib>` | Embedded image object. | `v >= 5` |
| `width` | `f64` | Physical texture width in model inches. | Always |
| `height` | `f64` | Physical texture height in model inches. | Always |
| `filename` | `legacy_string` | Informational texture filename. | Always |
| `average_color` | `RGBA` | Saved average image color. | Always |

### `CDib`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `image_format` | `u32` | Encoded-image format. Schema `1` implies value `4` without storing it. | `v > 1` |
| `byte_count` | `u32` | Length of encoded image data. | `v > 0` |
| `image_bytes` | `u8[byte_count]` | Bounded PNG, JPEG, BMP, or related encoded bytes. | `v > 0` |
| `format_1_suffix` | `u32` | Extra format-specific word. | `v >= 3` and `image_format == 1` |

Schema `0` has an empty body.

### `CThumbnail`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `camera` | `inline<old camera>` | Untagged historical camera payload. | `v == 0` |
| `camera` | `object<CCamera>` | Camera associated with the thumbnail. | `v == 1` |
| `dib` | `object<CDib>` | Thumbnail image bytes. | `v in {0, 1}` |

### `CLayer`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `name` | `legacy_string` | Layer/tag name. | Always |
| `hidden` | `bool` | Stored inverse of public visibility. | Always |
| `display_material` | `inline<CMaterial>` | Layer display material; it is not added to the model material registry. | Always |
| `page_behavior` | `u32` | Per-scene visibility behavior. | `v > 1` |
| `obsolete_reference` | `object_ref<?>` | Historical layer reference with no current public mapping. | `v > 2` |

### `CLayerManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `layers` | `counted<object<CLayer>>` | Layer registry. | Always |
| `active_layer` | `object_ref<CLayer>` | Active layer. | `v == 3` or layer count is nonzero |
| `folders` | `counted<object<CLayerGroup>>` | Flat folder list used by the first folder layout. | `v == 6` |
| `root_folder` | `inline<CLayerGroup>` | Root of the nested folder tree. | `v >= 7` |

### `CLayerGroup`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `name` | `legacy_string` | Folder name. | `v in {1, 2, 3}` |
| `child_folders` | `counted<object<CLayerGroup>>` | Nested folders. | `v in {1, 2, 3}` |
| `child_layers` | `counted<object_ref<CLayer>>` | Layers directly owned by the folder. | `v in {1, 2, 3}` |
| `visible` | `bool` | Folder visibility. | `v > 1` |
| `expanded` | `bool` | Saved user-interface expansion state. | `v > 2` |

### `CCustomLineStyle`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `historical_entity` | `inline<CEntity>` | Second historical entity body. | `v < 3` |
| `name` | `legacy_string` | Line-style name. | `v in {1, 2, 3, 4}` |
| `dash_code` | `u16` | Numeric dash pattern. | `v == 1` |
| `dash_pattern` | `legacy_string` | Text dash pattern. | `v > 1` |
| `line_width_points` | `f64` | Display width in points. | Always |
| `stipple_scale` | `f64` | Dash-pattern scale. | `v > 1` |
| `superseded_width` | `f64` | Historical width value retained for alignment. | `v in {2, 3}` |
| `color` | `u32` | Packed line color. | `v >= 4` |
| `mutable` | `u8` | Whether the style can be edited. | `v >= 4` |

## Cameras, pages, and visual metadata

### `CCamera`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `eye` | `Point3` | Camera position. | Always |
| `target` | `Point3` | Look-at target. | Always |
| `up` | `Vector3` | Up direction. | Always |
| `near` | `f64` | Near clipping distance. | Always |
| `far` | `f64` | Far clipping distance. | Always |
| `perspective` | `bool` | Perspective rather than orthographic projection. | Always |
| `field_of_view` | `f64` | Perspective field of view. | Always |
| `orthographic_height` | `f64` | Orthographic view height. | Always |
| `obsolete_vector` | `Vector3` | Historical vector retained for alignment. | Always |
| `aspect_ratio` | `f64` | Image aspect ratio. | Always |
| `fov_is_height` | `bool` | Whether field of view is measured vertically. | Always |
| `legacy_flag` | `bool` | Confirmed camera flag whose semantics remain unnamed. | `v >= 2` |
| `name` | `legacy_string` | Camera name. | `v > 2` |
| `image_width` | `f64` | Saved image-plane width. | `v > 3` |
| `is_2d` | `bool` | Two-dimensional camera mode. | `v > 4` |
| `scale_2d` | `f64` | Two-dimensional view scale. | `v > 4` |
| `center_2d_x` | `f64` | Two-dimensional image center X. | `v > 4` |
| `center_2d_y` | `f64` | Two-dimensional image center Y. | `v > 4` |

The untagged SU3 camera replaces `target` with a direction vector and ends
after the obsolete vector; the public target is reconstructed as `eye +
direction`.

### `CSketchUpPage`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `name` | `legacy_string` | Scene/page name. | `v == 1` |
| `description` | `legacy_string` | Scene/page description. | `v == 1` |

### `CViewPage`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `page` | `inline<CSketchUpPage>` | Entity base, page name, and description. | Always |
| `flags` | `u32` | Snapshot-presence mask: camera, rendering, shadows, axes, hidden entities, layer visibility, and sections. | Always |
| `camera` | `inline<old camera>` or `object<CCamera>` | Camera snapshot; untagged before page schema 7. | camera bit set |
| `rendering_options` | `inline<CRenderingOptions>` | Rendering snapshot, including its entity base. | rendering bit set |
| `style` | `object_ref<CSkpStyle>` | Style used by the rendering snapshot. | rendering bit set and `v > 9` |
| `shadow_info` | `inline<CShadowInfo>` | Shadow snapshot. | shadow bit set |
| `display_shadows` | `bool` | Scene-local shadow visibility. | shadow bit set |
| `axes` | `inline<CSketchCS>` | Axes snapshot. | axes bit set |
| `display_axes` | `bool` | Scene-local axes visibility. | axes bit set |
| `hidden_entities` | `counted<object_ref<CEntity>>` | Hidden entity set. | hidden bit set |
| `hidden_layers` | `counted<object_ref<CLayer>>` | Layer-visibility override set. | layer-visibility bit set |
| `active_section_planes` | `counted<object_ref<CSectionPlane>>` | Active section-plane set. | section bit set |
| `show_in_slideshow` | `bool` | Include page in scene animation. | Always |
| `display_watermarks` | `bool` | Historical page-level watermark state. | `6 <= v <= 10` |
| `transition_time` | `f64` | Transition duration. | `v >= 8` |
| `delay_time` | `f64` | Pause duration. | `v >= 9` |
| `background_image` | `object<CBackgroundImage>` | Optional page background image. | `v > 9` |
| `display_background_image` | `bool` | Scene-local background-image visibility. | `v >= 12` |
| `image_rep_present` | `bool` | Announces an embedded `ImageFileRep`. | `v >= 12` |
| `image_rep` | `inline<ImageFileRep>` | Optional saved image representation. | `v >= 12` and preceding flag is true |

### `CPageList`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `pages` | `counted<object<CViewPage>>` | Saved pages in display order. | `v == 1` |
| `active_page` | `object_ref<CViewPage>` | Runtime active-page selection. | `v == 1` |

### `CBackgroundImage`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `image_reference` | `inline<ImageReference>` | Image path, data, dimensions, and saved file state. | `v == 10` |
| `visible` | `bool` | Background-image visibility. | `v == 10` |
| `opacity` | `f64` | Background-image opacity. | `v == 10` |
| `grip_points` | `counted<Point3>` | Calibration/control points. | `v == 10` |
| `principal_point_delta` | `Vector3` | Photo-match principal-point offset. | `v == 10` |
| `radial_distortion_k1` | `f64` | First radial lens-distortion coefficient. | `v == 10` |
| `image_source` | `u32` | Saved image-source category. | `v == 10` |

### `CSketchCS`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Present when the axes object is read from the archive graph. | Always |
| `origin` | `Point3` | Axes origin. | `v == 0` |
| `x_axis` | `Vector3` | X-axis direction. | `v == 0` |
| `y_axis` | `Vector3` | Y-axis direction. | `v == 0` |
| `z_axis` | `Vector3` | Z-axis direction. | `v == 0` |

The root-model axes body follows an already consumed drawing-element prefix;
the four geometric members above are the `CSketchCS` field body.

### `CShadowInfo`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `time` | `u32` | Saved shadow time value. | `v == 7` |
| `daylight_savings` | `bool` | Daylight-saving adjustment. | `v == 7` |
| `country` | `legacy_string` | Geolocation country. | `v == 7` |
| `city` | `legacy_string` | Geolocation city. | `v == 7` |
| `longitude` | `f64` | Longitude in degrees. | `v == 7` |
| `latitude` | `f64` | Latitude in degrees. | `v == 7` |
| `timezone_offset` | `f64` | Time-zone offset. | `v == 7` |
| `north_direction` | `Vector3` | Model north direction. | `v == 7` |
| `display_shadows` | `bool` | Master shadow visibility. | `v == 7` |
| `display_north` | `bool` | North-indicator visibility. | `v == 7` |
| `display_on_all_faces` | `bool` | Draw shadows on all faces. | `v == 7` |
| `display_on_ground_plane` | `bool` | Draw shadows on the ground plane. | `v == 7` |
| `light` | `i32` | Light intensity setting. | `v == 7` |
| `dark` | `i32` | Dark intensity setting. | `v == 7` |
| `use_sun_for_all_shading` | `bool` | Use sun direction for all face shading. | `v == 7` |

### `CWatermark`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `leading_flag` | `bool` | Confirmed watermark flag with no public semantic name. | `v == 1` |
| `name` | `legacy_string` | Watermark name. | `v == 1` |
| `state_word` | `u32` | Confirmed saved state word. | `v == 1` |
| `position` | `u32` | Watermark placement mode. | `v == 1` |
| `state_flag_1` | `bool` | First saved placement/display flag. | `v == 1` |
| `state_flag_2` | `bool` | Second saved placement/display flag. | `v == 1` |
| `state_flag_3` | `bool` | Third saved placement/display flag. | `v == 1` |
| `state_flag_4` | `bool` | Fourth saved placement/display flag. | `v == 1` |
| `state_flag_5` | `bool` | Fifth saved placement/display flag. | `v == 1` |
| `scale` | `f64` | Saved watermark scale value. | `v == 1` |
| `opacity` | `f64` | Watermark opacity. | `v == 1` |
| `path` | `legacy_string` | Informational source path. | `v == 1` |
| `dib` | `object<CDib>` | Encoded watermark image. | `v == 1` |

### `CWatermarkManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `watermarks` | `counted<object<CWatermark>>` | Watermark registry. | `v == 2` |

## Annotations, fonts, and styles

### `CDimension`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Entity, material, visibility, and layer state. | Always |
| `text` | `legacy_string` | Dimension text. | Always |
| `font` | `object<CSkFont>` | Dimension font. | `v >= 1` |
| `is_3d_text` | `bool` | Whether text is placed in model space. | `v >= 1` |
| `arrow_type` | `u32` | Dimension arrowhead type. | `v >= 1` |

### `CDimensionLinear`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `dimension` | `inline<CDimension>` | Common dimension text, font, and drawing state. | Always |
| `start_ref` | `inline<CPointRef>` | First measured anchor. | Always |
| `end_ref` | `inline<CPointRef>` | Second measured anchor. | Always |
| `normal` | `Vector3` | Dimension-plane normal. | Always |
| `x_axis` | `Vector3` | Dimension local X direction. | Always |
| `dimension_type` | `u32` | Linear dimension layout type. | Always |
| `y_position` | `f64` | Text/line position on the local Y axis. | Always |
| `x_position` | `f64` | Text/line position on the local X axis. | Always |
| `text_position` | `u32` | Explicit text-position mode; older schemas imply zero. | `v > 5` |

### `CDimensionRadial`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `dimension` | `inline<CDimension>` | Common dimension text, font, and drawing state. | Always |
| `target` | `object_ref<CEdge>` | Referenced arc edge; null selects embedded arc geometry. | `v == 2` |
| `parameter` | `f64` | Parameter on the target arc. | `v == 2` |
| `radius_ratio` | `f64` | Radial leader placement ratio. | `v == 2` |
| `is_diameter` | `bool` | Diameter rather than radius annotation. | `v == 2` |
| `arc` | `inline<CArc3d>` | Fallback arc when `target` is null. | `v == 2` and target is null |

### `CText`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `drawing_element` | `inline<CDrawingElement>` | Entity, material, visibility, and layer state. | Always |
| `font` | `object<CSkFont>` | Text font. | `v == 9` |
| `screen_x` | `f64` | Saved horizontal screen offset. | `v == 9` |
| `screen_y` | `f64` | Saved vertical screen offset. | `v == 9` |
| `point_ref` | `inline<CPointRef>` | Anchor entity, point, and instance paths. | `v == 9` |
| `leader_vector` | `Vector3` | Leader direction/offset. | `v == 9` |
| `view_direction` | `Vector3` | View direction used for placement. | `v == 9` |
| `leader_type` | `u32` | Leader layout type. | `v == 9` |
| `line_weight` | `u32` | Leader line weight. | `v == 9` |
| `point_ref_front` | `bool` | Front-side anchor state. | `v == 9` |
| `hide_out_of_plane` | `bool` | Hide when viewed out of plane. | `v == 9` |
| `arrow_type` | `u32` | Leader arrowhead type. | `v == 9` |
| `display_leader` | `bool` | Leader visibility. | `v == 9` |
| `text` | `legacy_string` | Annotation text. | `v == 9` |
| `convert_to_screen_on_explode` | `bool` | Conversion behavior when exploding its owner. | `v == 9` |
| `hidden_leader_direction` | `u32` | Saved direction for a hidden leader. | `v == 9` |

### `CSkFont`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `face_name` | `legacy_string` | Typeface family name. | `v in {0, 1}` |
| `bold` | `bool` | Bold style. | `v in {0, 1}` |
| `italic` | `bool` | Italic style. | `v in {0, 1}` |
| `point_size` | `u32` | Screen size in points. | `v in {0, 1}` |
| `use_world_size` | `bool` | Enables model-space font sizing. | `v > 0` |
| `world_size` | `f64` | Model-space text height. | `v > 0` |

### `CFontManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `fonts` | `counted<object<CSkFont>>` | Font registry. | `v == 0` |

### `CTextStyle`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `font` | `object_ref<CSkFont>` | Primary/world font. | `v in {4, 5}` |
| `arrow_type` | `u32` | Leader arrowhead type. | `v in {4, 5}` |
| `line_weight` | `u32` | Leader line weight. | `v in {4, 5}` |
| `hide_out_of_plane` | `bool` | Hide out-of-plane text. | `v in {4, 5}` |
| `leader_type` | `u32` | Leader layout type. | `v in {4, 5}` |
| `display_leader` | `bool` | Default leader visibility. | `v in {4, 5}` |
| `color` | `RGBA` | Model-space text color. | `v in {4, 5}` |
| `screen_color` | `RGBA` | Screen-space text color; schema 4 reuses `color`. | `v > 4` |
| `screen_font` | `object_ref<CSkFont>` | Screen-space font; schema 4 reuses `font`. | `v > 4` |

### `CDimensionStyle`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `style_version` | `u32` | Saved style serialization word. | `v == 4` |
| `font` | `object_ref<CSkFont>` | Dimension font. | `v == 4` |
| `text_3d` | `bool` | Place text in model space. | `v == 4` |
| `always_readable` | `bool` | Keep text readable from either view side. | `v == 4` |
| `extension_offset` | `u32` | Extension-line offset. | `v == 4` |
| `extension_overshoot` | `u32` | Extension-line overshoot. | `v == 4` |
| `line_weight` | `u32` | Dimension line weight. | `v == 4` |
| `arrow_type` | `u32` | Arrowhead type. | `v == 4` |
| `arrow_size` | `u32` | Arrowhead size. | `v == 4` |
| `highlight_non_associative` | `bool` | Highlight dimensions detached from geometry. | `v == 4` |
| `highlight_color` | `RGBA` | Detached-dimension highlight color. | `v == 4` |
| `show_radial_diameter_prefix` | `bool` | Show radius/diameter prefix. | `v == 4` |
| `hide_out_of_plane` | `bool` | Hide out-of-plane dimensions. | `v == 4` |
| `hide_out_of_plane_value` | `f64` | Out-of-plane threshold. | `v == 4` |
| `hide_small` | `bool` | Hide dimensions below a size threshold. | `v == 4` |
| `hide_small_value` | `f64` | Small-dimension threshold. | `v == 4` |
| `color` | `RGBA` | Dimension line color. | `v == 4` |
| `text_color` | `RGBA` | Dimension text color. | `v == 4` |
| `text_position` | `u32` | Default text-position mode. | `v == 4` |

### `CSkpStyle`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `guid` | `GUID` | Style identifier. | `v in {1, 2}` |
| `initial_file_name` | `legacy_string` | Original style filename. | `v in {1, 2}` |
| `style_version` | `u32` | Version of the style option stream. | `v in {1, 2}` |
| `display_name` | `legacy_string` | User-facing style name. | `v in {1, 2}` |
| `file_name` | `legacy_string` | Current style filename. | `v in {1, 2}` |
| `options` | `counted<(u32 key, style variant)>` | Heterogeneous style options; object-bearing NPR and watermark values retain archive references. | `v in {1, 2}` |

### `CSkpStyleManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `styles` | `counted<object<CSkpStyle>>` | Named styles. | `v == 2` |
| `active_style` | `object_ref<CSkpStyle>` | Active style. | `v == 2` and count is nonzero |
| `selected_style` | `object_ref<CSkpStyle>` | Selected style. | `v == 2` and count is nonzero |
| `selected_style_dirty` | `bool` | Whether the selected style has unsaved changes. | `v == 2` and count is nonzero |

## Rendering options

### `CRenderingOptions`

The root and scene forms consume the same entity body immediately before the
following ordered members.

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `render_mode` | `u32` | Face rendering mode. | Always |
| `model_transparency` | `bool` | Model-level transparency display. | Always |
| `material_transparency` | `bool` | Material transparency display. | Always |
| `jitter_edges` | `bool` | Jittered edge display. | Always |
| `line_style_edges` | `bool` | Custom line-style edge display; older schemas imply true. | `v > 37` |
| `edge_display_mode` | `u32` | Edge visibility mode. | Always |
| `background_color` | `RGBA` | View background color. | Always |
| `foreground_color` | `RGBA` | Foreground/edge color. | Always |
| `highlight_color` | `RGBA` | Selection highlight color. | Always |
| `construction_color` | `RGBA` | Construction-geometry color. | Always |
| `obsolete_display_flag` | `bool` | Historical display flag with intentionally unnamed semantics. | Always |
| `display_instance_axes` | `bool` | Component-instance axes visibility. | Always |
| `display_color_by_layer` | `bool` | Color geometry by layer. | Always |
| `texture` | `bool` | Texture display. | Always |
| `edge_color_mode` | `u32` | Edge color source. | Always |
| `extend_lines` | `bool` | Extend edge endpoints. | Always |
| `line_extension` | `u32` | Extension length. | Always |
| `draw_silhouettes` | `bool` | Silhouette edge display. | Always |
| `silhouette_width` | `u32` | Silhouette width. | Always |
| `draw_depth_que` | `bool` | Depth-cued edge display. | `v >= 26` |
| `depth_que_width` | `u32` | Depth-cue width. | `v >= 26` |
| `draw_line_ends` | `bool` | Line-end display. | `v >= 26` |
| `line_end_width` | `u32` | Line-end width. | `v >= 26` |
| `draw_profiles_only` | `bool` | Restrict profile processing to profiles. | `v >= 28` |
| `draw_hidden_geometry` | `bool` | Hidden geometry visibility. | Always |
| `draw_hidden_objects` | `bool` | Hidden object visibility; older schemas reuse hidden geometry. | `v >= 39` |
| `face_color_mode` | `u32` | Face color source/mode. | Always |
| `face_front_color` | `RGBA` | Default front-face color. | Always |
| `face_back_color` | `RGBA` | Default back-face color. | Always |
| `inactive_fade` | `f64` | Fade amount for inactive geometry. | Always |
| `instance_fade` | `f64` | Fade amount for other component instances. | Always |
| `inactive_hidden` | `bool` | Hide inactive geometry. | Always |
| `instance_hidden` | `bool` | Hide other component instances. | Always |
| `display_fog` | `bool` | Fog visibility. | `v >= 29` |
| `fog_color` | `RGBA` | Fog color. | `v >= 29` |
| `fog_use_background_color` | `bool` | Use background color for fog. | `v >= 29` |
| `fog_start_dist` | `f64` | Fog start distance. | `v >= 29` |
| `fog_end_dist` | `f64` | Fog end distance. | `v >= 29` |
| `fog_hint_mode` | `u32` | Fog distance interpretation. | `v >= 30` |
| `edge_type` | `u32` | Edge rendering type. | `v > 30` |
| `display_sketch_axes` | `bool` | Model axes visibility. | `v > 30` |
| `display_text` | `bool` | Text visibility. | `v > 30` |
| `display_dims` | `bool` | Dimension visibility. | `v > 30` |
| `hide_construction_geometry` | `bool` | Hide guides and construction points. | `v > 30` |
| `sky_color` | `RGBA` | Sky color. | Always |
| `horizon_color` | `RGBA` | Horizon color. | `v >= 24` |
| `ground_color` | `RGBA` | Ground color. | Always |
| `draw_horizon` | `bool` | Horizon visibility. | Always |
| `draw_ground` | `bool` | Ground visibility. | Always |
| `draw_underground` | `bool` | Ground display below the horizon. | Always |
| `ground_transparency` | `u32` | Ground transparency. | Always |
| `section_active_color` | `RGBA` | Active section-plane color. | Always |
| `section_inactive_color` | `RGBA` | Inactive section-plane color. | Always |
| `section_default_cut_color` | `RGBA` | Default section-cut color. | Always |
| `section_cut_width` | `u32` | Section-cut line width. | Always |
| `section_display_mode` | `u32` | Bit `0x01` displays planes; bit `0x02` displays cuts. | Always |
| `section_default_fill_color` | `RGBA` | Default section-fill color. | `v > 36` |
| `section_cut_filled` | `bool` | Section fill visibility. | `v > 36` |
| `transparency_sort` | `u32` | Transparency sorting mode. | Always |
| `draw_soft_edges` | `bool` | Soft-edge display. | Always |
| `soft_edge_limit` | `f64` | Smoothing angle/limit. | Always |
| `draw_smooth_edges` | `bool` | Smooth-edge display. | Always |
| `mipmap_option` | `bool` | Historical model-level mipmap option. | `v in {23, 24, 33}` |
| `locked_color` | `RGBA` | Locked-entity display color. | `v >= 27` |
| `display_watermarks` | `bool` | Watermark visibility. | `v >= 32` |
| `xray_opacity` | `f64` | X-ray opacity. | `v >= 35` |
| `draw_back_edges` | `bool` | Back-edge display. | `v >= 36` |
| `photomatch_draw_background` | `bool` | Photo-match background visibility. | `v >= 36` |
| `photomatch_background_opacity` | `f64` | Photo-match background opacity. | `v >= 36` |
| `photomatch_draw_overlay` | `bool` | Photo-match overlay visibility. | `v >= 36` |
| `photomatch_overlay_opacity` | `f64` | Photo-match overlay opacity. | `v >= 36` |

Confirmed complete schemas are `22`, `25`, `28`, `32`, and `35`–`39`.
Intermediate gate numbers explain field evolution but are not all known as
complete emitted layouts.

## Embedded serialization records

These records are not independent entries in the SU8 version map, but named
class-like payloads occur inside the supported runtime classes above.

### `CPointRef`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `kind` | `u32` | Point-reference kind. | Always |
| `format_version` | `u32` | Selects the optional reference/path members. | Always |
| `position` | `Point3` | Saved point position. | Always |
| `leaf` | `object<CEntity>` | Referenced leaf entity. | Always |
| `secondary_leaf` | `object<CEntity>` | Optional second leaf. | format version `> 0` |
| `instance_path` | `counted<object<CComponentInstance>>` | Primary nested-instance path. | Always |
| `secondary_instance_path` | `counted<object<CComponentInstance>>` | Secondary nested-instance path. | format version `> 3` |

### `CArc3d`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `center` | `Point3` | Arc center. | Always |
| `normal` | `Vector3` | Arc-plane normal. | Always |
| `x_axis` | `Vector3` | First in-plane axis. | Always |
| `start_angle` | `f64` | Start angle. | Always |
| `end_angle` | `f64` | End angle. | Always |
| `y_axis` | `Vector3` | Second in-plane axis. | Owning layout requests it |

### `CTypedValue`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `type_code` | `u8` | Selects the following payload representation. | Always |
| `value` | Type selected by `type_code` | Null (`0`); integers (`2`–`4`, `8`, `9`); `f32` (`5`); `f64`/time-like values (`6`, `12`–`16`); bool (`7`); string (`10`); nested array (`11`); triples (`17`–`19`); or 16-double transform (`20`). | Type is not null |

### `COptionsManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `version` | `u32` | Options-manager serialization version. | Always |
| `providers` | `counted<option provider>` | Named option-provider records. | Always |
| `provider.name` | `legacy_string` | Provider name. | For each provider |
| `provider.entries` | `terminated<(legacy_string, CTypedValue)>` | Option name/value pairs; an empty name terminates the provider. | For each provider |

### `CLineStyleManager`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `entity` | `inline<CEntity>` | Common entity state. | Always |
| `styles` | `counted<object<CCustomLineStyle>>` | Custom line-style registry. | Always |

### `ImageReference`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `path` | `legacy_string` | Informational image path. | `v == 3` |
| `state` | `u32` | Saved image-reference state. | `v == 3` |
| `dib` | `object<CDib>` | Encoded image data. | `v == 3` |
| `width` | `u32` | Pixel width. | `v == 3` |
| `height` | `u32` | Pixel height. | `v == 3` |
| `file_size` | `u32` | Saved source-file size. | `v == 3` |
| `timestamp` | `u32` | Saved source-file timestamp. | `v == 3` |

### `ImageFileRep`

| Member | Type | Description | Present when |
| --- | --- | --- | --- |
| `has_data` | `bool` | Announces an encoded byte payload. | Always |
| `byte_count` | `u32` | Encoded payload length. | `has_data` is true |
| `image_bytes` | `u8[byte_count]` | Bounded image-representation bytes. | `has_data` is true |

## Deliberately neutral names

Fields whose behavior is not established by controlled fixtures retain names
such as `state_word`, `obsolete_*`, or `legacy_flag`. This keeps byte order and
type information explicit without assigning unsupported semantics.
