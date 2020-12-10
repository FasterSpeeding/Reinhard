from __future__ import annotations

# from hikari import intents as intents_  # TODO: handle intents in config
from hikari.impl import bot as bot_module

from reinhard import client as client_module
from reinhard import config as config_


def main() -> None:
    config = config_.load_config()
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
    client_module.add_components(client, config=config)
    bot.run()


if __name__ == "__main__":
    main()
