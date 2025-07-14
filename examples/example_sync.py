#!/usr/bin/env python3
"""Example demonstrating browser control with Fleet Manager Client."""

import fleet as flt
from dotenv import load_dotenv

load_dotenv()


def main():
    environments = flt.env.list_envs()
    print("Environments:", len(environments))

    instances = flt.env.list_instances()
    print("Instances:", len(instances))

    # Create a new instance
    env = flt.env.make("hubspot:v1.2.7")
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
