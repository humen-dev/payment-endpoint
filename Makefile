PYTHON ?= python
SOURCES = shop tests migrations wsgi.py

.PHONY: help format lint test check db up down logs docker-test

help:  ## Show available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

format:  ## Sort imports and format the code
	$(PYTHON) -m isort $(SOURCES)
	$(PYTHON) -m black $(SOURCES)

lint:  ## Check imports, formatting and code style without changing files
	$(PYTHON) -m isort --check-only --diff $(SOURCES)
	$(PYTHON) -m black --check --diff $(SOURCES)
	$(PYTHON) -m flake8 $(SOURCES)

test:  ## Run the test suite locally (needs `make db`)
	$(PYTHON) -m pytest

check: lint test  ## Run the linters and the tests

db:  ## Start only PostgreSQL (to run the app and the tests locally)
	docker compose up -d --wait db

up:  ## Build and start PostgreSQL and the app on http://localhost:8000
	docker compose up -d --build --wait

down:  ## Stop the containers (the database volume is kept)
	docker compose down

logs:  ## Follow the app logs
	docker compose logs -f app

docker-test:  ## Run the test suite in Docker, no local Python needed
	docker compose run --rm --build tests
