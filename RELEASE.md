# Fleet Python SDK Release Guide

This document outlines the process for releasing new versions of the Fleet Python SDK to PyPI.

## Prerequisites

1. **PyPI Account**: You need a PyPI account with permissions to manage the `fleet-python` package
2. **Trusted Publisher**: Configure PyPI to trust the GitHub repository (see setup instructions below)
3. **GitHub Environment**: Optionally create a `pypi` environment in GitHub repository settings for additional security

## PyPI Trusted Publisher Setup

Before the first release, you need to configure PyPI to trust this GitHub repository:

1. **Go to PyPI Trusted Publishers**: Visit [PyPI Trusted Publishers](https://pypi.org/manage/account/publishing/)
2. **Add Pending Publisher**: Since the project doesn't exist yet, add a "pending" publisher
3. **Configure GitHub Integration**:

   - **PyPI Project Name**: `fleet-python`
   - **Owner**: `fleet-ai` (or your GitHub organization/username)
   - **Repository name**: `fleet-python` (or your repository name)
   - **Workflow name**: `publish-fleet-sdk.yml`
   - **Environment name**: `pypi` (optional but recommended)

4. **Create GitHub Environment** (optional but recommended):
   - Go to your GitHub repository settings
   - Navigate to "Environments" → "New environment"
   - Create environment named `pypi`
   - Add protection rules (e.g., required reviewers)

Once configured, the workflow will automatically authenticate with PyPI using OIDC (no tokens needed!).

## Release Process

### 1. Prepare the Release

1. **Update Version**: Edit `pyproject.toml` and update the version number:

   ```toml
   version = "0.2.0"  # Update to new version
   ```

2. **Update Changelog**: Document changes in `CHANGELOG.md` (if exists) or in release notes

3. **Test Locally**: Run tests and validate the package builds correctly:
   ```bash
   cd fleet-sdk
   make dev-setup
   make build
   python examples/quickstart.py  # Test basic functionality
   ```

### 2. Create and Push Tag

1. **Commit Changes**: Commit version updates to the main branch:

   ```bash
   git add pyproject.toml
   git commit -m "Bump version to 0.2.0"
   git push origin main
   ```

2. **Create Tag**: Create a release tag following the format `fleet-python-v*.*.*`:
   ```bash
   git tag fleet-python-v0.2.0
   git push origin fleet-python-v0.2.0
   ```

### 3. Automated Publishing

The GitHub Actions workflow (`.github/workflows/publish-fleet-sdk.yml`) will automatically:

1. **Validate**: Check tag format and version consistency
2. **Build**: Create distribution packages
3. **Test**: Verify package integrity
4. **Publish**: Upload to PyPI

### 4. Verify Release

1. **Check PyPI**: Verify the new version appears on [PyPI](https://pypi.org/project/fleet-python/)
2. **Test Installation**: Test installing from PyPI:
   ```bash
   pip install fleet-python==0.2.0
   ```

## Manual Release (Fallback)

If automated publishing fails, you can publish manually:

```bash
cd fleet-sdk

# Set up environment
make install-dev

# Build package
make build

# Validate package
twine check dist/*

# Upload to PyPI (requires PyPI account authentication)
# Note: You'll need to configure PyPI credentials with `twine configure`
# or use a PyPI token via environment variables
make publish-to-pypi
```

⚠️ **Warning**: Manual releases are less secure than OIDC authentication and bypass validation checks.

## Version Strategy

Fleet SDK follows [Semantic Versioning](https://semver.org/):

- **Major (X.0.0)**: Breaking changes
- **Minor (0.X.0)**: New features, backward compatible
- **Patch (0.0.X)**: Bug fixes, backward compatible

## Tag Format

Tags must follow the exact format: `fleet-python-v*.*.*`

Examples:

- ✅ `fleet-python-v0.1.0`
- ✅ `fleet-python-v1.2.3`
- ❌ `v0.1.0`
- ❌ `fleet-v0.1.0`
- ❌ `0.1.0`

## Troubleshooting

### Tag Validation Fails

- Ensure tag format matches `fleet-python-v*.*.*`
- Verify version in `pyproject.toml` matches tag version
- Check that tag is reachable from main branch

### PyPI Upload Fails

- Verify PyPI Trusted Publisher is correctly configured
- Ensure version number hasn't been used before
- Check that GitHub Actions workflow has proper OIDC permissions
- Verify package metadata is valid

### Build Fails

- Verify all dependencies are correctly specified
- Check Python version compatibility
- Ensure all required files are included in the package
