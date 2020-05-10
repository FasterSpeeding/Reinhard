from __future__ import annotations

import json
import logging
import os
import typing

import yaml
from hikari.clients import stateless

from reinhard import client
from reinhard import config

CONFIG_PARSERS = {"yaml": yaml.safe_load, "json": json.load}


def parse_config(
    config_path: typing.Optional[str] = None,
    config_marshaller: typing.Callable[[dict], typing.Any] = config.ExtendedOptions.deserialize,
):
    if config_path is None:
        return config_marshaller({})

    file_type = config_path.split(".")[-1].lower()
    if (parser := CONFIG_PARSERS.get(file_type)) is None:
        raise TypeError(f"Unsupported file type received `{config_path.split('.')[-1]}`")

    if config_path is not None:
        with open(config_path, "r") as file:
            return config_marshaller(parser(file))


def main():
    if (config_path := os.getenv("REINHARD_CONFIG_FILE")) is None:
        for file_type in CONFIG_PARSERS.keys():
            if os.path.exists(config_path := f"config.{file_type}"):
                break
        else:
            logging.getLogger(__name__).warning("Config file not found, initiating without a config.")
            # FileNotFoundError
            config_path = None

    config_obj: config.ExtendedOptions = parse_config(config_path)

    logging.basicConfig(
        level=config_obj.log_level,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_logger = logging.FileHandler("bot.log")
    file_logger.setLevel(config_obj.file_log_level)
    file_logger.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logging.getLogger().addHandler(file_logger)

    bot_client = stateless.StatelessBot(config=config_obj)
    client.CommandClient(bot_client, modules=["reinhard.modules.sudo"])
    bot_client.run()
