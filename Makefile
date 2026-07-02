.PHONY: help install dev test lint typecheck build frontend docs clean docker-up docker-down

help:
	@echo "clean-evals dev tasks"
	@echo ""
	@echo "  install        Install package + dev extras"
	@echo "  dev            Install + start docker services"
	@echo "  test           Run pytest"
	@echo "  lint           Ruff + Black --check"
	@echo "  typecheck      mypy --strict"
	@echo "  frontend       Build React bundle"
	@echo "  build          Build the wheel (with bundled frontend)"
	@echo "  docs           Build and serve mkdocs locally"
	@echo "  docker-up      Bring up the docker-compose stack"
	@echo "  docker-down    Tear it down"
	@echo "  clean          Remove build artefacts"

install:
	pip install -e ".[dev,postgres,docs]"
	cd web && npm install --no-audit --no-fund

dev: install docker-up
	clean-evals migrate

test:
	pytest -ra

lint:
	ruff check .
	black --check .

typecheck:
	mypy src/

frontend:
	cd web && npm run build

build: frontend
	python -m build

docs:
	mkdocs serve

docker-up:
	docker-compose up -d redis mysql

docker-down:
	docker-compose down

clean:
	rm -rf build dist *.egg-info src/clean_evals/web/static/* site .mypy_cache .ruff_cache .pytest_cache .coverage coverage.xml
