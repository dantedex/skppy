# Changelog

Notable user-facing changes are recorded here. Versions follow Git tags and
the project uses semantic versioning while the public API remains pre-1.0.

## Unreleased

### Added

- Import opt-in Enscape PBR metadata from standalone SKM packages and modern
  model materials, including metallic, roughness, specular, IOR, emission,
  bump, normal, displacement, map brightness, and map inversion values.
- Build Blender Principled material nodes for embedded metallic, roughness,
  normal, bump, and displacement maps while preserving missing external map
  references as material custom properties.

### Changed

- Import Enscape texture tint and image fade, resolve `Source=SKETCHUP` from
  the owning material even when its renderer filename is stale, and convert
  material colors to Blender's linear color space. Report unsupported diffuse
  node graphs during export instead of silently dropping their appearance.
- Prefer valid Enscape metadata over V-Ray when both describe the same material;
  malformed Enscape metadata still permits the V-Ray fallback.
- Import Enscape diffuse color, opacity, and embedded diffuse textures. Keep
  the SketchUp texture when the renderer's replacement image is unavailable.
- Decode Enscape material attributes in legacy SKP files as well as modern
  SKP and SKM packages, respecting the configured XML size budget and reusing
  only each material's own embedded image for matching map references.
- Apply Enscape diffuse texture brightness and inversion in Blender while
  keeping image alpha separate and multiplying it by material opacity.
- Broaden the Blender `Use V-Ray Materials` option to `Use Render Materials`;
  the compatible `import_vray_materials` property now enables both V-Ray and
  Enscape metadata.

### Fixed

- Keep Blender imports isolated from existing materials and meshes; clean up
  newly created data-blocks after failed builds.
- Preserve hard source edges and smooth generated triangulation diagonals
  consistently across face modes (GitHub #1).
- Keep packed textures backed by persistent content-addressed files so standard
  FBX and glTF exporters retain their image resources (GitHub #2).
- Resolve renderer maps by path and material scope, reject ambiguous fallback
  names, and generate UVs for materials without a base-color texture.
- Preserve roughness when optional V-Ray values are absent, and reject invalid
  inner loops instead of silently filling openings.
- Reject duplicate material names and unsupported renderer export properties;
  write completed models through atomic destination replacement.
- Enforce configurable resource byte budgets before ZIP extraction and check
  cancellation between read chunks, including standalone material imports.

- Build versioned documentation for release tags without starting a duplicate
  GitHub Pages deployment that violates the main-only environment policy.

## 0.10.0 - 2026-08-23

### Added

- Load standalone SketchUp material packages through `load_material()`, using
  content-based detection for both `.skm` files and mislabeled `.skp`
  downloads, with embedded base textures and opt-in V-Ray PBR values.
- Import standalone `.skm` materials in Blender, including mislabeled `.skp`
  downloads, packed textures, physical texture scale, and persistent data-blocks.

### Fixed

- Limit each GitHub Release body to the matching tagged section while retaining
  the complete project history in `CHANGELOG.md`.
- Dispatch legacy CArchive models with appended classification ZIP metadata to
  the legacy parser instead of mistaking them for modern ZIP-based models.
- Reject unrelated SKP classification documents as standalone materials.

## 0.9.1 - 2026-08-10

- Preserve door and window openings when triangulating walls with several coplanar holes.
- Apply glued component cutting contours to their host faces during Blender import.

### Changed

- Blender imports build component meshes only when reachable instances need
  them, while repeated instances continue sharing cached mesh data.
- Blender imports can reuse component definition collections, avoiding
  expanded copies of deeply repeated component object hierarchies when enabled.
- Modern files collect attributes for dense geometry sections during their
  primary parse instead of scanning every vertex and edge a second time.
- Large CAD faces use bounded ear selection and triangle merging, avoiding
  cubic n-gon preparation on boundaries with hundreds of vertices and holes.

### Fixed

- Imported Blender cameras use a far clipping plane of at least 100 km so
  large scenes remain visible through saved views.
- Visible loose SketchUp edges, including large imported 2D CAD drawings and
  line-only component definitions, are imported as Blender mesh edges.

## 0.9.0 - 2026-08-10

### Changed

- Legacy-format documentation is organized as a concise overview plus focused
  container, class-schema, and field-layout references.
- Agent notes contain only durable public development guidance instead of
  historical session logs or machine-specific procedures.
- Documentation examples are executed by a strict Sphinx doctest gate in local
  builds and CI.

### Fixed

- Blender collection instances preserve source parent transforms and instance
  offsets, deduplicate multi-linked objects, and serialize child definitions
  before their containers so official readers recognize the complete asset in
  modern and SketchUp Make 2017 exports.
- Blender mesh export marks an edge soft and smooth only when exactly two
  smooth-shaded faces share a non-sharp edge. Boundary, non-manifold, explicit
  sharp, and smooth/flat-transition edges now remain hard.

## 0.8.0 - 2026-07-19

### Added

- Complete modern writer coverage for geometry, materials/PBR/textures, UVs,
  layers/folders, components/groups/images, annotations, cameras/scenes,
  environments, styles, watermarks, match-photo images, options, axes,
  rendering/shadow state, and typed attribute dictionaries.
- Blender `export_scene.skp` operator and File > Export UI with object scope,
  unit conversion, evaluated modifiers, reusable mesh definitions, collection
  instances, PBR/textures/UVs, tags, camera-marker scenes, text annotations,
  and scalar custom properties.
- Independent Python-to-C conformance catalog with 59 writer fixtures plus a
  Blender-generated export validated through the public SketchUp SDK.

### Changed

- Writer unit tests compare generated data with independent raw bytes rather
  than using the parser as a round-trip oracle.
- The addon manifest and legacy `bl_info` now advertise bidirectional SKP IO.

### Fixed

- Modern annotations without an explicit font now reference the required
  default font, preventing official-reader error 12.
- Annotation entity associations, nested instance paths, shadow state, font
  objects, scene snapshots, multiple environments, and graph identity checks
  are preserved during writing.

## 0.7.0 - 2026-07-16

### Added

- Automatic, version-aware loading of SU3-SU2020 CArchive and SU2021 ZIP/TLV
  containers into one shared public model.
- Shared representations for text, dimensions, page backgrounds, relationship
  IDs, attribute ownership, rendering options, and layer display materials.
- Blender import for layer collections, construction geometry, annotations,
  saved scene cameras, PBR factors, UV projections, and edge shading, with
  responsive progress and cooperative cancellation.
- Generated compatibility validation for all 15 save targets, deterministic
  binary mutation coverage, and CI for Python 3.10-3.14 and Blender LTS/current.

### Changed

- Legacy and modern parsers now populate the same data structures directly;
  archive-only state is limited to provenance and unresolved wire identities.
- Parser, mesh-preparation, scene-graph, triangulation, and Blender construction
  phases are split into focused modules with enforced complexity thresholds.
- Dense parsing uses indexed TLV/archive lookups and linear child tracking.
- Modern saved scenes preserve persistent IDs, cameras, repeated references,
  and version-aware metadata defaults.

### Fixed

- Legacy and modern projected, positioned, mirrored, inherited, and two-sided
  UV mappings now follow SketchUp's observed material-side semantics.
- Material opacity respects its enable flag; image alpha, PBR factors, and
  dithered transparency are connected correctly in Blender.
- Modern inline layer materials, layer-folder membership, shadow country, scene
  identity, and section-display flags are preserved.
- Polygon reconstruction and triangulation reduce narrow triangles and preserve
  the minimum practical n-gon count, including faces with multiple holes.
- Invalid containers consistently raise `InvalidSkpError` while preserving the
  low-level cause; unsupported legacy schemas remain explicit.
- Metadata classification no longer truncates ordinary contributor names.

## 0.6.0 - 2026-06-30

### Added

- NumPy-backed vectors, transforms, UV calculations, and image alpha checks.
- Blender edge smoothing and sharp-edge import controls.
- Single-hole n-gon reconstruction and improved triangulation quality.

### Changed

- Parser logic and shared data structures were separated into dedicated
  modules without compatibility shims.
- Project documentation and quality checks became part of the release baseline.
