PYTHON ?= python
SOURCES = shop tests migrations wsgi.py

.PHONY: help format lint test check

help:  ## Show available commands
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

format:  ## Sort imports and format the code
	$(PYTHON) -m isort $(SOURCES)
	$(PYTHON) -m black $(SOURCES)

lint:  ## Check imports, formatting and code style without changing files
	$(PYTHON) -m isort --check-only --diff $(SOURCES)
	$(PYTHON) -m black --check --diff $(SOURCES)
	$(PYTHON) -m flake8 $(SOURCES)

test:  ## Run the test suite (needs `docker compose up -d --wait`)
	$(PYTHON) -m pytest

check: lint test  ## Run the linters and the tests
