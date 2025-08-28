#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import fleet
from dotenv import load_dotenv

load_dotenv()


def main():
    environments = fleet.env.list_envs()
    print("Environments:", len(environments))

    instances = fleet.env.list_instances(status="running")
    print("Instances:", len(instances))

    # Create a new instance
    env = fleet.env.make("hubspot")
    print("New Instance:", env.instance_id)

    response = env.reset(seed=42)
    print("Reset response:", response)

    print(env.resources())

    sqlite = env.db()
    print("SQLite:", sqlite.describe())

    print("Query:", sqlite.query("SELECT * FROM users"))

    sqlite = env.state("sqlite://current").describe()
    print("SQLite:", sqlite)

    browser = env.browser()
    print("CDP URL:", browser.cdp_url())
    print("Devtools URL:", browser.devtools_url())

    # Delete the instance
    env.close()


if __name__ == "__main__":
    main()
