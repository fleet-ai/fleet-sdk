import asyncio
import fleet as flt
from nova_act import NovaAct, ActResult


async def main():
    instance = await flt.env.make("hubspot")
    cdp_url = await instance.browser().cdp_url()

    loop = asyncio.get_event_loop()

    def run_nova() -> ActResult:
        with NovaAct(
            starting_page=instance.urls.app,
            cdp_endpoint_url=cdp_url,
            preview={"playwright_actuation": True},
        ) as nova:
            future = asyncio.run_coroutine_threadsafe(
                instance.browser().devtools_url(), loop
            )
            print("Devtools URL:", future.result())
            return nova.act("Create a deal")

    await asyncio.to_thread(run_nova)
    await instance.close()


if __name__ == "__main__":
    asyncio.run(main())
