#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import asyncio
import fleet as flt


async def main():
    environments = await flt.env.list_envs()
    print("Environments:", len(environments))

    # Create a new instance
    env = await flt.env.make("hubspot:v1.2.7")
    print("New Instance:", env.instance_id)

    response = await env.reset(seed=42)
    print("Reset response:", response)

    print(await env.resources())

    sqlite = env.db()
    print("SQLite:", await sqlite.describe())

    print("Query:", await sqlite.query("SELECT * FROM users"))

    sqlite = await env.state("sqlite://current").describe()
    print("SQLite:", sqlite)

    await env.browser().start(width=1920, height=1080)

    browser_connection = await env.browser().describe()
    print("CDP Page URL:", browser_connection.cdp_page_url)
    print("CDP Browser URL:", browser_connection.cdp_browser_url)
    print("CDP Devtools URL:", browser_connection.cdp_devtools_url)

    # Delete the instance
    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
