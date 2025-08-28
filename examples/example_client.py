#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import asyncio
import fleet
from dotenv import load_dotenv

load_dotenv()


async def main():
    fleet = fleet.AsyncFleet()

    environments = await fleet.list_envs()
    print("Environments:", len(environments))

    # Create a new instance
    env = await fleet.make("fira")
    print(f"New Instance: {env.instance_id} ({env.region})")

    response = await env.reset(seed=42)
    print("Reset response:", response)

    print(await env.resources())

    sqlite = env.db()
    print("SQLite:", await sqlite.describe())

    print("Query:", await sqlite.query("SELECT * FROM users"))

    sqlite = await env.state("sqlite://current").describe()
    print("SQLite:", sqlite)

    browser = env.browser()
    print("CDP URL:", await browser.cdp_url())
    print("Devtools URL:", await browser.devtools_url())

    # Delete the instance
    await fleet.delete(env.instance_id)


if __name__ == "__main__":
    asyncio.run(main())
