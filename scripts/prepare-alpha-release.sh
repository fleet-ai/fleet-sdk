#!/bin/bash

set -e

# Helper script to prepare an alpha release of the Fleet Python SDK
# Usage: ./scripts/prepare-alpha-release.sh <alpha-version>
# Example: ./scripts/prepare-alpha-release.sh 0.2.64-alpha1

ALPHA_VERSION=$1

if [ -z "$ALPHA_VERSION" ]; then
    echo "Error: No alpha version provided"
    echo "Usage: ./scripts/prepare-alpha-release.sh <alpha-version>"
    echo "Examples:"
    echo "  ./scripts/prepare-alpha-release.sh 0.2.64-alpha1"
    echo "  ./scripts/prepare-alpha-release.sh 0.2.64a1"
    exit 1
fi

echo "Preparing alpha release: $ALPHA_VERSION"

# Validate alpha version format
if [[ ! $ALPHA_VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+(-?alpha[0-9]*|a[0-9]+)$ ]]; then
    echo "Error: Invalid alpha version format"
    echo "Expected format: X.Y.Z-alphaN, X.Y.Z-alpha, or X.Y.ZaN"
    echo "Received: $ALPHA_VERSION"
    exit 1
fi

# Check if we have uncommitted changes
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "⚠️  Warning: You have uncommitted changes"
    echo "It's recommended to commit all changes before creating an alpha release"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get current version from pyproject.toml
CURRENT_VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
echo "Current version in pyproject.toml: $CURRENT_VERSION"

# Update version in pyproject.toml
echo "Updating version in pyproject.toml to $ALPHA_VERSION..."

# Use Python to update the version
python << EOF
import tomllib
import re

# Read the file
with open('pyproject.toml', 'r') as f:
    content = f.read()

# Replace version using regex
new_content = re.sub(
    r'(version\s*=\s*")[^"]+(")',
    r'\g<1>$ALPHA_VERSION\g<2>',
    content
)

# Write back
with open('pyproject.toml', 'w') as f:
    f.write(new_content)

print(f"✅ Updated pyproject.toml version to $ALPHA_VERSION")
EOF

# Verify the change
NEW_VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
if [ "$NEW_VERSION" != "$ALPHA_VERSION" ]; then
    echo "❌ Error: Failed to update version in pyproject.toml"
    exit 1
fi

echo ""
echo "✅ Alpha release prepared successfully!"
echo ""
echo "Next steps:"
echo "1. Review the changes:"
echo "   git diff pyproject.toml"
echo ""
echo "2. Commit the version change:"
echo "   git add pyproject.toml"
echo "   git commit -m \"Bump version to $ALPHA_VERSION\""
echo ""
echo "3. Create and push the tag:"
echo "   git tag fleet-python-v$ALPHA_VERSION"
echo "   git push origin fleet-python-v$ALPHA_VERSION"
echo ""
echo "4. The GitHub Actions workflow will automatically:"
echo "   - Validate the alpha version"
echo "   - Build the package"
echo "   - Publish to PyPI"
echo ""
echo "Users can then install with:"
echo "   pip install fleet-python==$ALPHA_VERSION"
echo "   or"
echo "   pip install --pre fleet-python  # to get latest pre-release"

