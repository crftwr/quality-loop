VENV := .venv

UNAME_S := $(shell uname -s 2>/dev/null)
ifneq (,$(findstring MINGW,$(UNAME_S))$(findstring MSYS,$(UNAME_S))$(findstring CYGWIN,$(UNAME_S)))
    IS_WINDOWS := 1
else ifeq ($(OS),Windows_NT)
    IS_WINDOWS := 1
endif

ifeq ($(IS_WINDOWS),1)
    PYTHON := py
    VENV_PYTHON := $(VENV)/Scripts/python.exe
else
    PYTHON := python3.14
    VENV_PYTHON := $(VENV)/bin/python
endif

VENV_STAMP := $(VENV)/.installed

.PHONY: help test build publish-testpypi publish clean

help:
	@echo "make test              - run the tests"
	@echo "make build             - build the sdist and wheel into dist/"
	@echo "make publish-testpypi  - upload dist/ to TestPyPI"
	@echo "make publish           - upload dist/ to PyPI"

$(VENV_STAMP): pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --quiet -e ".[dev]"
	@touch $@

test: $(VENV_STAMP)
	$(VENV_PYTHON) -m pytest -q

build: $(VENV_STAMP)
	$(VENV_PYTHON) -m pip install --quiet build twine
	rm -rf dist build *.egg-info
	$(VENV_PYTHON) -m build
	$(VENV_PYTHON) -m twine check --strict dist/*

publish-testpypi: build
	$(VENV_PYTHON) -m twine upload -r testpypi dist/*

publish: build
	$(VENV_PYTHON) -m twine upload dist/*

clean:
	rm -rf dist build *.egg-info .pytest_cache
