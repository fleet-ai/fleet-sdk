import asyncio
import fleet as flt
from nova_act import NovaAct, ActResult


async def main() -> None:
    instance = await flt.env.make("hubspot")

    def run_nova() -> ActResult:
        with NovaAct(starting_page=instance.urls.app) as nova:
            return nova.act("Create a deal")

    await asyncio.to_thread(run_nova)
    await instance.close()


if __name__ == "__main__":
    asyncio.run(main())
