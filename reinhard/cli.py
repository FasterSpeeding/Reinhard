import logging
import os


import yaml


from reinhard import client
from reinhard import config


def main():
    config_path = os.getenv("REINHARD_CONFIG_FILE", "config.yaml")

    with open(config_path, "r") as file:
        config_obj = config.Config.from_dict(yaml.safe_load(file))

    logging.basicConfig(
        level=config_obj.log_level,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    bot_client = client.BotClient(config_obj, modules=["reinhard.modules.stars"])
    bot_client.run()
