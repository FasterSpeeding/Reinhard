import asyncio
import os


import yaml


from reinhard import client
from reinhard import config


async def async_main(config_obj: config.Config):
    bot_client = client.BotClient(config_obj)

    await bot_client.run()


def main():
    config_path = os.getenv("REINHARD_CONFIG_FILE", "config.yaml")

    with open(config_path, "r") as file:
        config_obj = config.Config.parse_obj(yaml.safe_load(file))

    asyncio.run(async_main(config_obj))
