# Legacy Container and Archive

This reference describes the pre-ZIP container used by SketchUp save targets
3–2020. It should be read with the [legacy overview](../old_format.md).

## Header

All observed multi-byte scalars are little-endian unless noted otherwise.

```text
product_name    legacy UTF-16 string, normally "SketchUp Model"
version_string  legacy UTF-16 string, for example "{8.0.1}"
model_id        16 raw bytes
saved_path      legacy UTF-16 string; may be empty
timestamp       u32 Unix timestamp
version_map     CVersionMap block
model_payload   serialized object graph
```

The saved path is informational. Consumers must not open it or use it to locate
resources.

## Legacy UTF-16 strings

Strings begin with `ff fe ff`, followed by a character count and UTF-16LE
payload.

| Form | Count encoding |
| --- | --- |
| Short | one-byte UTF-16 code-unit count |
| Extended | `ff`, then a little-endian `u16` count |
| Large extended | extended `u16` equals `ffff`, then a `u32` count |

The reader validates lengths before allocating or decoding. Both short and
extended forms occur in compatibility samples.

## Version map

The schema map precedes the object graph:

```text
magic       ff ff 00 00
name_len    u16, observed 11
name        ASCII "CVersionMap"
entries     repeated legacy UTF-16 class name + u32 schema
sentinel    class name "End-Of-Version-Map"
```

The map belongs to the file and is authoritative for body selection. Class
presence and schema numbers vary by save generation.

## Object and class references

The graph maintains ordered class and object tables for the active archive
session.

| Encoded tag | Meaning in context |
| --- | --- |
| `0x0000` | Null object |
| `0xffff` | New class definition follows |
| `0x8000 | index` | Short class back-reference |
| `0x0001..0x7ffe` | Short object back-reference |
| `0x7fff` + `u32` | Extended object/class reference; high bit selects class context |

A new class definition carries `schema: u16`, `name_length: u16`, and the ASCII
class name. The session allocates the object index separately; the raw class
reference value is not an entity identity.

Skipping an unknown object-valued field would corrupt later references. The
parser instead stops at the unsupported class/schema boundary.

## Primitive values

| Value | Wire representation |
| --- | --- |
| Boolean | archive boolean used by the owning schema |
| Point/vector | three `f64` values |
| Plane | four `f64` values |
| Transform | 13 `f64` values for legacy component placement |
| RGBA | four bytes; public colors normalize to ARGB where required |
| GUID | 16 raw bytes |
| Typed option | one-byte type code followed by type-specific payload |

Confirmed typed-option codes include `4` for a 32-bit integer, `6` for an
`f64`, and `7` for a boolean. Strings, arrays, colors, times, points, vectors,
unit vectors, and transforms also occur; unsupported types fail explicitly.

## High-level root order

After `End-Of-Version-Map`, the stream is already inside the root model body;
there is no separate root object tag. For SketchUp 8 the confirmed order is:

| Order | Block |
| ---: | --- |
| 1 | Version-gated model prologue and thumbnail state |
| 2 | Root component behavior and description |
| 3 | Options manager and model attribute dictionaries |
| 4 | Root camera and optional image data |
| 5 | Rendering options and version-gated state words |
| 6 | Root component: materials, layers, definitions, entities, relationships |
| 7 | Shadow/location, pages, axes, annotation styles, fonts, line styles, background image, styles, and watermarks |

Later generations extend the tail according to the file's schema map. Parsing
uses explicit version branches rather than searching for byte signatures.

## Options and attributes

The option manager has a version, a provider count, provider names, and
name/value pairs terminated by an empty key. Attribute containers similarly
hold named dictionaries with typed values.

Public mapping is owner-aware:

| Archive owner | Public destination |
| --- | --- |
| Root model properties | `Model.attribute_dictionaries` |
| Definitions, materials, layers | `Model.attribute_dictionaries_by_object_id` |
| Scoped entities | `Entities.attribute_dictionaries_by_entity_id` |

Archive container objects do not appear as duplicate public dictionaries.

## Embedded image blocks

Legacy image data may appear in material textures, placed images, background
images, watermarks, or thumbnail state. The containing class determines its
meaning. Encoded PNG/JPEG bytes are preserved only when they belong to a public
image-bearing object.

An observed thumbnail form contains an ASCII `CDib` key, stored schema, byte
count, and encoded image bytes. Its stored schema may differ from the main
version-map entry, so consumers must use the block's own bounded envelope.

## Safety requirements

- Validate every length against remaining bytes before reading.
- Bound recursion and retain one archive session per object graph.
- Never follow the serialized saved path.
- Do not infer class layouts from neighboring bytes.
- Report the file version, class, schema, reference index, and byte offset on
  failure.
