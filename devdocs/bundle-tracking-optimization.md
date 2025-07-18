# Bundle Tracking Optimization

## Overview

The **Bundle Tracking Optimization** dramatically reduces network traffic by sending verifier bundles only once per environment, rather than with every remote call. This optimization is implemented client-side and provides 63-96% reduction in network traffic for repeated calls.

## Problem Statement

### Before Optimization

```python
await verifier.remote(env, 5)   # Send 2KB bundle + execute
await verifier.remote(env, 10)  # Send 2KB bundle + execute (redundant!)
await verifier.remote(env, 15)  # Send 2KB bundle + execute (redundant!)
# Total: 6KB network traffic
```

### After Optimization

```python
await verifier.remote(env, 5)   # Send 2KB bundle + execute (first time)
await verifier.remote(env, 10)  # Send 96 bytes (verifier_id + args) + execute
await verifier.remote(env, 15)  # Send 96 bytes (verifier_id + args) + execute
# Total: ~2.2KB network traffic (63% reduction)
```

## Implementation Details

### Client-Side Bundle Tracking

#### 1. Per-Verifier Environment Tracking

```python
class AsyncVerifiedFunction:
    def __init__(self, func, name, verifier_id, extra_requirements=None):
        self.func = func
        self.name = name
        self.verifier_id = verifier_id  # Unique UUID per verifier
        self.extra_requirements = extra_requirements or []
        self._bundler = FunctionBundler()
        self._bundle_sent_to_envs = set()  # Track environments that have our bundle
```

#### 2. Smart Bundle Sending Logic

```python
async def remote(self, env, *args, **kwargs) -> float:
    env_id = self._get_env_id(env)

    if env_id not in self._bundle_sent_to_envs:
        # First time sending to this environment - send bundle
        bundle_data = self._bundler.create_bundle(self.func, self.extra_requirements, self.verifier_id)
        response = await env.instance.execute_verifier_remote(
            bundle_data=bundle_data,
            verifier_id=self.verifier_id,
            args=args,
            kwargs=kwargs
        )
        self._bundle_sent_to_envs.add(env_id)
    else:
        # Bundle already sent - just execute using verifier_id
        response = await env.instance.execute_verifier_by_id(
            verifier_id=self.verifier_id,
            args=args,
            kwargs=kwargs
        )

    return self._process_result(response)
```

#### 3. Environment Identification

```python
def _get_env_id(self, env) -> str:
    """Generate unique identifier for environment."""
    if hasattr(env, 'instance') and hasattr(env.instance, 'base_url'):
        return f"{env.instance.base_url}"
    else:
        return str(id(env))  # Fallback to object ID
```

#### 4. Error Recovery

```python
try:
    response = await env.instance.execute_verifier_by_id(verifier_id, args, kwargs)
except Exception as e:
    if self._is_bundle_not_found_error(e):
        # Server restart detected - remove from tracking and retry
        self._bundle_sent_to_envs.discard(env_id)
        return await self.remote(env, *args, **kwargs)
    else:
        raise
```

### Enhanced Bundle Manifest

Bundles now include the verifier_id for server-side identification:

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

## Server-Side Requirements

### API Endpoints

#### 1. execute_verifier_remote (Enhanced)

```python
@app.post("/verifiers/execute-remote")
async def execute_verifier_remote(
    bundle_data: bytes,
    verifier_id: str,
    args: tuple,
    kwargs: dict
):
    # Extract and process bundle
    # Store processed environment by verifier_id
    # Execute function
    pass
```

#### 2. execute_verifier_by_id (New)

```python
@app.post("/verifiers/execute-by-id")
async def execute_verifier_by_id(
    verifier_id: str,
    args: tuple,
    kwargs: dict
):
    # Look up cached bundle by verifier_id
    # Execute function using cached environment
    pass
```

### Bundle Storage

```python
class BundleManager:
    def __init__(self):
        self.bundles = {}  # verifier_id -> processed_environment

    async def store_bundle(self, verifier_id: str, bundle_data: bytes):
        env = await self._process_bundle(bundle_data)
        self.bundles[verifier_id] = env

    async def execute_by_id(self, verifier_id: str, args: tuple, kwargs: dict):
        if verifier_id not in self.bundles:
            raise ValueError(f"Bundle not found for verifier {verifier_id}")
        return await self._execute_in_environment(self.bundles[verifier_id], args, kwargs)
```

## Performance Benefits

### Call Patterns

- **First call**: Full bundle sent (~2KB)
- **Subsequent calls**: Only verifier_id + args (~96 bytes)
- **Different environments**: Each gets bundle once
- **Server restart**: Automatic recovery and re-send

## Usage Examples

### Single Environment

```python
@verifier(extra_requirements=["torch==2.3.0"])
def validate_model(env, threshold: float) -> float:
    import torch
    # ... validation logic
    return accuracy_score

# Usage is identical - optimization is transparent
env = fleet.env.make("production")

result1 = await validate_model.remote(env, 0.95)  # Sends bundle (2KB)
result2 = await validate_model.remote(env, 0.90)  # Uses cached bundle (96 bytes)
result3 = await validate_model.remote(env, 0.85)  # Uses cached bundle (96 bytes)
```

### Multiple Environments

```python
env1 = fleet.env.make("production")
env2 = fleet.env.make("staging")

# Each environment gets bundle once
await validate_model.remote(env1, 0.95)  # Send bundle to env1
await validate_model.remote(env2, 0.95)  # Send bundle to env2
await validate_model.remote(env1, 0.90)  # Use cached bundle on env1
await validate_model.remote(env2, 0.90)  # Use cached bundle on env2
```

### Error Recovery

```python
# Server restarts between calls
await validate_model.remote(env, 0.95)  # Sends bundle
# Server restarts here
await validate_model.remote(env, 0.90)  # Detects "bundle not found", automatically re-sends
```

## Key Features

### 1. **Transparent Optimization**

- No changes to user code required
- Same API as before
- Automatic optimization

### 2. **Per-Environment Tracking**

- Each environment tracked independently
- Multiple environments supported
- Environment identified by base URL

### 3. **Automatic Error Recovery**

- Detects server restarts
- Automatically re-sends bundles when needed
- Graceful degradation

### 4. **Unique Verifier Identification**

- Each verifier gets unique UUID
- Server can identify bundles by verifier_id
- Prevents bundle conflicts

## Edge Cases Handled

### Server Restart

- **Detection**: "Bundle not found" error patterns
- **Recovery**: Remove from tracking, retry with bundle
- **Transparency**: User code unaware of restart

### Multiple Verifiers

- **Isolation**: Each verifier has own tracking
- **Identification**: Unique verifier_id per function
- **Caching**: Independent bundle caches

### Network Errors

- **Fallback**: Standard error handling
- **Retry**: Automatic retry with bundle if needed
- **Robustness**: Graceful error recovery

## Benefits Summary

1. **63-96% network reduction** for repeated calls
2. **Transparent optimization** - no user code changes
3. **Automatic error recovery** - handles server restarts
4. **Multi-environment support** - independent tracking per environment
5. **Production ready** - comprehensive testing and error handling

The bundle tracking optimization makes remote verifier execution highly efficient for production workloads where verifiers are called repeatedly on the same environment.
