.PHONY: setup test lint fmt data eval eval-validate run api ui clean

setup:
	uv sync --all-groups
	uv run pre-commit install

test:
	uv run pytest -v

lint:
	uv run ruff check .
	uv run black --check .

fmt:
	uv run ruff check --fix .
	uv run black .

data:
	uv run python -m ledgerql.data.build

eval:
	uv run python evals/run_eval.py --db $(or $(LEDGERQL_DB_PATH),data/ledgerql.duckdb)

eval-validate:
	uv run python evals/validate_gold.py --db data/ledgerql.duckdb

api:
	uv run uvicorn ledgerql.api:app --reload --port 8000

ui:
	uv run streamlit run ledgerql/ui/app.py

run: api

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
