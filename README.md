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
import fleet as flt

# Create environment by key
env = flt.env.make("fira")

# Reset environment with seed and options
env.reset(
    seed=42,
    timestamp=datetime.now()
)

# Access environment state ('crm' is the resource id for a sqlite database)
sql = env.state("sqlite://crm")
sql.exec("UPDATE customers SET status = 'active' WHERE id = 123")

# Clean up
env.close()
```

## Environment Management

### Creating Instances

```python
# Create environment instance with explicit version
env = flt.env.make("fira:v1.2.5")

# Create environment instance with default (latest) version
env = flt.env.make("fira")

```

### Connecting to Existing Instances

```python
# Connect to a running instance
env = flt.env.get("env_instance_id")

# List all running instances
instances = flt.env.list_instances()
for instance in instances:
    print(f"Instance: {instance.instance_id}")
    print(f"Type: {instance.environment_type}")
    print(f"Status: {instance.status}")

# Filter instances by status (running, pending, stopped, error)
running_instances = flt.env.list_instances(status_filter="running")

# List available environment types
available_envs = flt.env.list_envs()
```

## Development

### Code Structure

This SDK uses `unasync` to maintain both async and sync versions of the code from a single source:

- **`fleet/_async/`** - The source code (async version) - **EDIT THIS**
- **`fleet/`** - The generated sync version - **DO NOT EDIT** (auto-generated)

### Making Changes

⚠️ **Important**: All code modifications should be made in the `fleet/_async/` directory. The synchronous versions in `fleet/` are automatically generated.

1. Make your changes in `fleet/_async/`
2. Run `make unasync` to generate the sync versions
3. Test both async and sync versions
4. Commit all changes (both async source and generated sync files)

Example workflow:
```bash
# Edit the async source files
vim fleet/_async/client.py

# Generate sync versions
make unasync

# Run tests
python examples/example.py

# Commit both source and generated files
git add fleet/_async/ fleet/
git commit -m "Add new feature"
```

### Why This Structure?

- Single source of truth for business logic
- Automatic sync/async API generation
- Consistent behavior between sync and async versions
- Easier maintenance and testing
