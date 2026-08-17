.PHONY: install test lint format migrate run

install:
	pip install -r requirements.txt -r requirements-dev.txt
	pre-commit install

test:
	pytest --cov=core --cov-report=term-missing --cov-fail-under=71 -v

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

migrate:
	python manage.py migrate

run:
	python manage.py runserver
