# Installing skppy

## Requirements

| Component | Minimum version | Notes |
|-----------|----------------|-------|
| Python | 3.11 | Runtime and development environment |
| NumPy | 1.24 | Installed automatically with `skppy` |

`skppy` is a Python library that depends on NumPy for geometry, UV, and image
processing helpers. Normal Python packaging installs the dependency
automatically.

### From PyPI

```bash
python -m pip install skppy
```

### From source (editable)

```bash
git clone https://github.com/dantedex/skppy.git
cd skppy
pip install -e .
```

Verify:

```python
import skppy
print(skppy.__version__)   # derived from the installed package metadata
```

### Inside a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate.bat       # Windows

pip install -e .
```

To install the bundled Blender integration instead, follow
[Installing the Blender Addon](blender/installing.md). It does not require a
separate `skppy` installation.

---

## Development setup

```bash
git clone https://github.com/dantedex/skppy.git
cd skppy

# Virtual environment
python -m venv .venv
source .venv/bin/activate

# Library + development dependencies
pip install -e ".[dev]"

# Optional but recommended local quality hooks
pre-commit install

# Run tests
make test

# Run formatting, lint, strict type checks, and docstring checks
make quality
```

### Building the documentation

```bash
pip install -r docs/requirements.txt
make docs
make doctest
# Open docs/_build/html/index.html
```

For live-reloading during editing:

```bash
cd docs && make livehtml
```
