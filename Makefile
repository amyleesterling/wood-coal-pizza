.PHONY: help install dev test sample run clean

PY ?= python3
STATES ?= NY,NJ,CT,MA,RI,PA,AZ,OR,CA,IL

help:
	@echo "wcpizza — wood/coal-fired pizza per capita"
	@echo ""
	@echo "  make install   Install runtime dependencies"
	@echo "  make dev       Install runtime + test dependencies"
	@echo "  make test      Run the test suite"
	@echo "  make sample    Run the pipeline offline on bundled fixtures"
	@echo "  make run       Run live (set STATES=NY,NJ,...). Hits Overpass+Census."
	@echo "  make clean     Remove generated artifacts and caches"

install:
	$(PY) -m pip install -r requirements.txt

dev:
	$(PY) -m pip install -r requirements-dev.txt

test:
	PYTHONPATH=src $(PY) -m pytest

sample:
	PYTHONPATH=src $(PY) -m wcpizza.pipeline run --source sample

run:
	PYTHONPATH=src $(PY) -m wcpizza.pipeline run --source live --states $(STATES)

clean:
	rm -rf data/raw/* data/interim/* .http_cache .pytest_cache
	rm -f data/processed/ranking.csv data/processed/restaurants.csv data/processed/summary.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
