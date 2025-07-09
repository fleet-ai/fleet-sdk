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

    response = await instance.env.reset(flt.ResetRequest(seed=42))
    print("Reset response:", response)

    print(await instance.env.resources())

    sqlite = instance.env.db("current")
    print("SQLite:", await sqlite.describe())

    print("Query:", await sqlite.query("SELECT * FROM users"))

    sqlite = await instance.env.state("sqlite://current").describe()
    print("SQLite:", sqlite)

    await instance.env.browser("cdp").start(
        flt.ChromeStartRequest(resolution="1920,1080")
    )

    browser = await instance.env.browser("cdp").describe()
    print("CDP Page URL:", browser.cdp_page_url)
    print("CDP Browser URL:", browser.cdp_browser_url)
    print("CDP Devtools URL:", browser.cdp_devtools_url)

    # Delete the instance
    instance = await fleet.delete(instance.instance_id)
    print("Instance deleted:", instance.terminated_at)


if __name__ == "__main__":
    asyncio.run(main())
