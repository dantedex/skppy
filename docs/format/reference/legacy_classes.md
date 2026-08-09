# Legacy Class Catalog

Class names and schemas below are values recorded in controlled files. They are
wire identifiers, not Python implementation names. Public mappings refer to
the data returned by `skppy`.

## Class families

| Wire classes | Public mapping | Key role |
| --- | --- | --- |
| `CVertex`, `CEdge`, `CEdgeUse`, `CLoop`, `CFace` | Geometry classes in `Entities` | Shared topology and directed face boundaries |
| `CCurve`, `CArcCurve` | `Curve`, `ArcCurve` | Ordered edge ownership and circular parameters |
| `CComponentDefinition`, `CComponentInstance`, `CGroup`, `CImage` | Component/entity classes | Reusable geometry and placement |
| `CMaterial`, `CTexture`, `CDib` | `Material`, `Texture` | Appearance, physical scale, and image bytes |
| `CLayer`, `CLayerGroup` | `Layer`, `LayerFolder` | Visibility and ownership |
| `CConstructionPoint`, `CConstructionLine`, `CSectionPlane` | Construction classes | Guides and sections |
| `CCamera`, `CSketchUpPage`, `CViewPage` | `Camera`, `Scene` | View and saved-page state |
| `CRenderingOptions`, `CShadowInfo`, `CSketchCS` | Model metadata | Display, geolocation, and axes |
| `CText`, `CDimensionLinear`, `CDimensionRadial`, `CSkFont` | Annotation classes | Text, anchors, dimensions, and fonts |
| `CAttributeNamed`, `CRelationshipMap` | Dictionaries and relationships | Typed metadata and graph links |
| Style, line-style, watermark managers | Shared style classes | Named presentation resources |

Manager objects normally collapse into their public collections; they are not
duplicated as model objects.

## SketchUp 8 version map

| # | Class | Schema | # | Class | Schema |
| ---: | --- | ---: | ---: | --- | ---: |
| 1 | `CArcCurve` | 1 | 29 | `CImage` | 1 |
| 2 | `CAttribute` | 0 | 30 | `CLayer` | 2 |
| 3 | `CAttributeContainer` | 0 | 31 | `CLayerManager` | 4 |
| 4 | `CAttributeNamed` | 1 | 32 | `CLoop` | 1 |
| 5 | `CBackgroundImage` | 10 | 33 | `CMaterial` | 12 |
| 6 | `CCamera` | 5 | 34 | `CMaterialManager` | 4 |
| 7 | `CComponent` | 11 | 35 | `CPageList` | 1 |
| 8 | `CComponentBehavior` | 5 | 36 | `CPolyline3d` | 0 |
| 9 | `CComponentDefinition` | 10 | 37 | `CRelationship` | 0 |
| 10 | `CComponentInstance` | 4 | 38 | `CRelationshipMap` | 0 |
| 11 | `CConstructionGeometry` | 0 | 39 | `CRenderingOptions` | 36 |
| 12 | `CConstructionLine` | 1 | 40 | `CSectionPlane` | 2 |
| 13 | `CConstructionPoint` | 0 | 41 | `CShadowInfo` | 7 |
| 14 | `CCurve` | 4 | 42 | `CSkFont` | 1 |
| 15 | `CDefinitionList` | 0 | 43 | `CSketchCS` | 0 |
| 16 | `CDib` | 3 | 44 | `CSketchUpModel` | 22 |
| 17 | `CDimension` | 1 | 45 | `CSketchUpPage` | 1 |
| 18 | `CDimensionLinear` | 6 | 46 | `CSkpStyle` | 1 |
| 19 | `CDimensionRadial` | 2 | 47 | `CSkpStyleManager` | 2 |
| 20 | `CDimensionStyle` | 4 | 48 | `CText` | 9 |
| 21 | `CDrawingElement` | 9 | 49 | `CTextStyle` | 5 |
| 22 | `CEdge` | 2 | 50 | `CTexture` | 6 |
| 23 | `CEdgeUse` | 1 | 51 | `CThumbnail` | 1 |
| 24 | `CEntity` | 3 | 52 | `CVertex` | 0 |
| 25 | `CFace` | 3 | 53 | `CViewPage` | 12 |
| 26 | `CFaceTextureCoords` | 4 | 54 | `CWatermark` | 1 |
| 27 | `CFontManager` | 0 | 55 | `CWatermarkManager` | 2 |
| 28 | `CGroup` | 1 | 56 | `End-Of-Version-Map` | 0 |

## Schema differences, SketchUp 3–8

A dash means that the class is absent from the target's version map.

| Class | V3 | V4 | V5 | V6 | V7 | V8 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `CAttribute` | - | 0 | 0 | 0 | 0 | 0 |
| `CAttributeContainer` | - | 0 | 0 | 0 | 0 | 0 |
| `CAttributeNamed` | - | 0 | 0 | 0 | 1 | 1 |
| `CBackgroundImage` | - | - | - | 1 | 9 | 10 |
| `CCamera` | - | 4 | 4 | 5 | 5 | 5 |
| `CComponentBehavior` | 3 | 4 | 4 | 4 | 5 | 5 |
| `CComponentInstance` | 3 | 3 | 4 | 4 | 4 | 4 |
| `CConstructionLine` | 0 | 1 | 1 | 1 | 1 | 1 |
| `CCurve` | 3 | 4 | 4 | 4 | 4 | 4 |
| `CDib` | 2 | 2 | 2 | 3 | 3 | 3 |
| `CDimension` | 0 | 0 | 0 | 1 | 1 | 1 |
| `CDimensionLinear` | 4 | 4 | 4 | 6 | 6 | 6 |
| `CDrawingElement` | 8 | 8 | 9 | 9 | 9 | 9 |
| `CEntity` | 2 | 3 | 3 | 3 | 3 | 3 |
| `CFaceTextureCoords` | - | 4 | 4 | 4 | 4 | 4 |
| `CLayer` | 1 | 2 | 2 | 2 | 2 | 2 |
| `CPageList` | - | 1 | 1 | 1 | 1 | 1 |
| `CRenderingOptions` | 22 | 25 | 28 | 32 | 35 | 36 |
| `CSkFont` | 0 | 0 | 0 | 1 | 1 | 1 |
| `CSketchUpModel` | 10 | 12 | 12 | 18 | 22 | 22 |
| `CSkpStyle` | - | - | - | 1 | 1 | 1 |
| `CSkpStyleManager` | - | - | - | 2 | 2 | 2 |
| `CTextStyle` | 4 | 4 | 4 | 5 | 5 | 5 |
| `CTexture` | 4 | 4 | 4 | 6 | 6 | 6 |
| `CThumbnail` | 0 | 1 | 1 | 1 | 1 | 1 |
| `CViewPage` | 6 | 9 | 9 | 11 | 11 | 12 |
| `CWatermarkManager` | - | - | - | 2 | 2 | 2 |

## Explicit schema boundaries

Version-aware readers use the per-file map. Classes with a single confirmed
layout accept only the schemas below and fail before consuming an unknown body.

| Class | Accepted schemas |
| --- | --- |
| `CBackgroundImage` | 10 |
| `CComponent` | 11 |
| `CComponentDefinition` | 10, 11 |
| `CComponentInstance` | 4, 6 |
| `CConstructionGeometry` | 0 |
| `CDefinitionList` | 0 |
| `CDimension` | 1 |
| `CDimensionLinear` | 6 |
| `CDimensionRadial` | 2 |
| `CFontManager` | 0 |
| `CPageList` | 1 |
| `CPolyline3d` | 0 |
| `CRelationshipMap` | 0 |
| `CSkpStyleManager` | 2 |
| `CText` | 9 |
| `CThumbnail` | 1 |
| `CWatermark` | 1 |
| `CWatermarkManager` | 2 |

Some newer applications write a later class tag while down-saving an older
body. The archive tag still participates in object identity, but the file's
version map selects the body layout. Confirmed target-specific exceptions are
documented in [field layouts](legacy_fields.md).
