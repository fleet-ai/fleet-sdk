#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import asyncio
import fleet
from dotenv import load_dotenv

load_dotenv()


async def main():
    # Create a new instance
    env = await fleet.env.make_async("fira:v1.3.2")
    print(f"New Instance: {env.instance_id} ({env.region})")
    print("URL:", env.urls.app)

    print(await env.resources())

    sqlite = env.db("action_log")
    print("SQLite:", await sqlite.describe())

    print("Query:", await sqlite.query("SELECT * FROM action_log"))

    await env.close()


if __name__ == "__main__":
    asyncio.run(main())
