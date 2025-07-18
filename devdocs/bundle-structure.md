# Fleet Verifier Bundle Structure

## Overview

A **bundle** is a ZIP file containing all the code and metadata needed to execute a verifier function remotely. It's created by the client using **tree shaking** to minimize size and sent to the server for execution.

## Bundle Structure

```
bundle.zip (2,004 bytes)
├── requirements.txt (31 bytes)           # PyPI packages for server-side uv resolution
├── verifier.py (682 bytes)               # Main verifier function source code
├── manifest.json (149 bytes)             # Bundle metadata & execution info
└── fleet/ (1,888 bytes)                  # Tree-shaken local imports
    ├── __init__.py (28 bytes)
    ├── _async/
    │   ├── __init__.py (28 bytes)
    │   └── verifiers/
    │       ├── __init__.py (28 bytes)
    │       └── decorator.py (1,888 bytes)  # Only AsyncVerifiedFunction class
```

## File Details

### 1. requirements.txt

**Purpose**: Lists PyPI packages for server-side dependency resolution
**Content Example**:

```
fleet-python
numpy
torch==2.3.0
```

**Server Processing**: `uv install -r requirements.txt` to get wheels

### 2. verifier.py

**Purpose**: Contains the main verifier function
**Content**: Exact source code of your verifier function
**Server Processing**: Imported and executed as entry point

### 3. manifest.json

**Purpose**: Bundle metadata and execution instructions
**Content Example**:

```json
{
  "function_name": "validate_model",
  "entry": "verifier.validate_model",
  "version": "1.0",
  "optimized": true,
  "tree_shaken": true,
  "verifier_id": "cbbcc8e4-d4c0-44b4-8e6a-510e48865762"
}
```

**Server Processing**: Uses entry point and verifier_id for execution and caching

### 4. fleet/ Directory

**Purpose**: Tree-shaken local project files
**Content**: Only the specific functions/classes that the verifier imports
**Size**: Dramatically reduced from original files (1,000+ lines → 46 lines)

## Tree Shaking Process

### What Gets Included

- **Main verifier function** → `verifier.py`
- **PyPI packages** → `requirements.txt`
- **Imported local functions** → extracted and included
- **Necessary imports** → only used imports included
- **Auto-generated `__init__.py`** → for proper Python imports

### What Gets Excluded

- **Unused functions** from local files
- **Unused imports**
- **Comments and documentation**
- **Test code**
- **Standard library imports** (available on server)

## Bundle Creation Flow

### 1. Dependency Analysis

```python
# Verifier function
@verifier(extra_requirements=["torch==2.3.0"])
def validate_model(env, threshold: float) -> float:
    import json  # Standard library - not bundled
    from fleet._async.verifiers.decorator import AsyncVerifiedFunction  # Local - tree-shaken
    # ... function logic
```

### 2. Tree Shaking

- **AST parsing** of function source code
- **Import analysis** to find dependencies
- **Function extraction** from local files
- **Dependency tracing** to include transitive dependencies

### 3. Bundle Assembly

- Create temporary directory structure
- Write extracted code to appropriate files
- Generate manifest with execution metadata
- Create ZIP archive with all files

## Server-Side Processing

### 1. Bundle Extraction

```python
# Server receives ZIP bytes
with zipfile.ZipFile(bundle_data) as zf:
    zf.extractall(work_dir)
```

### 2. Dependency Installation

```python
# Server runs uv to install PyPI packages
uv install -r requirements.txt --python 3.11
```

### 3. Function Execution

```python
# Server imports and executes
sys.path.insert(0, work_dir)
from verifier import validate_model
result = validate_model(env, *args, **kwargs)
```

## Bundle Caching

### Client-Side Bundle Caching

- **Function signature cache**: Same function → same bundle
- **Per-verifier bundler**: Each verifier has its own bundler instance
- **Instant cache hits**: Subsequent calls to same verifier use cached bundle

### Server-Side Bundle Caching (via Bundle Tracking)

- **Verifier ID tracking**: Each bundle has unique verifier_id
- **Per-environment tracking**: Client tracks which environments have bundles
- **Automatic error recovery**: Handles server restarts gracefully

## Bundle Size Optimization

### Tree Shaking Results

- **Before**: ~50KB bundles (entire files)
- **After**: ~2KB bundles (tree-shaken)
- **Reduction**: 95%+ size reduction

### Network Traffic Optimization

- **Before**: Send bundle every call
- **After**: Send bundle once per verifier per environment
- **Reduction**: 63-96% for repeated calls

## Example Bundle Analysis

```python
@verifier(extra_requirements=["numpy"])
def example_verifier(env, x: int) -> float:
    import json
    from fleet._async.verifiers.decorator import AsyncVerifiedFunction
    return float(x)
```

**Resulting Bundle**:

- `requirements.txt`: `fleet-python\nnumpy`
- `verifier.py`: Function source code
- `manifest.json`: Execution metadata with verifier_id
- `fleet/_async/verifiers/decorator.py`: Only AsyncVerifiedFunction class

## Key Benefits

1. **Minimal Size**: Tree shaking reduces bundle size by 95%+
2. **Fast Creation**: Client-side caching makes bundle creation instant
3. **Efficient Transfer**: Small bundles transfer quickly
4. **Server Efficiency**: Server can cache processed bundles by verifier_id
5. **Automatic Optimization**: All optimization is transparent to user code

The bundle is essentially a **portable, optimized execution environment** that contains exactly what's needed to run your verifier function remotely.
