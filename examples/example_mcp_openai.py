import fleet as flt
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()


def main():
    env = flt.env.make("fira:v1.3.3")
    print("Created environment:", env.urls.app)
    print("MCP URL:", env.mcp.url)

    response = client.responses.create(
        model="gpt-4.1",
        tools=[env.mcp.openai()],
        input="Get the current authorized user.",
    )

    print(response.output_text)

    env.close()


if __name__ == "__main__":
    main()
