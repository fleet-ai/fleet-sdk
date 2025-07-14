.PHONY: help install-dev build test clean publish-to-pypi validate-tag unasync

help:
	@echo "Fleet Python SDK Development Commands"
	@echo "====================================="
	@echo "install-dev     Install package in development mode"
	@echo "build          Build package for distribution"
	@echo "test           Run tests"
	@echo "clean          Clean build artifacts"
	@echo "validate-tag   Validate release tag format"
	@echo "publish-to-pypi Publish package to PyPI"
	@echo "unasync        Generate sync code from async sources"

install-dev:
	python -m pip install --upgrade pip
	pip install build twine
	pip install -e .

build: clean unasync
	python -m build

test:
	python -m pytest

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

unasync:
	@echo "Running unasync to generate sync code from async sources..."
	@python -c "import os, unasync; \
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
		'list_instances_async': 'list_instances', \
		'get_async': 'get', \
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
		'httpx.AsyncClient': 'httpx.Client', \
	}); \
	files = [os.path.join(root, f) for root, dirs, files in os.walk('fleet/_async/') for f in files if f.endswith('.py') and f != '__init__.py']; \
	unasync.unasync_files(files, [rule])"
	@python scripts/fix_sync_imports.py
	@echo "✅ Sync code generated successfully!"

validate-tag:
	@if [ -z "$(TAG)" ]; then \
		echo "Usage: make validate-tag TAG=fleet-python-v0.1.0"; \
		exit 1; \
	fi
	./scripts/validate-release-tag.sh $(TAG)

publish-to-pypi: build
	@echo "⚠️  Warning: Direct publishing is deprecated for security reasons"
	@echo "🔒 Recommended: Use GitHub Actions workflow with OIDC authentication"
	@echo "📋 To publish via GitHub Actions:"
	@echo "   1. Ensure PyPI Trusted Publisher is configured"
	@echo "   2. Create release tag: git tag fleet-python-v<VERSION>"
	@echo "   3. Push tag: git push origin fleet-python-v<VERSION>"
	@echo ""
	@echo "Proceeding with direct upload in 5 seconds..."
	@sleep 5
	twine check dist/*
	twine upload dist/*

# Local development
dev-setup: install-dev
	@echo "✅ Development environment ready!"
	@echo "Run 'python examples/quickstart.py' to test the SDK" 