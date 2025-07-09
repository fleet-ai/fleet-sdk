#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import asyncio
import fleet as flt


async def main():
    fleet = flt.AsyncFleet()

    environments = await fleet.environments()
    print("Environments:", len(environments))

    instances = await fleet.instances(status="running")
    print("Instances:", len(instances))

    instance = await fleet.instance("16fdbc96")
    print("Instance:", instance.instance_id)
    print("Instance Environment:", instance.env_key)

    environment = await fleet.environment(instance.env_key)
    print("Environment Default Version:", environment.default_version)

    response = await instance.env.reset()
    print("Reset response:", response)

    await instance.env.resources()

    sqlite = await instance.env.sqlite("current").describe()
    print("SQLite:", sqlite)

    sqlite = await instance.env.state("sqlite://current").describe()
    print("SQLite:", sqlite)

    print(await instance.env.browser("cdp").describe())

    # Create a new instance
    instance = await fleet.make(flt.InstanceRequest(env_key=instance.env_key))
    print("New Instance:", instance.instance_id)

    # Delete the instance
    instance = await fleet.delete(instance.instance_id)
    print("Instance deleted:", instance.terminated_at)


if __name__ == "__main__":
    asyncio.run(main())
