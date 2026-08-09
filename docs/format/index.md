# File Format Reference

Low-level documentation of the SketchUp `.skp` binary format established from
observed file behavior and interoperability testing by the `skppy` project.

| Document | Description |
|----------|-------------|
| [SKP Format](skp_format.md) | ZIP/VFF format emitted for SketchUp 2021+ - TLV encoding, all root tags, entity structure |
| [Legacy Format](old_format.md) | Overview of the pre-ZIP object graph emitted through SketchUp 2020 |
| [Legacy Container](reference/legacy_container.md) | Header, strings, version map, references, and root order |
| [Legacy Class Catalog](reference/legacy_classes.md) | Tabular class mappings and schema matrices |
| [Legacy Field Layouts](reference/legacy_fields.md) | Confirmed version-gated fields by feature family |
| [UV Projection](uv_projection.md) | Texture projection matrix math and TLV path |
| [Edge Shading Flags](edge_shading.md) | Soft/smooth edge flags and importer shading behavior |
| [Tag Map](../skp_tags.yaml) | Machine-readable YAML - 422 mapped tags with payload type annotations |

```{toctree}
:hidden:

skp_format
old_format
reference/legacy_container
reference/legacy_classes
reference/legacy_fields
uv_projection
edge_shading
```

> Findings are observation-based and may evolve as broader samples are tested.
> This documentation is not affiliated with or endorsed by Trimble Inc.
