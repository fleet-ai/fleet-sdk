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

# Detached HEAD is normal in tag-triggered GitHub Actions. Always validate the
# tagged commit directly instead of inferring safety from the branch name.
TAG_COMMIT=$(git rev-list -n 1 "$RELEASE_TAG" 2>/dev/null) || {
    echo "Error: Tag $RELEASE_TAG does not exist"
    exit 1
}
MAIN_COMMIT=$(git rev-parse origin/main 2>/dev/null) || {
    echo "Error: origin/main is unavailable; fetch full history before validating"
    exit 1
}

if ! git merge-base --is-ancestor "$TAG_COMMIT" "$MAIN_COMMIT"; then
    echo "Error: Tag $RELEASE_TAG is not reachable from origin/main"
    exit 1
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
