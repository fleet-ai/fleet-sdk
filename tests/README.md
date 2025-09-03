# Fleet SDK Integration Tests

Comprehensive integration tests for the Fleet Python SDK with real API calls

## 📁 Structure

```
tests/
├── integration/
│   ├── base_test.py          # DRY base classes with common functionality
│   ├── test_sdk_import.py    # SDK import and basic functionality tests
│   ├── test_fleet_core.py    # Core functionality including .make()
│   ├── test_resources.py     # Database, browser, and resource tests
│   └── test_verifiers.py     # Verifier functionality tests
├── conftest.py               # Pytest configuration and fixtures
├── pytest.ini               # Test settings and markers
├── requirements.txt          # Test dependencies
└── README.md                 # This file
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd tests
pip install -r requirements.txt
```

### 2. Set API Key

```bash
# Linux/Mac
export FLEET_API_KEY="your-api-key-here"

# Windows PowerShell
$env:FLEET_API_KEY="your-api-key-here"

# Or pass via command line
pytest --api-key="your-api-key-here"
```

### 3. Run Tests

```bash
# Run all integration tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest integration/test_fleet_core.py -v

# Run tests in parallel (faster)
pytest -n auto

# Run only fast tests (exclude slow ones)
pytest -m "not slow"
```

## 📋 Test Categories

### Core Functionality Tests
- **SDK Import Tests** (`test_sdk_import.py`) - Verify SDK modules can be imported
- **Fleet Core Tests** (`test_fleet_core.py`) - Test `.make()`, environment management, task loading
- **Resource Tests** (`test_resources.py`) - Database, browser resource functionality
- **Verifier Tests** (`test_verifiers.py`) - Verifier creation, bundling, execution

### Test Markers

```bash
# Integration tests (all tests are integration by default)
pytest -m integration

# Slow tests (>30 seconds)
pytest -m slow

# Tests requiring environment instances
pytest -m requires_instance

# Exclude slow tests
pytest -m "not slow"
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLEET_API_KEY` | Your Fleet API key (required) | None |
| `FLEET_TEST_ENV_KEY` | Environment key for testing | `"fira"` |
| `FLEET_TEST_VERSION` | Version for testing | `"v1.3.1"` |

### Command Line Options

```bash
pytest --api-key="sk_your_key"        # Set API key
pytest --timeout=300                   # Set test timeout
pytest -x                             # Stop on first failure
pytest --tb=short                     # Short traceback format
```

## 📊 Expected Test Coverage

### Major Functionality Tested

✅ **SDK Import & Basic Usage**
- Module imports work correctly
- Client initialization 
- Global client functions

✅ **Core Fleet Functionality**
- `.make()` method with various parameters
- Environment listing and access
- Task loading and management
- Async variants of all operations

✅ **Resource Management**
- Database (SQLite) operations
- Browser automation
- State-based resource access
- Error handling

✅ **Verifier System**
- Sync and async verifier creation
- Verifier bundling
- Remote execution (if supported)
- Database interaction verifiers

## 🚦 Running Specific Tests

### Test the .make() Functionality
```bash
pytest integration/test_fleet_core.py::TestMakeFunctionality -v
```

### Test SDK Import
```bash
pytest integration/test_sdk_import.py -v
```

### Test Database Resources
```bash
pytest integration/test_resources.py::TestDatabaseResources -v
```

### Test Async Functionality
```bash
pytest integration/test_fleet_core.py::TestAsyncFleetClient -v
```

## 🐛 Troubleshooting

### Common Issues

**No API key provided**
```
Solution: Set FLEET_API_KEY environment variable or use --api-key option
```

**Tests skipped with "not available"**
```
This is normal - tests skip when functionality isn't available in your environment
```

**Timeout errors**
```bash
# Increase timeout for slow operations
pytest --timeout=600
```

**Import errors**
```
Ensure you're running tests from the project root and Flask SDK is in the path
```

### Expected Output
```
======================== test session starts ========================
collected 25+ items

integration/test_sdk_import.py ✓✓✓✓✓✓✓✓
integration/test_fleet_core.py ✓✓✓✓✓✓✓✓  
integration/test_resources.py ✓✓✓✓✓✓
integration/test_verifiers.py ✓✓✓✓✓

==================== 25+ passed in 45.2s ====================
```

## 🔄 CI/CD Integration

For continuous integration, use:

```bash
# Install dependencies  
pip install -r tests/requirements.txt

# Run tests with API key from secrets
pytest --api-key="$FLEET_API_KEY" --tb=short

# Generate test report
pytest --html=test_report.html --self-contained-html
```

