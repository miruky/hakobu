.PHONY: install test lint fmt

install:
	pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .
	python -m ruff format --check .

fmt:
	python -m ruff format .
	python -m ruff check --fix .
