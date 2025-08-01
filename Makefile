.PHONY: help install dev test lint format clean docker-build docker-up docker-down migrate upgrade downgrade seed

# Default target
help:
	@echo "Available commands:"
	@echo "  install     - Install dependencies"
	@echo "  dev         - Run development server"
	@echo "  test        - Run tests"
	@echo "  test-cov    - Run tests with coverage"
	@echo "  lint        - Run linting"
	@echo "  format      - Format code"
	@echo "  clean       - Clean cache and temp files"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-up   - Start Docker services"
	@echo "  docker-down - Stop Docker services"
	@echo "  migrate     - Create new migration"
	@echo "  upgrade     - Apply migrations"
	@echo "  downgrade   - Rollback migration"
	@echo "  seed        - Seed database with sample data"
	@echo "  shell       - Start Python shell with app context"

# Install dependencies
install:
	pip install -r requirements.txt

# Install development dependencies
dev-install:
	pip install -r requirements.txt
	pip install pytest pytest-asyncio pytest-cov black flake8 mypy

# Run development server
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
test:
	pytest

# Run tests with coverage
test-cov:
	pytest --cov=app --cov-report=html --cov-report=term-missing

# Run specific test file
test-file:
	pytest $(FILE) -v

# Run tests with specific marker
test-marker:
	pytest -m $(MARKER) -v

# Lint code
lint:
	flake8 app/ tests/
	mypy app/

# Format code
format:
	black app/ tests/
	isort app/ tests/

# Clean cache and temporary files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type f -name "*.log" -delete

# Docker commands
docker-build:
	docker build -t vision-fintech-backend .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-shell:
	docker-compose exec app bash

# Database commands
migrate:
	alembic revision --autogenerate -m "$(MESSAGE)"

upgrade:
	alembic upgrade head

downgrade:
	alembic downgrade -1

reset-db:
	alembic downgrade base
	alembic upgrade head

# Seed database with sample data
seed:
	python scripts/seed_database.py

# Start Python shell with app context
shell:
	python -c "from app.main import app; import asyncio; from app.core.database import get_db; print('App context loaded')"

# Security scan
security:
	bandit -r app/
	safety check

# Generate requirements.txt from current environment
freeze:
	pip freeze > requirements.txt

# Check for outdated packages
outdated:
	pip list --outdated

# Run all quality checks
quality: lint test-cov security
	@echo "All quality checks completed"

# Production deployment preparation
prod-check:
	@echo "Running production readiness checks..."
	pytest tests/ -v
	flake8 app/
	mypy app/
	bandit -r app/
	@echo "Production checks completed"

# Start Celery worker
celery-worker:
	celery -A app.tasks worker --loglevel=info

# Start Celery beat scheduler
celery-beat:
	celery -A app.tasks beat --loglevel=info

# Start Flower monitoring
flower:
	celery -A app.tasks flower --port=5555

# Monitor application
monitor:
	@echo "Starting monitoring dashboard..."
	@echo "Flower: http://localhost:5555"
	@echo "API Docs: http://localhost:8000/docs"
	@echo "Health Check: http://localhost:8000/health"

# Backup database
backup:
	pg_dump $(DATABASE_URL) > backup_$(shell date +%Y%m%d_%H%M%S).sql

# Restore database
restore:
	psql $(DATABASE_URL) < $(BACKUP_FILE)

# Load environment variables and run command
env-run:
	set -a && source .env && set +a && $(COMMAND)

# Check environment setup
check-env:
	@echo "Checking environment setup..."
	@python -c "import sys; print(f'Python: {sys.version}')"
	@python -c "import fastapi; print(f'FastAPI: {fastapi.__version__}')"
	@python -c "import sqlalchemy; print(f'SQLAlchemy: {sqlalchemy.__version__}')"
	@python -c "import redis; print(f'Redis: {redis.__version__}')"
	@echo "Environment check completed"

# Initialize project (first time setup)
init:
	@echo "Initializing project..."
	make dev-install
	cp .env.example .env
	@echo "Please edit .env file with your configuration"
	@echo "Then run: make upgrade && make seed"
	@echo "Finally run: make dev"

# Full setup for new developers
setup: init
	@echo "Setting up database..."
	make upgrade
	make seed
	@echo "Setup completed! Run 'make dev' to start the server"