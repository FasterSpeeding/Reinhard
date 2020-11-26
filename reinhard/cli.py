from __future__ import annotations

import os
import pathlib

# from hikari import intents  # TODO: handle intents in config
from hikari.impl import bot as bot_module

from reinhard import client as client_module
from reinhard import config as config_


def main() -> None:
    config_location = os.getenv("REINHARD_CONFIG_FILE")
    config_path = pathlib.Path(config_location) if config_location else None

    if config_path and not config_path.exists():
        raise RuntimeError("Invalid configuration given in environment variables")

    config = config_.get_config_from_file(config_path)
    bot = bot_module.BotApp(config.tokens.bot, logs=config.log_level)
    client = client_module.Client(
        bot,
        password=config.database.password,
        host=config.database.host,
        user=config.database.user,
        database=config.database.database,
        port=config.database.port,
        prefixes=config.prefixes,
    )

    client_module.add_components(client, config)
    bot.run()


if __name__ == "__main__":
    main()
