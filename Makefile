.PHONY: help install-dev build test clean publish-to-pypi validate-tag

help:
	@echo "Fleet Python SDK Development Commands"
	@echo "====================================="
	@echo "install-dev     Install package in development mode"
	@echo "build          Build package for distribution"
	@echo "test           Run tests"
	@echo "clean          Clean build artifacts"
	@echo "validate-tag   Validate release tag format"
	@echo "publish-to-pypi Publish package to PyPI"

install-dev:
	python -m pip install --upgrade pip
	pip install build twine
	pip install -e .

build: clean
	python -m build

test:
	python -m pytest

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete

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