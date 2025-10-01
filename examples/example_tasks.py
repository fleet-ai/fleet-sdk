import fleet
from dotenv import load_dotenv

load_dotenv()


def main():
    account = fleet.env.account()
    print(account)

    tasks = fleet.load_tasks(team_id="5ca40f9f-9899-4bee-b194-6974138a4f12")
    print(f"Loaded {len(tasks)} tasks")

    # Save tasks to JSON file
    import json

    with open(f"{account.team_id}.json", "w") as f:
        json.dump([task.model_dump() for task in tasks], f, indent=2)

    print(f"Saved {len(tasks)} tasks to saved_tasks.json")


if __name__ == "__main__":
    main()
