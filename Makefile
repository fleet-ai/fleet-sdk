.PHONY: help install-dev build test clean validate-tag unasync release-help

# Use the active Python interpreter (python3 preferred, fallback to python)
PYTHON ?= $(shell command -v python3 || command -v python)

help:
	@echo "Fleet Python SDK Development Commands"
	@echo "====================================="
	@echo "install-dev     Install package in development mode"
	@echo "build          Build package for distribution"
	@echo "test           Run tests"
	@echo "clean          Clean build artifacts"
	@echo "validate-tag   Validate release tag format"
	@echo "release-help    Show the automated release process"
	@echo "unasync        Generate sync code from async sources"

install-dev:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install --upgrade build twine
	$(PYTHON) -m pip install -e ".[dev]"

build: clean unasync
	$(PYTHON) -m build

test:
	.venv/bin/python -m pytest

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

unasync:
	@echo "Running unasync to generate sync code from async sources..."
	@$(PYTHON) -c "import os, unasync; \
	rule = unasync.Rule('fleet/_async/', 'fleet/', { \
		'AsyncClient': 'Client', \
		'AsyncInstanceClient': 'InstanceClient', \
		'AsyncEnvironment': 'Environment', \
		'AsyncFleet': 'Fleet', \
		'AsyncWrapper': 'SyncWrapper', \
		'AsyncResource': 'Resource', \
		'AsyncSQLiteResource': 'SQLiteResource', \
		'AsyncBrowserResource': 'BrowserResource', \
		'AsyncFleetPlaywrightWrapper': 'FleetPlaywrightWrapper', \
		'make_async': 'make', \
		'list_envs_async': 'list_envs', \
		'list_regions_async': 'list_regions', \
		'list_instances_async': 'list_instances', \
		'get_async': 'get', \
		'account_async': 'account', \
		'async def': 'def', \
		'from fleet.verifiers': 'from ..verifiers', \
		'await asyncio.sleep': 'time.sleep', \
		'await ': '', \
		'async with': 'with', \
		'async for': 'for', \
		'__aenter__': '__enter__', \
		'__aexit__': '__exit__', \
		'playwright.async_api': 'playwright.sync_api', \
		'async_playwright': 'sync_playwright', \
		'asyncio.sleep': 'time.sleep', \
		'asyncio.iscoroutinefunction': 'inspect.iscoroutinefunction', \
		'httpx.AsyncClient': 'httpx.Client', \
		'httpx.AsyncHTTPTransport': 'httpx.HTTPTransport', \
		'httpx.SyncHTTPTransport': 'httpx.HTTPTransport', \
		'from ..config import': 'from .config import', \
	}); \
	files = [os.path.join(root, f) for root, dirs, files in os.walk('fleet/_async/') for f in files if f.endswith('.py') and f != '__init__.py']; \
	print('Files to process:', files); \
	unasync.unasync_files(files, [rule])"
	@$(PYTHON) scripts/fix_sync_imports.py
	@echo "✅ Sync code generated successfully!"

validate-tag:
	@if [ -z "$(TAG)" ]; then \
		echo "Usage: make validate-tag TAG=fleet-python-v0.1.0"; \
		exit 1; \
	fi
	./scripts/validate-release-tag.sh $(TAG)

release-help:
	@echo "Fleet SDK releases are automated from protected main."
	@echo "Merge the reviewed Release Please PR; do not create or push tags manually."
	@echo "See docs/releases.md for gates, configuration, retry, and rollback guidance."

# Local development
dev-setup: install-dev
	@echo "✅ Development environment ready!"
	@echo "Run 'python examples/quickstart.py' to test the SDK" 
