# Installing the Blender Addon

The addon bundles `skppy`; installing the standalone Python library is not
required. For library-only use, see [Installing skppy](../installing.md).

## Requirements

- Blender >= 4.2.0
- Python >= 3.10 (for the build step only - Blender supplies its own Python)

---

## Step 1 - Build the distribution ZIP

The build script packages the addon and its bundled `skppy` copy into a
single ZIP file:

```bash
python build_blender_addon.py
```

Output: `dist/blender_skp_io-<version>.zip`

The script:
- Derives the same public Python package version as `skppy` from Git tags.
- Copies `blender_skp_io/` (addon source) and `skppy/` (library) into the ZIP.
- Writes a Blender-compatible version into the packaged manifest and the
  derived Python package version into bundled `skppy`.
- Excludes `__pycache__`, `.git`, test files, and build artifacts.

For development versions, bundled `skppy` keeps the PEP 440 version such as
`0.8.1.dev12`, while the Blender manifest uses SemVer prerelease form such as
`0.8.1-dev.12`.

---

## Step 2 - Install in Blender

1. Open Blender (>= 4.2.0).
2. Go to **Edit -> Preferences -> Add-ons**.
3. Click **Install...** (top-right button).
4. Navigate and select `dist/blender_skp_io-<version>.zip`.
5. Enable the addon by checking the box next to
   **Import-Export: SketchUp IO (.skp)**.

> **Tip:** If you update the addon, disable and remove the old version first,
> then reinstall the new ZIP.

---

## Step 3 - Verify

Open **File -> Import -> SketchUp (.skp)**. The file browser should open with
the import option panel on the right side.

---

## Uninstalling

1. Go to **Edit -> Preferences -> Add-ons**.
2. Search for "SketchUp".
3. Expand the addon entry and click **Remove**.

---

## Development mode (manual install)

For development without rebuilding the ZIP on every change:

1. Locate Blender's addons directory:
   - **Linux:** `~/.config/blender/<version>/scripts/addons/`
   - **macOS:** `~/Library/Application Support/Blender/<version>/scripts/addons/`
   - **Windows:** `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`
2. Create a symlink or copy the `blender_skp_io/` folder there.
3. Also copy (or symlink) `skppy/` into the addon folder so `import skppy`
   resolves inside Blender.
4. Enable the addon in Preferences.

Changes to Python files take effect after reloading scripts
(**Edit -> Preferences -> Add-ons -> scroll to bottom -> "Reload Scripts"** or
press **F3** and search for "Reload Scripts").
