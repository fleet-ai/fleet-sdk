#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import asyncio
import fleet as flt


async def main():
    fleet = flt.AsyncFleet()

    environments = await fleet.list_envs()
    print("Environments:", len(environments))

    # Create a new instance
    instance = await fleet.make(
        flt.InstanceRequest(env_key="hubspot", version="v1.2.7")
    )
    print("New Instance:", instance.instance_id)

    environment = await fleet.environment(instance.env_key)
    print("Environment Default Version:", environment.default_version)

    response = await instance.env.reset()
    print("Reset response:", response)

    print(await instance.env.resources())

    sqlite = instance.env.sqlite("current")
    print("SQLite:", await sqlite.describe())

    print("Query:", await sqlite.query("SELECT * FROM users"))

    sqlite = await instance.env.state("sqlite://current").describe()
    print("SQLite:", sqlite)

    browser = await instance.env.browser("cdp").describe()
    print("CDP URL:", browser.url)
    print("CDP Devtools URL:", browser.devtools_url)

    # Delete the instance
    instance = await fleet.delete(instance.instance_id)
    print("Instance deleted:", instance.terminated_at)


if __name__ == "__main__":
    asyncio.run(main())
