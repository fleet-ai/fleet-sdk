# Server-Side UV Architecture for Remote Verifiers

## Overview

We've moved dependency resolution from client-side to server-side to improve reliability, security, and performance. The client now creates lightweight bundles while the server handles all `uv` operations.

## Architecture Changes

### Before (Client-Side UV)

```
Client:
1. Analyze function dependencies
2. Run uv compile to create lock.txt
3. Run uv install to download wheels
4. Create bundle with source + wheels (~50MB)
5. Upload bundle to server

Server:
1. Extract bundle
2. Execute function directly
```

### After (Server-Side UV)

```
Client:
1. Analyze function dependencies
2. Map imports to PyPI package names
3. Create lightweight bundle with source + requirements.txt (~50KB)
4. Upload bundle to server

Server:
1. Extract bundle
2. Run uv compile to create lock.txt
3. Run uv install to download wheels
4. Create execution environment
5. Execute function
```

## Benefits

### 1. **Eliminates Client Dependencies**

- No need for `uv` on client machines
- Works on any Python environment
- Simpler client setup

### 2. **Solves Platform Issues**

- Client can be macOS/Windows, server handles Linux compilation
- Consistent wheel resolution for target platform
- No cross-platform compatibility issues

### 3. **Dramatic Size Reduction**

- Bundle size: ~50MB → ~50KB (99%+ reduction)
- Faster uploads with HTTP/2 compression
- Reduced network bandwidth usage

### 4. **Improved Security**

- Server controls dependency resolution
- Centralized security policies
- No client-side package installation

### 5. **Better Performance**

- Server can cache resolved dependencies
- Parallel execution of multiple verifiers
- Reduced client-side processing time

### 6. **Consistency**

- Same `uv` version across all executions
- Deterministic dependency resolution
- No version drift between clients

## Bundle Structure

### Lightweight Bundle (Client → Server)

```
bundle.zip
├── verifier.py          # Function source code
├── requirements.txt     # PyPI package names
├── manifest.json        # Execution metadata
└── fleet/               # Local project files (if any)
    ├── __init__.py
    └── _async/
        └── verifiers/
            └── decorator.py
```

### Server-Side Resolution

```
Server receives bundle →
Server runs uv compile →
Server runs uv install →
Server creates execution environment →
Server executes function
```

## Implementation Details

### Client-Side Changes

1. **Removed UV operations** from `FunctionBundler`
2. **Simplified bundle creation** to only package source + requirements
3. **Enhanced dependency detection** using `modulegraph2` + AST analysis
4. **Maintained caching** for repeated bundle creation

### Server-Side Requirements (Future)

1. **Install uv** on server infrastructure
2. **Add bundle extraction** logic
3. **Implement dependency resolution** pipeline
4. **Add execution environment** management
5. **Handle caching** of resolved dependencies

## Testing

The lightweight bundle test confirms:

- ✅ Bundle contains only source code and requirements
- ✅ No uv artifacts (lock.txt, \_\_venv, wheels)
- ✅ Proper dependency detection
- ✅ Correct function extraction
- ✅ 99%+ size reduction

## Migration Strategy

1. **Phase 1**: Deploy server-side uv support
2. **Phase 2**: Update client to use lightweight bundles
3. **Phase 3**: Remove client-side uv dependency
4. **Phase 4**: Optimize server-side caching and performance

## Example Usage

```python
# Client code remains unchanged
@verifier(extra_requirements=["torch==2.3.0"])
def check_model_accuracy(env, threshold: float) -> float:
    import torch
    # ... verifier logic
    return accuracy_score

# Remote execution still works the same
result = await check_model_accuracy.remote(env, 0.95)
```

The user experience is identical, but the underlying architecture is much more robust and efficient.
