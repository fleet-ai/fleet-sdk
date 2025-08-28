# Fleet SDK

The Fleet Python SDK provides programmatic access to Fleet's environment infrastructure.

## Installation

Install the Fleet SDK using pip:

```bash
pip install fleet-python
```

## API Key Setup

Fleet requires an API key for authentication. You can obtain one from the [Fleet Platform](https://fleetai.com/dashboard/api-keys).

Set your API key as an environment variable:

```bash
export FLEET_API_KEY="sk_your_key_here"
```

## Basic Usage

```python
import fleet
import datetime

# Create environment by key
env = fleet.env.make("fira")

# Reset environment with seed and options
env.reset(
    seed=42,
    timestamp=int(datetime.datetime.now().timestamp())
)

# Access environment state ('current' is the resource id for a sqlite database)
sql = env.state("sqlite://current")
sql.exec("UPDATE customers SET status = 'active' WHERE id = 123")

# Clean up
env.close()
```

## Environment Management

### Creating Instances

```python
# Create environment instance with explicit version
env = fleet.env.make("fira:v1.2.5")

# Create environment instance with default (latest) version
env = fleet.env.make("fira")

```

### Connecting to Existing Instances

```python
# Connect to a running instance
env = fleet.env.get("env_instance_id")

# List all running instances
instances = fleet.env.list_instances()
for instance in instances:
    print(f"Instance: {instance.instance_id}")
    print(f"Type: {instance.environment_type}")
    print(f"Status: {instance.status}")

# Filter instances by status (running, pending, stopped, error)
running_instances = fleet.env.list_instances(status_filter="running")

# List available environment types
available_envs = fleet.env.list_envs()
```
