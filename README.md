# Fleet SDK

[![PyPI version](https://img.shields.io/pypi/v/fleet-python.svg)](https://pypi.org/project/fleet-python/)
[![Python versions](https://img.shields.io/pypi/pyversions/fleet-python.svg)](https://pypi.org/project/fleet-python/)
[![License](https://img.shields.io/pypi/l/fleet-python.svg)](https://pypi.org/project/fleet-python/)

The Fleet Python SDK provides programmatic access to Fleet's environment infrastructure.

## Installation

```bash
pip install fleet-python
```

## API Key Setup

Get your API key from the [Fleet Dashboard](https://fleetai.com/dashboard/api-keys), then set it as an environment variable:

```bash
export FLEET_API_KEY="sk_your_key_here"
```

## Quick Start

```python
import fleet

async def main():
    # Load a task
    tasks = await fleet.load_tasks_async(
        keys=["task_abcdef"]
    )
    task = tasks[0]

    # Create an environment from the task
    env = await fleet.env.make_async(
        env_key=task.env_key,
        data_key=task.data_key,
        env_variables=task.env_variables,
        ttl_seconds=7200,
        run_id="run-123",
    )

    # Access the environment URL
    print(env.urls.app[0])

    # ... interact with the environment ...

    # Verify task completion
    result = await task.verify_detailed_async(env.instance_id)
    print(result)

    # Clean up
    await env.close()
```

## Loading Tasks

### By Task Keys

```python
tasks = await fleet.load_tasks_async(
    keys=["task_abcdef"]
)
```

### By Project Key

```python
tasks = await fleet.load_tasks_async(project_key="my-project")
```

## Creating Environments

```python
env = await fleet.env.make_async(
    env_key=task.env_key,
    data_key=task.data_key,
    env_variables=task.env_variables,
    ttl_seconds=7200,
    run_id="run-123",
)
```

### With Heartbeats (Optional)

Optionally enable heartbeats to keep environments alive during long-running operations:

```python
env = await fleet.env.make_async(
    env_key=task.env_key,
    data_key=task.data_key,
    env_variables=task.env_variables,
    ttl_seconds=10800,
    heartbeat_interval=30,  # seconds
)
```

Send heartbeats to keep the environment alive:

```python
# Via the environment object
await env.heartbeat()

# Or via instance ID
await fleet.env.heartbeat_async(instance_id)
```

Heartbeats are optional. If `heartbeat_interval` is not set, the instance lifetime is controlled solely by `ttl_seconds`. If heartbeats are enabled and missed 3 consecutive times, the instance will be terminated. Heartbeats take precedence over the TTL.

## Instance Management

### List Instances

```python
# List all instances for a run
instances = await fleet.env.list_instances_async(run_id="run-123")

# List all instances for your profile
instances = await fleet.env.list_instances_async(profile_id="self")
```

### Close Instances

```python
# Close all instances for a run
await fleet.env.close_all_async(run_id="run-123")

# Close all instances for your profile
await fleet.env.close_all_async(profile_id="self")

# Close a specific instance by ID
await fleet.env.close_async("bc8954c2")
```

`"self"` is an alias for the profile associated with your `FLEET_API_KEY`.

## Account Information

View your current account details including team info, instance limits, and profile ID:

```python
account = await fleet.env.account_async()
```

Returns:

```json
{
  "team_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "team_name": "My Team",
  "instance_limit": 32000,
  "instance_count": 924,
  "profile_id": "11111111-2222-3333-4444-555555555555",
  "profile_name": "Jane Doe"
}
```

## Run Tracking

Track active and past runs:

```python
# List active runs
runs = await fleet.env.list_runs_async()

# List all runs (active and inactive)
runs = await fleet.env.list_runs_async(status="all")

# Filter by profile
runs = await fleet.env.list_runs_async(profile_id="self")
```

Returns:

```json
[
  {
    "run_id": "run-123",
    "running_count": 0,
    "total_count": 4,
    "first_created_at": "2025-10-24T09:48:47.152387",
    "last_created_at": "2025-10-24T09:55:19.284294",
    "profile_id": "11111111-2222-3333-4444-555555555555"
  }
]
```

## Task Verification

Verify task completion and get detailed results:

```python
result = await task.verify_detailed_async(env.instance_id)
print(result)
```

Returns:

```json
{
  "key": "task_abcdef",
  "version": 4,
  "success": true,
  "result": 1.0,
  "error": null,
  "execution_time_ms": 2291,
  "stdout": ""
}
```

On failure, `stdout` contains detailed verification errors:

```json
{
  "key": "task_abcdef",
  "version": 4,
  "success": true,
  "result": 0,
  "error": null,
  "execution_time_ms": 2291,
  "stdout": "Verification errors: [\"Expected field to be 'value', got None\", \"Form not marked as complete\"]"
}
```

## Complete Example

```python
import fleet
import asyncio

async def main():
    # Load tasks from a project
    tasks = await fleet.load_tasks_async(project_key="my-project")
    
    for task in tasks:
        # Create environment
        env = await fleet.env.make_async(
            env_key=task.env_key,
            data_key=task.data_key,
            env_variables=task.env_variables,
            ttl_seconds=7200,
            run_id="my-evaluation-run",
        )
        
        try:
            # Access the environment URL
            print(env.urls.app[0])
            
            # ... run your agent ...
            
            # Verify task completion
            result = await task.verify_detailed_async(env.instance_id)
            print(f"Task {task.key}: score={result['result']}")
            
        finally:
            await env.close()
    
    # Clean up all instances from this run
    await fleet.env.close_all_async(run_id="my-evaluation-run")

if __name__ == "__main__":
    asyncio.run(main())
```
