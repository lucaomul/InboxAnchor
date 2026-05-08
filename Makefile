PYTHON ?= python3

.PHONY: api dashboard test lint format

api:
	$(PYTHON) -m uvicorn inboxanchor.api.main:app --reload

dashboard:
	$(PYTHON) -m streamlit run inboxanchor/app/dashboard.py

test:
	$(PYTHON) -m pytest --tb=short

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff check . --fix
