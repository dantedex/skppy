# SPDX-License-Identifier: MIT
"""
Core TLV primitives for SketchUp model.dat binary encoding.

Record wire format (model.dat geometry section):
    tag    : u16 little-endian  (2 bytes)
    length : u32 little-endian  (4 bytes)
    payload: <length> bytes
"""

from __future__ import annotations

import struct
from enum import IntEnum
from typing import Iterator, Optional, Tuple

from .._cancellation import check_cancelled

HEADER_SIZE = 6  # 2-byte tag + 4-byte length


class TlvTag(IntEnum):
    """All known TLV tag values for SketchUp model.dat binary format.

    This enum contains every tag recognized by the skppy parser, covering
    root-level blocks (0x01F4-0x0214), entity records (0x05DC-0x7D64),
    and all sub-tags for materials, layers, cameras, styles, etc.

    Tags are grouped by functional area with comments indicating the
    hex range and purpose.  The numeric values match the on-disk TLV
    tag integers used in SketchUp's ``model.dat`` binary stream.

    See the SketchUp C API headers for the canonical tag definitions.
    """

    # Root-level blocks
    MODEL_ROOT = 0x01F4
    MODEL_ID_COUNTER = 0x01F5
    ENTITIES_BLOCK = 0x01F6
    MATERIALS_BLOCK = 0x01F7
    LAYERS_BLOCK = 0x01F8
    DEFINITIONS_BLOCK = 0x01F9
    CAMERA_BLOCK = 0x01FA
    RENDERING_OPTIONS = 0x01FB
    MODEL_VIEW = 0x01FC
    FONTS = 0x01FD
    TEXT_STYLE_BLOCK = 0x01FE
    DIMENSION_STYLE_BLOCK = 0x01FF
    OPTIONS_MANAGER_BLOCK = 0x0200
    MODEL_EMPTY_MARKER = 0x0201
    BACKGROUND_IMAGES_BLOCK = 0x0201
    ACTIVE_BACKGROUND_IMAGE_REF = 0x0202
    WATERMARKS_BLOCK = 0x0203
    SHADOW_INFO_BLOCK = 0x0204
    ACTIVE_SCHEMATA_BLOCK = 0x0205
    STYLES_REGISTRY_BLOCK = 0x0206
    SCENES_BLOCK = 0x0207
    LINE_STYLES_BLOCK = 0x0208
    MODEL_PROPERTIES_BLOCK = 0x0209
    METADATA_PATH_ENTRY = 0x020A
    USE_MIPMAPS_FLAG = 0x020C
    SECTION_PLANE_NAME_SEED = 0x020D
    COMPONENT_BEHAVIOR_DEFAULTS_BLOCK = 0x020E
    DEFAULT_IMAGE_REF_STATE = 0x020F
    ENVIRONMENT_DATA_BLOCK = 0x0210
    SUN_DATA_BLOCK = 0x0213
    FACE_REVERSION_MIGRATION_FLAG = 0x0214
    LEGACY_VERSION_MARKER = 0x0063

    # Entities container
    ENTITIES = 0x1388
    VERTICES = 0x1389
    EDGES = 0x138A
    FACES = 0x138B
    COMPONENT_INSTANCES = 0x138C
    GROUPS = 0x138D
    DRAW_ELEM_REF = 0x138E
    IMAGES = 0x1390
    CURVES = 0x1396
    ARC_CURVES = 0x1397

    # Curve record sub-tags
    CURVE_RECORD = 0x4A38
    CURVE_EDGE_COUNT = 0x4A39
    CURVE_POLYGON_FLAG = 0x4A3A
    CURVE_FIRST_EDGE_ID = 0x4A3B
    CURVE_LAST_EDGE_ID = 0x4A3C

    # Arc-curve record sub-tags
    ARC_CURVE_RECORD = 0x4C2C
    ARC_SPECIFIC_PAYLOAD = 0x4C2D

    # Vertex
    VERTEX_RECORD = 0x09C4
    VERTEX_POSITION = 0x09C5

    # Entity base / ID
    ENTITY_BASE = 0x07D0
    ENTITY_MATERIAL_REF = 0x07D1
    ENTITY_LAYER_REF = 0x07D2
    ENTITY_FLAGS = 0x07D3
    ID_WRAPPER = 0x05DC
    ID_EXT_PAYLOAD = 0x05DD
    ID_VALUE = 0x05DE

    # Attribute dictionaries
    ATTR_DICTS_ROOT = 0x36B1
    ATTR_DICT_RECORD = 0x36B2
    ATTR_DICT_DATA = 0x36B3
    ATTR_DICT_NAME = 0x36B4
    ATTR_DICT_ENTRIES = 0x36B5
    ATTR_DICT_ENTRY_KEY = 0x36B6
    ATTR_ENTRY_FLAGS = 0x36B7
    ATTR_TYPED_VALUE = 0x38A4
    ATTR_TYPED_VALUE_TYPE = 0x38A7
    ATTR_TYPED_VALUE_INT = 0x38A8
    ATTR_TYPED_VALUE_F64 = 0x38A9
    ATTR_TYPED_VALUE_BOOL = 0x38AA
    ATTR_TYPED_VALUE_STRING = 0x38AD
    ATTR_TYPED_VALUE_NESTED = 0x38AE
    ATTR_DICT_HEADER = 0x36B0

    # Texture projection
    TEX_PROJ_PAIR = 0x2710
    TEX_PROJ_FRONT = 0x2711
    TEX_PROJ_BACK = 0x2712
    TEX_PROJ_PAYLOAD = 0x2713
    TEX_PROJ_ENABLED = 0x2714
    TEX_PROJ_TRANSFORM = 0x2715
    TEX_PROJ_ORIGIN = 0x2716
    TEX_PROJ_PINS = 0x2717
    TEX_PROJ_PIN = 0x2718
    TEX_PROJ_PIN_TEXTURE_POSITION = 0x2719
    TEX_PROJ_PIN_MODEL_POSITION = 0x271A

    # Edge
    EDGE_RECORD = 0x0BB8
    EDGE_START_VERTEX = 0x0BB9
    EDGE_END_VERTEX = 0x0BBA
    EDGE_CURVE_ID = 0x0BBB

    # Face
    FACE_RECORD = 0x0DAC
    FACE_PLANE = 0x0DAD
    FACE_LOOPS = 0x0DAE
    FACE_EXTRA_FLAG = 0x0DAF

    # Loop / edge-use
    LOOP_RECORD = 0x1194
    EDGE_USES = 0x1195
    EDGE_USE = 0x0FA0
    EDGE_USE_ID = 0x0FA1
    EDGE_USE_REVERSED = 0x0FA2

    # Component instance / group / image
    INSTANCE_RECORD = 0x1964
    INSTANCE_NAME = 0x1965
    INSTANCE_TRANSFORM = 0x1966
    INSTANCE_DEF_ID = 0x1967
    INSTANCE_GUID = 0x1968
    GROUP_RECORD = 0x1D4C
    IMAGE_RECORD = 0x1F40

    # Materials
    MATERIALS_CONTAINER = 0x30D4
    MATERIALS_LIST = 0x30D5
    MATERIAL_RECORD = 0x32C8
    MATERIAL_EMBEDDED = 0x32CA
    MATERIAL_TEX_PAYLOAD = 0x32CB
    MATERIAL_NAME = 0x32CC
    MATERIAL_AUX_U32 = 0x32CD

    # Layers
    LAYERS_CONTAINER = 0x3A98
    LAYER_LIST = 0x3A99
    ACTIVE_LAYER_ID = 0x3A9A
    LAYER_FOLDER_TREE = 0x3A9B
    LAYER_RECORD = 0x3C8C
    LAYER_NAME = 0x3C8D
    LAYER_VISIBLE = 0x3C8E
    LAYER_MATERIAL = 0x3C8F
    LAYER_SCENE_FLAGS = 0x3C90
    FOLDER_NODE = 0x3E80
    FOLDER_NAME = 0x3E81
    FOLDER_VISIBLE = 0x3E82
    FOLDER_CHILD_GROUPS = 0x3E83
    FOLDER_CHILD_LAYER_IDS = 0x3E84
    FOLDER_VISIBLE_ON_NEW_SCENES = 0x3E85

    # Camera
    CAMERA_RECORD = 0x34BC
    CAMERA_EYE = 0x34BD
    CAMERA_TARGET = 0x34BE
    CAMERA_UP = 0x34BF
    CAMERA_NEAR = 0x34C0
    CAMERA_FAR = 0x34C1
    CAMERA_IS_PERSPECTIVE = 0x34C2
    CAMERA_ORTHO_HEIGHT = 0x34C3
    CAMERA_FOV = 0x34C4
    CAMERA_ASPECT = 0x34C5
    CAMERA_FOV_IS_HEIGHT = 0x34C6
    CAMERA_LEGACY_FLAG = 0x34C7
    CAMERA_DESCRIPTION = 0x34C8
    CAMERA_IMAGE_WIDTH = 0x34C9
    CAMERA_IS_2D = 0x34CA
    CAMERA_2D_SCALE = 0x34CB
    CAMERA_2D_CENTER_X = 0x34CC
    CAMERA_2D_CENTER_Y = 0x34CD
    CAMERA_ALLOW_CLIPPING = 0x34CE

    # Component definitions
    DEFINITIONS_CONTAINER = 0x1770
    DEFINITIONS_LIST = 0x1771
    DEFINITION_RECORD = 0x157C
    DEFINITION_GUID = 0x157D
    DEFINITION_NAME = 0x157E
    DEFINITION_DESC = 0x157F
    DEFINITION_LOADED_FROM = 0x1580
    DEFINITION_TIMESTAMP = 0x1581
    DEFINITION_MODIFIED = 0x1582
    DEFINITION_TYPE = 0x1583
    DEFINITION_PACKED_PAYLOAD = 0x1585

    # Component behavior
    COMPONENT_BEHAVIOR_BLOCK = 0x1B58
    BEHAVIOR_SNAP_MODE = 0x1B59
    BEHAVIOR_NO_SCALE_MASK = 0x1B5A
    BEHAVIOR_SNAP_ENABLED = 0x1B5B
    BEHAVIOR_CUTS_OPENING = 0x1B5C
    BEHAVIOR_ALWAYS_FACE_CAMERA = 0x1B5D
    BEHAVIOR_SHADOWS_FACE_SUN = 0x1B5E

    # Packed payload
    PACKED_PAYLOAD_RECORD = 0x251C
    PACKED_PAYLOAD_VALUE = 0x251D
    PACKED_THUMBNAIL_RECORD = 0x251E
    PACKED_THUMBNAIL_KIND = 0x2328
    PACKED_THUMBNAIL_PATH = 0x2329
    PACKED_THUMBNAIL_DATA = 0x232A

    # Model view / sketch axes
    MODEL_VIEW_RECORD = 0x4650
    SKETCH_AXES_ORIGIN = 0x4651
    SKETCH_AXES_X_AXIS = 0x4652
    SKETCH_AXES_Y_AXIS = 0x4653
    SKETCH_AXES_Z_AXIS = 0x4654
    SKETCH_AXES_FLAGS = 0x3FF0

    # Guide lines
    GUIDE_LINES = 0x1391
    GUIDE_LINE_RECORD = 0x4269
    CONSTRUCTION_GEOMETRY_BASE = 0x4268
    GUIDE_LINE_GEOMETRY = 0x426A
    GUIDE_LINE_STIPPLE = 0x426B

    # Guide points
    GUIDE_POINTS = 0x1392
    GUIDE_POINT_RECORD = 0x426C
    GUIDE_POINT_POSITION = 0x426D
    GUIDE_POINT_REFERENCE_POSITION = 0x426E
    GUIDE_POINT_HAS_REFERENCE_POSITION = 0x426F

    # Section planes
    SECTION_PLANES = 0x1393
    SECTION_PLANE_RECORD = 0x445C
    SECTION_PLANE_PLANE = 0x445D
    SECTION_PLANE_NAME = 0x445E
    SECTION_PLANE_SYMBOL = 0x445F
    ACTIVE_SECTION_PLANE_REF = 0x1394

    # Text annotations
    TEXTS = 0x1398
    TEXT_RECORD = 0x55F0
    TEXT_VALUE = 0x55F1
    TEXT_SCREEN_X = 0x55F2
    TEXT_SCREEN_Y = 0x55F3
    TEXT_ANCHOR = 0x55F4
    TEXT_LEADER_VECTOR = 0x55F5
    TEXT_ANCHOR_IN_FRONT = 0x55F6
    TEXT_VIEW_DIRECTION = 0x55F7
    TEXT_HIDE_OUT_OF_PLANE = 0x55F8
    TEXT_FONT_REF = 0x55F9
    TEXT_LINE_WEIGHT = 0x55FA
    TEXT_LEADER_TYPE = 0x55FB
    TEXT_DISPLAY_LEADER = 0x55FC
    TEXT_ARROW_TYPE = 0x55FD
    TEXT_HIDDEN_LEADER_DIRECTION = 0x55FE

    # Dimensions
    DIMENSIONS = 0x1399
    DIMENSION_RECORD = 0x5BCC
    DIMENSION_BASE = 0x59D8
    DIMENSION_TEXT = 0x59D9
    DIMENSION_FONT_REF = 0x59DA
    DIMENSION_3D_TEXT = 0x59DB
    DIMENSION_ARROW_TYPE = 0x59DC
    DIMENSION_ANCHOR_A = 0x5BCD
    DIMENSION_ANCHOR_B = 0x5BCE
    POINT_REFERENCE = 0x5208
    DIMENSION_ANCHOR_ENABLED = 0x5209
    DIMENSION_ANCHOR_POINT = 0x520A
    DIMENSION_ANCHOR_STYLE_A = 0x520B
    DIMENSION_ANCHOR_STYLE_B = 0x520C
    DIMENSION_ANCHOR_STYLE_WRAPPER = 0x53FC
    DIMENSION_ANCHOR_STYLE_ENTITY = 0x53FD
    DIMENSION_ANCHOR_STYLE_VALUE = 0x53FE
    DIMENSION_DIRECTION = 0x5BCF
    DIMENSION_RENDER_DIR = 0x5BD0
    DIMENSION_MODE = 0x5BD1
    DIMENSION_LINE_POS = 0x5BD2
    DIMENSION_OFFSET = 0x5BD3
    DIMENSION_ALIGNMENT = 0x5BD4

    # Radial dimensions
    RADIAL_DIMENSIONS = 0x139A
    RADIAL_DIMENSION_RECORD = 0x5DC0
    RADIAL_DIMENSION_TARGET_REF = 0x5DC1
    RADIAL_DIMENSION_ARC = 0x5DC2
    RADIAL_DIMENSION_PARAMETER = 0x5DC3
    RADIAL_DIMENSION_RADIUS_RATIO = 0x5DC4
    RADIAL_DIMENSION_IS_DIAMETER = 0x5DC5

    # Openings
    OPENINGS = 0x139D
    OPENING_RECORD = 0x7530
    OPENING_ORIGIN = 0x7531
    OPENING_X_AXIS = 0x7532
    OPENING_Y_AXIS = 0x7533
    OPENING_Z_AXIS = 0x7534
    OPENING_FLAGS = 0x7535

    # Entities metadata / state
    ENTITIES_METADATA_BLOCK = 0x139B
    ENTITIES_METADATA_RECORD = 0x639F
    ENTITIES_METADATA_PAYLOAD = 0x63A0
    ENTITIES_SENTINEL = 0x139E
    COMPONENT_STATE_FLAGS = 0x139F
    DEFINITION_ENTITIES_BOUNDS = 0x13A0

    # Scenes structure
    SCENES_CONTAINER = 0x6D60
    SCENES_LIST = 0x6D61
    SCENE_RECORD = 0x7148
    SCENE_BASE = 0x6F54
    SCENE_NAME = 0x6F55
    SCENE_DESCRIPTION = 0x6F56
    SCENE_FLAGS = 0x7149
    SCENE_CAMERA_SNAPSHOT = 0x714A
    SCENE_HIDDEN_ENTITY_IDS = 0x714B
    SCENE_STYLE_REF = 0x714C
    SCENE_RENDERING_OPTIONS_SNAPSHOT = 0x714D
    SCENE_SHADOW_INFO_SNAPSHOT = 0x714E
    SCENE_AXES_SNAPSHOT = 0x714F
    SCENE_HIDDEN_LAYER_IDS = 0x7150
    SCENE_ACTIVE_SECTION_PLANE_IDS = 0x7151
    SCENE_SHOW_IN_SLIDESHOW = 0x7152
    SCENE_RESERVED_STRING = 0x7153
    SCENE_TRANSITION_TIME = 0x7154
    SCENE_DELAY_TIME = 0x7155
    SCENE_BACKGROUND_IMAGE_REF = 0x7156
    SCENE_USE_THUMBNAIL = 0x7157
    SCENE_THUMBNAIL_IMAGE = 0x7158
    SCENE_HIDDEN_LAYER_FOLDER_IDS = 0x7159
    SCENE_ENVIRONMENT_REF = 0x715A
    SCENE_ENVIRONMENT_SETTINGS = 0x715B
    SCENE_FOREGROUND_IMAGE_IDS = 0x715C

    # Shadow info
    SHADOW_INFO_RECORD = 0x6590
    SHADOW_INFO_TIME = 0x6591
    SHADOW_INFO_DAYLIGHT_SAVINGS = 0x6592
    SHADOW_INFO_CITY = 0x6593
    SHADOW_INFO_COUNTRY = 0x6594
    SHADOW_INFO_LONGITUDE = 0x6595
    SHADOW_INFO_LATITUDE = 0x6596
    SHADOW_INFO_TIMEZONE_OFFSET = 0x6597
    SHADOW_INFO_NORTH_DIRECTION = 0x6598
    SHADOW_INFO_DISPLAY_SHADOWS = 0x6599
    SHADOW_INFO_DISPLAY_NORTH = 0x659A
    SHADOW_INFO_DISPLAY_ON_ALL_FACES = 0x659B
    SHADOW_INFO_DISPLAY_ON_GROUND = 0x659C
    SHADOW_INFO_EDGES_CAST_SHADOWS = 0x659D
    SHADOW_INFO_LIGHT = 0x659E
    SHADOW_INFO_DARK = 0x659F
    SHADOW_INFO_USE_SUN_FOR_ALL_SHADING = 0x65A0

    # Watermarks
    WATERMARK_MANAGER_RECORD = 0x2CEC
    WATERMARK_LIST = 0x2CED
    WATERMARK_SERIALIZED_COUNT = 0x2CEE
    WATERMARK_RECORD = 0x2EE0
    WATERMARK_NAME = 0x2EE1
    WATERMARK_FILE_INFO_FOUND = 0x2EE2
    WATERMARK_FILE_TIME = 0x2EE3
    WATERMARK_FILE_NAME = 0x2EE4
    WATERMARK_POSITION = 0x2EE5
    WATERMARK_IMAGE = 0x2EE6
    WATERMARK_TILED = 0x2EE7
    WATERMARK_STRETCHED = 0x2EE8
    WATERMARK_MAINTAIN_ASPECT = 0x2EE9
    WATERMARK_BACKGROUND = 0x2EEA
    WATERMARK_SCALE = 0x2EEB
    WATERMARK_INTENSITY_ALPHA = 0x2EEC
    WATERMARK_OPACITY = 0x2EED
    WATERMARK_FITTING_TYPE = 0x2EEE
    WATERMARK_STRETCH_TYPE = 0x2EEF

    # Inline/external CDib payloads.
    DIB_RECORD = 0x2328
    DIB_FILE_TYPE = 0x2329
    DIB_EXTERNAL_PATH = 0x232A
    DIB_BINARY = 0x232B
    DIB_JPEG_QUALITY = 0x232C

    # Match-photo/page background images.
    BACKGROUND_IMAGE_RECORD = 0x2904
    BACKGROUND_IMAGE_REFERENCE = 0x2905
    BACKGROUND_IMAGE_VISIBLE = 0x2906
    BACKGROUND_IMAGE_OPACITY = 0x2907
    BACKGROUND_IMAGE_GRIP_POINTS = 0x2908
    BACKGROUND_IMAGE_PRINCIPAL_DELTA = 0x2909
    BACKGROUND_IMAGE_RADIAL_DISTORTION = 0x290A
    BACKGROUND_IMAGE_SOURCE = 0x290B
    IMAGE_REFERENCE_RECORD = 0x2AF8
    IMAGE_REFERENCE_PATH = 0x2AF9
    IMAGE_REFERENCE_STATE = 0x2AFA
    IMAGE_REFERENCE_DIB = 0x2AFB
    IMAGE_REFERENCE_WIDTH = 0x2AFC
    IMAGE_REFERENCE_HEIGHT = 0x2AFD
    IMAGE_REFERENCE_FILE_SIZE = 0x2AFE
    IMAGE_REFERENCE_TIMESTAMP = 0x2AFF

    # Fonts
    FONTS_CONTAINER = 0x4E20
    FONTS_LIST = 0x4E21
    FONT_RECORD = 0x5014
    FONT_FACE_NAME = 0x5015
    FONT_BOLD_FLAG = 0x5016
    FONT_ITALIC_FLAG = 0x5017
    FONT_POINT_SIZE = 0x5018
    FONT_USE_WORLD_SIZE = 0x5019
    FONT_WORLD_SIZE = 0x501A

    # Text style
    TEXT_STYLE_RECORD = 0x57E4
    TEXT_STYLE_FONT_REF = 0x57E5
    TEXT_STYLE_SCREEN_FONT_REF = 0x57E6
    TEXT_STYLE_ARROW_TYPE = 0x57E7
    TEXT_STYLE_LINE_WEIGHT = 0x57E8
    TEXT_STYLE_HIDE_OUT_OF_PLANE = 0x57E9
    TEXT_STYLE_LEADER_TYPE = 0x57EA
    TEXT_STYLE_DISPLAY_LEADER = 0x57EB
    TEXT_STYLE_COLOR = 0x57EC
    TEXT_STYLE_SCREEN_COLOR = 0x57ED

    # Dimension style
    DIMENSION_STYLE_RECORD = 0x5FB4
    DIMENSION_STYLE_FONT_REF = 0x5FB5
    DIMENSION_STYLE_3D_TEXT = 0x5FB6
    DIMENSION_STYLE_ALWAYS_READABLE = 0x5FB7
    DIMENSION_STYLE_EXTENSION_OFFSET = 0x5FB8
    DIMENSION_STYLE_EXTENSION_OVERSHOOT = 0x5FB9
    DIMENSION_STYLE_LINE_WEIGHT = 0x5FBA
    DIMENSION_STYLE_ARROW_TYPE = 0x5FBB
    DIMENSION_STYLE_ARROW_SIZE = 0x5FBC
    DIMENSION_STYLE_HIGHLIGHT_NON_ASSOC = 0x5FBD
    DIMENSION_STYLE_HIGHLIGHT_NON_ASSOC_COLOR = 0x5FBE
    DIMENSION_STYLE_SHOW_RADIAL_PREFIX = 0x5FBF
    DIMENSION_STYLE_HIDE_OUT_OF_PLANE = 0x5FC0
    DIMENSION_STYLE_HIDE_OUT_OF_PLANE_VALUE = 0x5FC1
    DIMENSION_STYLE_HIDE_SMALL = 0x5FC2
    DIMENSION_STYLE_HIDE_SMALL_VALUE = 0x5FC3
    DIMENSION_STYLE_COLOR = 0x5FC4
    DIMENSION_STYLE_TEXT_COLOR = 0x5FC5
    DIMENSION_STYLE_TEXT_POSITION = 0x5FC6

    # Line styles
    LINE_STYLES_RECORD = 0x4074
    LINE_STYLE_LIST = 0x4075
    LINE_STYLE_RECORD = 0x4076
    LINE_STYLE_NAME = 0x4077
    LINE_STYLE_DASH_PATTERN = 0x4078
    LINE_STYLE_STIPPLE_SCALE = 0x4079
    LINE_STYLE_LINE_WIDTH = 0x407A
    LINE_STYLE_COLOR = 0x407B
    LINE_STYLE_MUTABILITY = 0x407C

    # Options manager
    OPTIONS_MANAGER_RECORD = 0x61A8
    OPTIONS_PROVIDER_LIST = 0x61A9
    OPTIONS_PROVIDER_RECORD = 0x61AA
    OPTIONS_PROVIDER_NAME = 0x61AB
    OPTIONS_KEY_TABLE = 0x61AC
    OPTIONS_KEY_NAME = 0x61AD

    # Styles registry
    STYLES_REGISTRY = 0x6978
    STYLE_LIST = 0x6979
    ACTIVE_STYLE_REF = 0x697A
    INLINE_STYLE_OVERRIDE = 0x697B
    STYLE_MANAGER_DIRTY = 0x697C
    STYLE_DESCRIPTOR = 0x6B6C
    STYLE_GUID = 0x6B6D
    STYLE_DISPLAY_NAME = 0x6B6E
    STYLE_FILE_NAME = 0x6B6F
    STYLE_WATERMARK_REFS = 0x6B70

    # Active schemata
    ACTIVE_SCHEMA_ZIP_RECORD = 0x6784

    # Environment data
    ENVIRONMENT_DATA_RECORD = 0x7918
    ENVIRONMENT_SELECTED_RECORD = 0x7919
    ENVIRONMENT_ENTRY = 0x7B0C
    ENVIRONMENT_NAME = 0x7B0D
    ENVIRONMENT_THUMBNAIL_REF = 0x7B0E
    ENVIRONMENT_THUMBNAIL_PATH = 0x2134

    # Sun data
    SUN_DATA_RECORD = 0x7D64
    SUN_DATA_EXTRA = 0x7D65

    # Rendering options
    RENDERING_OPTIONS_RECORD = 0x733C
    REND_OPT_RENDER_MODE = 0x733D
    REND_OPT_MODEL_TRANSPARENCY = 0x733E
    REND_OPT_MATERIAL_TRANSPARENCY = 0x733F
    REND_OPT_TEXTURE = 0x7340
    REND_OPT_EDGE_DISPLAY_MODE = 0x7341
    REND_OPT_EDGE_TYPE = 0x7342
    REND_OPT_DISPLAY_SKETCH_AXES = 0x7343
    REND_OPT_DISPLAY_TEXT = 0x7344
    REND_OPT_DISPLAY_DIMS = 0x7345
    REND_OPT_HIDE_CONSTRUCTION_GEOMETRY = 0x7346
    REND_OPT_DISPLAY_COLOR_BY_LAYER = 0x7347
    REND_OPT_EDGE_COLOR_MODE = 0x7348
    REND_OPT_DISPLAY_INSTANCE_AXES = 0x7349
    REND_OPT_FACE_COLOR_MODE = 0x734A
    REND_OPT_JITTER_EDGES = 0x734B
    REND_OPT_LINE_STYLE_EDGES = 0x734C
    REND_OPT_EXTEND_LINES = 0x734D
    REND_OPT_LINE_EXTENSION = 0x734E
    REND_OPT_DRAW_SILHOUETTES = 0x734F
    REND_OPT_SILHOUETTE_WIDTH = 0x7350
    REND_OPT_DRAW_DEPTH_QUE = 0x7351
    REND_OPT_DEPTH_QUE_WIDTH = 0x7352
    REND_OPT_DRAW_LINE_ENDS = 0x7353
    REND_OPT_LINE_END_WIDTH = 0x7354
    REND_OPT_DRAW_PROFILES_ONLY = 0x7355
    REND_OPT_DRAW_BACK_EDGES = 0x7356
    REND_OPT_BACKGROUND_COLOR = 0x7357
    REND_OPT_FOREGROUND_COLOR = 0x7358
    REND_OPT_HIGHLIGHT_COLOR = 0x7359
    REND_OPT_LOCKED_COLOR = 0x735A
    REND_OPT_CONSTRUCTION_COLOR = 0x735B
    REND_OPT_FACE_FRONT_COLOR = 0x735C
    REND_OPT_FACE_BACK_COLOR = 0x735D
    REND_OPT_DISPLAY_WATERMARKS = 0x735E
    REND_OPT_DISPLAY_FOG = 0x735F
    REND_OPT_FOG_COLOR = 0x7360
    REND_OPT_FOG_USE_BACKGROUND_COLOR = 0x7361
    REND_OPT_FOG_START_DIST = 0x7362
    REND_OPT_FOG_END_DIST = 0x7363
    REND_OPT_FOG_HINT_MODE = 0x7364
    REND_OPT_SKY_COLOR = 0x7365
    REND_OPT_HORIZON_COLOR = 0x7366
    REND_OPT_GROUND_COLOR = 0x7367
    REND_OPT_DRAW_HORIZON = 0x7368
    REND_OPT_DRAW_GROUND = 0x7369
    REND_OPT_DRAW_UNDERGROUND = 0x736A
    REND_OPT_GROUND_TRANSPARENCY = 0x736B
    REND_OPT_INACTIVE_FADE = 0x736C
    REND_OPT_INSTANCE_FADE = 0x736D
    REND_OPT_INACTIVE_HIDDEN = 0x736E
    REND_OPT_INSTANCE_HIDDEN = 0x736F
    REND_OPT_SECTION_ACTIVE_COLOR = 0x7370
    REND_OPT_SECTION_INACTIVE_COLOR = 0x7371
    REND_OPT_SECTION_DEFAULT_CUT_COLOR = 0x7372
    REND_OPT_SECTION_DEFAULT_FILL_COLOR = 0x7373
    REND_OPT_SECTION_CUT_WIDTH = 0x7374
    REND_OPT_SECTION_DISPLAY_MODE = 0x7375
    REND_OPT_SECTION_CUT_FILLED = 0x7376
    REND_OPT_TRANSPARENCY_SORT = 0x7377
    REND_OPT_XRAY_OPACITY = 0x7378
    REND_OPT_DRAW_SOFT_EDGES = 0x7379
    REND_OPT_SOFT_EDGE_LIMIT = 0x737A
    REND_OPT_DRAW_SMOOTH_EDGES = 0x737B
    REND_OPT_PHOTOMATCH_DRAW_BG = 0x737C
    REND_OPT_PHOTOMATCH_BG_OPACITY = 0x737D
    REND_OPT_PHOTOMATCH_DRAW_OVERLAY = 0x737E
    REND_OPT_PHOTOMATCH_OVERLAY_OPACITY = 0x737F
    REND_OPT_DRAW_HIDDEN_GEOMETRY = 0x7380
    REND_OPT_DRAW_HIDDEN_OBJECTS = 0x7381
    REND_OPT_HIDE_CUSTOM_CONTROL_POINTS = 0x7382
    REND_OPT_AMBIENT_OCCLUSION = 0x7383
    REND_OPT_AO_DISTANCE = 0x7385
    REND_OPT_AO_INTENSITY = 0x7386
    REND_OPT_AO_MULTIPLIER = 0x7389
    REND_OPT_AO_COLOR = 0x738A
    REND_OPT_AO_COLOR_ENABLED = 0x738B

    # Model ID counter sub-tags
    MODEL_ID_COUNTER_VALUE = 0x03E8
    MODEL_ID_COUNTER_EXTRA = 0x03E9


# Known top-level children of the model root (0x01F4)
KNOWN_ROOT_CHILDREN = frozenset(
    {
        0x01F5,
        0x01F6,
        0x01F7,
        0x01F8,
        0x01F9,
        0x01FA,
        0x01FB,
        0x01FC,
        0x01FD,
        0x01FE,
        0x01FF,
        0x0200,
        0x0201,
        0x0203,
        0x0204,
        0x0205,
        0x0206,
        0x0207,
        0x0208,
        0x0209,
        0x020A,
        0x020C,
        0x020D,
        0x020E,
        0x020F,
        0x0210,
        0x0213,
        0x0214,
        0x0063,
    }
)

# Pseudo-tags (not real TLV tags, safe to skip during scanning)
PSEUDO_TAGS = frozenset({0x0000, 0x8000, 0xBFF0})

# -
# Record I/O
# -


def read_record(data: bytes, offset: int) -> Tuple[int, bytes, int]:
    """
    Read one TLV record at *offset*.

    Parameters
    ----------
    data : bytes
        Byte buffer containing TLV records.
    offset : int
        Offset of the record header.

    Returns
    -------
    tuple
        ``(tag, payload, next_offset)``.

    Raises
    ------
    ValueError
        If the header or payload is truncated.
    """
    check_cancelled()
    if offset + HEADER_SIZE > len(data):
        raise ValueError(f"Truncated header at offset {offset} (need {HEADER_SIZE} bytes, have {len(data) - offset})")
    tag = struct.unpack_from("<H", data, offset)[0]
    length = struct.unpack_from("<I", data, offset + 2)[0]
    payload_start = offset + HEADER_SIZE
    payload_end = payload_start + length
    if payload_end > len(data):
        raise ValueError(
            f"Truncated payload at offset {offset}: "
            f"tag=0x{tag:04X} length={length} "
            f"available={len(data) - payload_start}"
        )
    return tag, data[payload_start:payload_end], payload_end


def iter_records(data: bytes) -> Iterator[Tuple[int, bytes]]:
    """
    Yield (tag, payload) pairs for every TLV record in *data*.

    Raises when a record header or payload is truncated. Structural parsers use
    this strict iterator so corrupt nested containers cannot masquerade as valid
    records with missing optional fields.

    Parameters
    ----------
    data : bytes
        Byte buffer containing zero or more TLV records.

    Returns
    -------
    iterator of tuple
        ``(tag, payload)`` pairs.
    """
    offset = 0
    while offset < len(data):
        tag, payload, next_offset = read_record(data, offset)
        yield tag, payload
        offset = next_offset


def iter_record_prefix(data: bytes) -> Iterator[Tuple[int, bytes]]:
    """Yield the complete TLV prefix before malformed trailing data.

    This recovery-oriented iterator is intentionally separate from
    :func:`iter_records`. It is suitable for diagnostics and mutation analysis,
    never for constructing a model that will be returned as successfully parsed.
    """
    offset = 0
    while offset < len(data):
        try:
            tag, payload, next_offset = read_record(data, offset)
        except ValueError:
            return
        yield tag, payload
        offset = next_offset


# -
# Lookup helpers
# -


def find_child(data: bytes, target_tag: int) -> Optional[bytes]:
    """Return the first child payload whose tag matches *target_tag*, or None.

    Parameters
    ----------
    data : bytes
        Parent TLV payload containing child records.
    target_tag : int
        Tag value to locate.

    Returns
    -------
    bytes or None
        Matching child payload, or ``None`` when absent.
    """
    for tag, payload in iter_records(data):
        if tag == target_tag:
            return payload
    return None


def find_all_children(data: bytes, target_tag: int) -> list[bytes]:
    """Return all child payloads whose tag matches *target_tag*.

    Parameters
    ----------
    data : bytes
        Raw TLV payload to search.
    target_tag : int
        Tag value to match.

    Returns
    -------
    list of bytes
        All matching child payloads (may be empty).
    """
    return [payload for tag, payload in iter_records(data) if tag == target_tag]


def index_children(data: bytes) -> dict[int, bytes]:
    """Index the first child payload for every tag in one pass.

    This is equivalent to calling :func:`find_child` for several distinct
    tags, but avoids repeatedly scanning large entity records. Duplicate tags
    intentionally retain the first payload to preserve ``find_child``
    semantics.

    Parameters
    ----------
    data : bytes
        Parent TLV payload containing child records.

    Returns
    -------
    dict
        Mapping of integer tag values to their first payload.
    """
    children: dict[int, bytes] = {}
    for tag, payload in iter_records(data):
        children.setdefault(tag, payload)
    return children


# -
# Payload decoders
# -


def read_compact_int(payload: bytes) -> int:
    """Decode a variable-length little-endian unsigned integer (1-4 bytes).

    SketchUp's compact-int encoding uses 1 to 4 bytes depending on the
    magnitude of the value.  Any payload length up to 4 bytes is accepted.

    Parameters
    ----------
    payload : bytes
        Raw bytes containing the encoded integer (little-endian).

    Returns
    -------
    int
        The decoded non-negative integer.  Returns 0 for an empty payload.
    """
    if not payload:
        return 0
    if len(payload) > 4:
        raise ValueError(f"Compact integer payload must contain at most 4 bytes, got {len(payload)}")
    return int.from_bytes(payload, "little")


def read_bool(payload: bytes) -> bool:
    """Decode a single-byte boolean value.

    Parameters
    ----------
    payload : bytes
        Raw bytes; the first byte is interpreted as a boolean.

    Returns
    -------
    bool
        ``True`` if the first byte is non-zero, ``False`` for an empty
        payload or a zero byte.
    """
    return bool(payload[0]) if payload else False


def read_u32_le(payload: bytes) -> int:
    """Decode a little-endian 32-bit unsigned integer.

    Accepts payloads shorter than 4 bytes (zero-extended).

    Parameters
    ----------
    payload : bytes
        Raw bytes containing the encoded integer (little-endian).

    Returns
    -------
    int
        The decoded unsigned 32-bit integer.
    """
    if len(payload) < 4:
        return int.from_bytes(payload, "little")
    return int(struct.unpack_from("<I", payload)[0])


def read_f64_le(payload: bytes) -> float:
    """Decode a little-endian 64-bit IEEE 754 double.

    Parameters
    ----------
    payload : bytes
        Raw bytes (must contain at least 8 bytes).

    Returns
    -------
    float
        The decoded floating-point value.
    """
    return float(struct.unpack_from("<d", payload)[0])


def read_vec3(payload: bytes) -> Tuple[float, float, float]:
    """Decode a 3-D vector (3 x little-endian f64).

    Parameters
    ----------
    payload : bytes
        Raw bytes (must contain at least 24 bytes).

    Returns
    -------
    tuple of float
        ``(x, y, z)`` components.
    """
    return struct.unpack_from("<3d", payload)


def read_vec4(payload: bytes) -> Tuple[float, float, float, float]:
    """Decode a 4-component vector (4 x little-endian f64).

    Used for plane equations ``(a, b, c, d)`` where ``ax + by + cz + d = 0``.

    Parameters
    ----------
    payload : bytes
        Raw bytes (must contain at least 32 bytes).

    Returns
    -------
    tuple of float
        ``(a, b, c, d)`` components.
    """
    return struct.unpack_from("<4d", payload)


def read_transform13(payload: bytes) -> list[float]:
    """Decode a SketchUp transformation (13 x little-endian f64).

    The 13-value layout matches the documented ``SUTransformation`` storage:
    12 rotation/scale matrix values (row-major 3x4) followed by a
    perspective component.

    Parameters
    ----------
    payload : bytes
        Raw bytes (must contain at least 104 bytes).

    Returns
    -------
    list of float
        13 transformation values in SUTransformation order.
    """
    return list(struct.unpack_from("<13d", payload))


def read_utf8(payload: bytes) -> str:
    """Decode a UTF-8 string payload.

    Malformed byte sequences are replaced with the Unicode replacement
    character (U+FFFD) rather than raising.

    Parameters
    ----------
    payload : bytes
        Raw UTF-8 encoded bytes.

    Returns
    -------
    str
        The decoded string.
    """
    return payload.decode("utf-8", errors="replace")


def read_guid(payload: bytes) -> bytes:
    """
    Return first 16 bytes as a raw GUID blob.

    The raw bytes can be converted to a UUID string using :func:`format_guid`.

    Parameters
    ----------
    payload : bytes
        Raw GUID payload.

    Returns
    -------
    bytes
        Up to the first 16 bytes from *payload*.
    """
    return payload[:16]


def format_guid(raw_bytes: bytes) -> str:
    """
    Convert raw 16-byte GUID to standard UUID string format.

    SketchUp uses the standard Windows GUID format. The first 8 bytes
    (data1, data2, data3) are stored in little-endian byte order on disk
    and must be byte-swapped for display. The last 8 bytes (data4) are
    stored as-is.

    This matches the standard GUID layout and the Windows `ToString` format.

    Returns a UUID string in the standard 8-4-4-4-12 format (e.g.,
    "550e8400-eb93-47d3-a957-1309ee55672b").

    Parameters
    ----------
    raw_bytes : bytes
        Exactly 16 bytes representing a GUID.

    Returns
    -------
    str
        UUID string in standard format.
    """
    if len(raw_bytes) < 16:
        raw_bytes = raw_bytes + b"\x00" * (16 - len(raw_bytes))

    # Standard GUID layout (Windows/COM style):
    # - data1 (bytes 0-3): u32 stored little-endian on disk
    # - data2 (bytes 4-5): u16 stored little-endian on disk
    # - data3 (bytes 6-7): u16 stored little-endian on disk
    # - data4 (bytes 8-15): 8 bytes stored as-is
    data1 = struct.unpack("<I", raw_bytes[0:4])[0]
    data2 = struct.unpack("<H", raw_bytes[4:6])[0]
    data3 = struct.unpack("<H", raw_bytes[6:8])[0]
    data4 = raw_bytes[8:16]

    return (
        f"{data1:08x}-"
        f"{data2:04x}-"
        f"{data3:04x}-"
        f"{data4[0]:02x}{data4[1]:02x}-"
        f"{data4[2]:02x}{data4[3]:02x}{data4[4]:02x}{data4[5]:02x}{data4[6]:02x}{data4[7]:02x}"
    )


# -
# ID reader (entity base -> id_wrapper -> id_value)
# -


def read_entity_id(entity_base_payload: bytes) -> int:
    """Extract the entity ID from an entity-base (0x07D0) payload.

    Navigates the TLV hierarchy ``ENTITY_BASE -> ID_WRAPPER -> ID_VALUE``
    and returns the decoded compact integer.

    Parameters
    ----------
    entity_base_payload : bytes
        Raw payload of the ENTITY_BASE (0x07D0) TLV record.

    Returns
    -------
    int
        The entity ID, or 0 if the ID cannot be found.
    """
    id_wrapper = find_child(entity_base_payload, TlvTag.ID_WRAPPER)
    if not id_wrapper:
        return 0
    id_val = find_child(id_wrapper, TlvTag.ID_VALUE)
    if not id_val:
        return 0
    return read_compact_int(id_val)


def read_id_from_wrapper(wrapper_payload: bytes) -> int:
    """Extract the ID from a bare id-wrapper (0x05DC) payload.

    This is a simplified path used when the ID wrapper is the direct
    parent (not nested inside an ENTITY_BASE).

    Parameters
    ----------
    wrapper_payload : bytes
        Raw payload of the ID_WRAPPER (0x05DC) TLV record.

    Returns
    -------
    int
        The decoded ID, or 0 if not found.
    """
    id_val = find_child(wrapper_payload, TlvTag.ID_VALUE)
    return read_compact_int(id_val) if id_val else 0


# -
# Model-root locator
# -


def find_model_root(data: bytes) -> int:
    """
    Return the byte offset of the 0x01F4 root TLV record in model.dat.

    In practice the root record starts at offset 0 and spans the entire
    model.dat payload.  This function verifies that assumption and falls back
    to a short scan if the file starts differently.

    Parameters
    ----------
    data : bytes
        Raw ``model.dat`` byte stream.

    Returns
    -------
    int
        Offset of the ``MODEL_ROOT`` record.

    Raises
    ------
    ValueError
        If no plausible model root can be found.
    """
    data_len = len(data)

    def _is_valid_root(offset: int) -> bool:
        if offset + HEADER_SIZE > data_len:
            return False
        if struct.unpack_from("<H", data, offset)[0] != TlvTag.MODEL_ROOT:
            return False
        length = struct.unpack_from("<I", data, offset + 2)[0]
        if offset + HEADER_SIZE + length > data_len:
            return False
        if length < 100:
            return False
        # First child of root must carry a known top-level tag
        payload_start = offset + HEADER_SIZE
        first_child_tag = struct.unpack_from("<H", data, payload_start)[0]
        return first_child_tag in KNOWN_ROOT_CHILDREN

    # Fast path: root at offset 0 (observed in all sample files)
    if _is_valid_root(0):
        return 0

    # Fallback: scan first 8 KB
    search_limit = min(data_len - HEADER_SIZE, 8192)
    for offset in range(1, search_limit):
        if _is_valid_root(offset):
            return offset

    raise ValueError(
        f"Could not locate model root (0x01F4) in model.dat (searched first {min(data_len, 8192)} of {data_len} bytes)"
    )
