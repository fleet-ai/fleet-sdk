import asyncio
import fleet
from dotenv import load_dotenv

load_dotenv()


async def main():
    print(f"Importing tasks... {(await fleet.env.account_async()).team_name}")
    await fleet._async.import_tasks(
        "6bb6c6b6-36a8-4407-ba66-6908e42069c8.json", project_key="amazon"
    )


if __name__ == "__main__":
    asyncio.run(main())
