PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)
BLENDER ?= blender
BLENDER_FIXTURE ?=
BLENDER_EXPORT_OUTPUT ?=

.PHONY: coverage docs docs-versioned doctest docs-clean test test-blender quality docstrings

coverage:
	$(PYTHON) -m pytest --cov=skppy --cov-report=term-missing --cov-fail-under=100

docs:
	rm -rf docs/api/generated
	$(PYTHON) -m sphinx -b html -W --keep-going docs docs/_build/html

docs-versioned:
	rm -rf docs/api/generated docs/_build/html
	$(PYTHON) docs/build_versioned.py docs/_build/html

doctest:
	rm -rf docs/_build/doctest
	$(PYTHON) -m sphinx -b doctest -W --keep-going docs docs/_build/doctest

docs-clean:
	rm -rf docs/_build docs/api/generated

test:
	$(PYTHON) -m pytest -q

test-blender:
	$(PYTHON) build_blender_addon.py --clean
	BLENDER_USER_RESOURCES=$$(mktemp -d) $(BLENDER) --background -noaudio --factory-startup \
		--python-exit-code 1 \
		--python tests/blender/run_integration.py -- \
		--addon $$(ls -t dist/blender_skp_io-*.zip | head -1) \
		$(if $(BLENDER_FIXTURE),--fixture "$(BLENDER_FIXTURE)") \
		$(if $(BLENDER_EXPORT_OUTPUT),--export-output "$(BLENDER_EXPORT_OUTPUT)")

docstrings:
	$(PYTHON) -m pydocstyle skppy

quality:
	$(PYTHON) -m ruff format --check skppy blender_skp_io tests build_blender_addon.py
	$(PYTHON) -m ruff check skppy blender_skp_io tests build_blender_addon.py
	$(PYTHON) -m mypy skppy
	$(MAKE) docstrings
