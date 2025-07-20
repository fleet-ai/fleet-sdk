#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import asyncio
import fleet as flt
from dotenv import load_dotenv

load_dotenv()


async def main():
    env = await flt.env.make_async("hubspot")


if __name__ == "__main__":
    asyncio.run(main())
