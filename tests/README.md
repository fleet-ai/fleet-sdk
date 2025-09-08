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

### Run Unit Tests Only (No API Key Required)
```bash
cd tests/unit
python run_unit_tests.py
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
├── integration/                   # Integration tests (real API calls)
│   ├── __init__.py
│   ├── base_test.py               # Base test classes and utilities
│   ├── test_sdk_imports.py        # SDK import and packaging tests
│   ├── test_async_pattern.py      # Async pattern verification tests
│   ├── test_environment_management.py  # Environment management tests
│   ├── test_database_operations.py     # Database operation tests
│   ├── test_browser_operations.py      # Browser operation tests
│   ├── test_verifiers.py              # Verifier functionality tests
│   ├── test_mcp_integration.py        # MCP integration tests
│   ├── test_task_management.py        # Task management tests
│   └── test_performance.py             # Performance measurement tests
└── unit/                          # Unit tests (mock data only)
    ├── __init__.py
    ├── pytest.ini                 # Unit test configuration
    ├── run_unit_tests.py          # Unit test runner script
    ├── constants.py               # Mock data constants
    ├── helpers.py                 # Mock factories and utilities
    ├── base_test.py               # Base unit test classes
    ├── test_client.py             # Fleet/AsyncFleet client tests
    ├── test_environment.py        # Environment management tests
    ├── test_resources.py          # Database/browser resource tests
    ├── test_verifiers.py          # Verifier functionality tests
    ├── test_tasks.py              # Task management tests
    └── test_models.py             # Data model tests
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

## 🧪 Unit Tests (Mock Data)

### **Client Tests** (`test_client.py`)
- Fleet and AsyncFleet client initialization
- Configuration validation
- Error handling scenarios
- Interface consistency

### **Environment Tests** (`test_environment.py`)
- Environment creation and management
- Environment listing and filtering
- Resource access patterns
- Lifecycle management

### **Resource Tests** (`test_resources.py`)
- Database resource operations
- Browser resource operations
- Query execution and results
- Resource integration

### **Verifier Tests** (`test_verifiers.py`)
- Verifier decorator functionality
- Sync and async verifier patterns
- Execution and validation logic
- Error handling scenarios

### **Task Tests** (`test_tasks.py`)
- Task creation and management
- Task verification workflows
- Task filtering and lifecycle
- Performance characteristics

### **Model Tests** (`test_models.py`)
- Data model validation
- Serialization and deserialization
- Field validation and constraints
- Model consistency

## ⚡ Parallel Execution

Run tests in parallel for 2-4x faster execution:

```bash
# Auto-detect CPU cores
python -m pytest integration/ -n auto

# Use specific number of workers
python -m pytest integration/ -n 4

# Run only fast tests in parallel
python -m pytest integration/ -m fast -n auto

# Run with API key
python -m pytest integration/ -n auto --api-key=your_key_here
```

## 🔄 CI/CD Integration

The test suite includes GitHub Actions workflow for automated testing:

### **Manual Trigger Only**
- Runs only when manually triggered (`workflow_dispatch`)
- Supports multiple Python versions (3.9, 3.10, 3.11, 3.12)
- Configurable test types and parallel execution

### **Required Secrets**
Set these in your GitHub repository settings:
- `FLEET_API_KEY` - Your Fleet API key
- `FLEET_TEST_ENV_KEY` - Test environment key (optional)

### **Usage**
1. Go to **Actions** tab in GitHub
2. Select **Fleet SDK Test Suite**
3. Click **Run workflow**
4. Configure:
   - **Test Type**: `all`, `fast`, `integration`, or `async`
   - **Parallel**: Enable/disable parallel execution
   - **Workers**: Number of workers (0 = auto-detect)

## 📈 Test Coverage

- **171+ integration tests** covering all major SDK functionality
- **100+ unit tests** with comprehensive mock data coverage
- **Real API integration** with live environments
- **Async/await pattern verification**
- **Performance measurement** and optimization
- **Mock data validation** for all SDK components

