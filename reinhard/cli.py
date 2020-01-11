import asyncio
import os


import yaml


from reinhard.modules import stars
from reinhard import client
from reinhard import config


async def async_main(config_obj: config.Config):
    bot_client = client.BotClient(config_obj, modules=[stars.StarboardModule])

    await bot_client.run()


def main():
    config_path = os.getenv("REINHARD_CONFIG_FILE", "config.yaml")

    with open(config_path, "r") as file:
        config_obj = config.Config.from_dict(yaml.safe_load(file))

    asyncio.run(async_main(config_obj))
