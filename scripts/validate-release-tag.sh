#!/bin/bash

set -e

# Validate release tag for Fleet Python SDK
# Usage: validate-release-tag.sh <tag>

RELEASE_TAG=$1

if [ -z "$RELEASE_TAG" ]; then
    echo "Error: No release tag provided"
    exit 1
fi

echo "Validating release tag: $RELEASE_TAG"

# Check tag format: fleet-python-v*.*.* or fleet-python-v*.*.*b* (for beta releases)
if [[ ! $RELEASE_TAG =~ ^fleet-python-v[0-9]+\.[0-9]+\.[0-9]+(b[0-9]+)?$ ]]; then
    echo "Error: Invalid tag format. Expected: fleet-python-v*.*.* or fleet-python-v*.*.*b* (for beta)"
    echo "Received: $RELEASE_TAG"
    exit 1
fi

# Extract version from tag (remove fleet-python-v prefix)
TAG_VERSION=${RELEASE_TAG#fleet-python-v}
echo "Tag version: $TAG_VERSION"

# Check if we're on main branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ] && [ "$CURRENT_BRANCH" != "HEAD" ]; then
    echo "Warning: Not on main branch. Current branch: $CURRENT_BRANCH"
    # Check if this is a beta release
    if [[ $TAG_VERSION =~ b[0-9]+$ ]]; then
        echo "Beta release detected on non-main branch - skipping main branch ancestry check"
    else
        # For non-beta releases, check if the tag is reachable from main
        if ! git merge-base --is-ancestor $(git rev-parse $RELEASE_TAG) $(git rev-parse origin/main) 2>/dev/null; then
            echo "Error: Tag $RELEASE_TAG is not reachable from main branch"
            exit 1
        fi
    fi
fi

# Check if version in pyproject.toml matches tag
PYPROJECT_VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")

if [ "$TAG_VERSION" != "$PYPROJECT_VERSION" ]; then
    echo "Error: Tag version ($TAG_VERSION) does not match pyproject.toml version ($PYPROJECT_VERSION)"
    exit 1
fi

echo "✅ Tag validation passed"
echo "  - Format: ✅ $RELEASE_TAG"
echo "  - Version match: ✅ $TAG_VERSION = $PYPROJECT_VERSION"
echo "  - Branch: ✅ Reachable from main" 