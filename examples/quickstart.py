#!/usr/bin/env python3
"""
Fleet SDK Quickstart Example.

This example demonstrates basic usage of the Fleet SDK for environment management.
"""

import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

from fleet import AsyncFleet


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Main example function."""

    # Initialize the Fleet client
    fleet_client = AsyncFleet()

    # 1. List available environments
    print("\n📋 Available environments:")
    try:
        environments = await fleet_client.list_envs()
        for env in environments:
            print(f"  - {env.env_key}: {env.name}")
            print(f"    Description: {env.description}")
            print(f"    Default version: {env.default_version}")
            print(f"    Available versions: {', '.join(env.versions.keys())}")
    except Exception as e:
        print(f"❌ Failed to list environments: {e}")
        return

    # 2. Create a new environment instance
    print("\n🚀 Creating new environment...")
    try:
        env = await fleet_client.make("fira:v1.3.1")
        print(f"✅ Environment created with instance ID: {env.instance_id}")

        # TODO: Execute a simple action
        print("\n⚡ Executing a simple action...")
        action = {"type": "test", "data": {"message": "Hello Fleet!"}}
        state, reward, done = await env.instance.step(action)
        print(f"✅ Action executed successfully!")
        print(f"   Reward: {reward}")
        print(f"   Done: {done}")
        print(f"   State keys: {list(state.keys())}")

        # Clean up
        print("\n🧹 Cleaning up...")
        await env.close()
        print("✅ Environment closed")

    except Exception as e:
        print(f"❌ Environment creation failed: {e}")
        return

    # 3. List running instances
    print("\n🏃 Listing running instances...")
    try:
        instances = await fleet_client.instances(status="running")
        if instances:
            print(f"Found {len(instances)} running instances:")
            for instance in instances:
                print(
                    f"  - {instance.instance_id}: {instance.env_key} ({instance.status})"
                )
        else:
            print("No running instances found")
    except Exception as e:
        print(f"❌ Failed to list instances: {e}")

    # 4. Connect to an existing instance (if any)
    print("\n🔗 Connecting to existing instance...")
    try:
        # Only get running instances
        running_instances = await fleet_client.instances(status="running")
        if running_instances:
            # Find a running instance that's not the one we just created/deleted
            target_instance = running_instances[0]
            print(f"Connecting to running instance: {target_instance.instance_id}")

            env = await fleet_client.instance(target_instance.instance_id)
            print(f"✅ Connected to instance: {env.instance_id}")

            # Execute an action on the existing instance
            action = {"type": "ping", "data": {"timestamp": "2024-01-01T00:00:00Z"}}
            state, reward, done = await env.instance.step(action)
            print(f"✅ Action executed on existing instance!")
            print(f"   Reward: {reward}")
            print(f"   Done: {done}")

            # Clean up (this will delete the instance)
            await env.close()
            print("✅ Connection closed (instance deleted)")
        else:
            print("No running instances to connect to")
    except Exception as e:
        print(f"❌ Failed to connect to existing instance: {e}")

    print("\n🎉 Quickstart complete!")


if __name__ == "__main__":
    asyncio.run(main())
