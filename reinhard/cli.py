import json
import logging
import os
import typing


import yaml


from reinhard import client
from reinhard import config

CONFIG_PARSERS = {"yaml": yaml.safe_load, "json": json.load}


def parse_config(
    config_path: typing.Optional[str] = None,
    config_marshaler: typing.Callable[[dict], typing.Any] = config.ExtendedOptions.from_dict,
):
    if config_path is None:
        return config_marshaler({})

    file_type = config_path.split(".")[-1].lower()
    parser = CONFIG_PARSERS.get(file_type)
    if parser is None:
        raise TypeError(f"Unsupported file type received `{config_path.split('.')[-1]}`")

    if config_path is not None:
        with open(config_path, "r") as file:
            return config_marshaler(parser(file))


def main():
    config_path = os.getenv("REINHARD_CONFIG_FILE")

    if config_path is None:
        for file_type in CONFIG_PARSERS.keys():
            config_path = f"config.{file_type}"
            if os.path.exists(config_path):
                break
        else:
            logging.getLogger(__name__).warning("Config file not found, initiating without a config.")
            # FileNotFoundError
            config_path = None

    config_obj: config.ExtendedOptions = parse_config(config_path)

    logging.basicConfig(
        level=config_obj.bot.log_level,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    bot_client = client.BotClient(config_obj)
    bot_client.run(token=config_obj.bot.token)
