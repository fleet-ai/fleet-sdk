# Fleet SDK Integration Tests

Comprehensive integration tests for the Fleet Python SDK with real API calls

## 🚀 Quick Start

### Prerequisites
```bash
# Install test dependencies
pip install -r requirements.txt

# Set your Fleet API key
export FLEET_API_KEY="sk_your_key_here"
```

### Run All Tests
```bash
cd tests
python run_tests.py
```

### Run Fast Tests First
```bash
# Run quick tests for immediate feedback
python -m pytest integration/test_environment_management.py::TestFleetEnvFunctions -v
python -m pytest integration/test_performance.py::TestFastOperations -v
```

## 🎭 Test Environments

Tests use these available environments:
- **Dropbox** - Forge1.1.0 - region us-west-1
- **Hubspot** - Forge1.1.0 - region us-west-1  
- **Ramp** - Forge1.1.0 - region us-west-1

## 📁 Test Structure

```
tests/
├── conftest.py                    # Shared fixtures and configuration
├── pytest.ini                    # Pytest configuration
├── requirements.txt               # Test dependencies
├── run_tests.py                   # Test runner script
└── integration/
    ├── __init__.py
    ├── base_test.py               # Base test classes and utilities
    ├── test_sdk_imports.py        # SDK import and packaging tests
    ├── test_async_pattern.py      # Async pattern verification tests
    ├── test_environment_management.py  # Environment management tests
    ├── test_database_operations.py     # Database operation tests
    ├── test_browser_operations.py      # Browser operation tests
    ├── test_verifiers.py              # Verifier functionality tests
    ├── test_mcp_integration.py        # MCP integration tests
    ├── test_task_management.py        # Task management tests
    └── test_performance.py             # Performance measurement tests
```

## 🔧 Configuration

### Environment Variables
- `FLEET_API_KEY` - Your Fleet API key (required)
- `FLEET_TEST_ENV_KEY` - Specific environment to test (optional)

### Pytest Options
- `--api-key` - Pass API key via command line
- `-v` - Verbose output
- `-k "test_name"` - Run specific test
- `-m "asyncio"` - Run only async tests
- `--tb=short` - Short traceback format

## 📊 Test Categories

### **Fast Tests** (No environment creation)
- **SDK import tests** (`test_sdk_imports.py`) - Comprehensive import verification
- **Basic client creation** - Fleet and AsyncFleet instantiation
- **Public API function tests** - `fleet.env.list_envs()`, `fleet.env.list_regions()`
- **Environment listing** - Available environments and regions
- **Account information** - Team and account details

### **Integration Tests** (Require environment)
- Environment management
- Database operations
- Browser operations
- Verifier execution
- MCP integration
- Task workflows

### **Async Tests** (Async/await functionality)
- Async environment creation
- Async database operations
- Async browser operations
- Async verifiers
- Async task management
- **Async Pattern Verification** - Ensures correct resource access patterns

### **Performance Tests**
- Environment creation time
- Database operation time
- Browser operation time
- Fast API call timing

## 📈 Test Results

The test suite now includes:
- **171+ tests** covering all major SDK functionality
- **Async pattern verification** to ensure correct usage
- **Performance measurement** for optimization
- **Comprehensive error handling** and edge cases
- **Real API integration** with live environments

