import fleet as flt
from dotenv import load_dotenv

load_dotenv()


client = flt.Fleet()


def main():
    env = flt.env.make("fira")

    tasks = client.load_tasks(env_key="fira")
    print(f"Loaded {len(tasks)} tasks")

    for i, task in enumerate(tasks):
        print(f"\nTask {i + 1}:")
        print(f"  Key: {task.key}")
        print(f"  Prompt: {task.prompt[:80]}...")
        print(f"  Verifier: {task.verifier_func[:80]}...")

        print(f"  Verifier: {task.verifier.key}")
        print("  Running verifier...")
        try:
            score = task.verify(env)
            print(f"  ✓ Score: {score}")
        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {e}")

        print("-" * 60)


if __name__ == "__main__":
    main()
