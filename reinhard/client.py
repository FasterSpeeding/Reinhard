from __future__ import annotations
import asyncpg
import logging
import time
import typing


from hikari.internal_utilities import loggers
from hikari.orm import models


from reinhard import command_client
from reinhard import config
from reinhard import sql

logging.getLogger().setLevel(logging.DEBUG)


class BotClient(command_client.CommandClient):
    def __init__(
        self,
        config: config.Config,
        *,
        modules: typing.List[str] = None,
        options: typing.Optional[command_client.CommandsClientOptions] = None,
    ):
        super().__init__(
            prefixes=config.prefixes or ["."],
            token=config.token,
            modules=modules,
            options=options,
        )
        self.config = config
        self.logger = loggers.get_named_logger(self)
        self.sql: typing.Optional[asyncpg.pool.Pool] = None
        self.sql_scripts = sql.CachedScripts()

    async def on_message_reaction_add(
        self, reaction: models.reactions.Reaction, user: models.users.User
    ):
        print(reaction.emoji == "\N{WHITE MEDIUM STAR}")
        if reaction.emoji == "\N{WHITE MEDIUM STAR}":
            print()

    async def on_message_reaction_remove(
        self, reaction: models.reactions.Reaction, user: models.users.User
    ):
        print(reaction.emoji == "\N{WHITE MEDIUM STAR}")
        if reaction.emoji == "\N{WHITE MEDIUM STAR}":
            print()

    @command_client.Command(level=42)
    async def echo(
        self, message: models.messages.Message, args
    ) -> typing.Optional[str]:
        if args:
            return args

    @command_client.Command
    async def error(self, message: models.messages.Message, args) -> None:
        raise Exception("This is an exception, get used to it.")

    async def error_handler(
        self, e: BaseException, message: models.messages.Message
    ) -> None:
        await self._fabric.http_api.create_message(
            str(message.channel_id),
            embed={
                "title": "An exception occured",
                "color": 15746887,
                "description": f"```python\n{str(e)[:1950]}```",
            },
        )

    @command_client.Command()
    async def ping(self, message: models.messages.Message, args) -> None:
        message_sent = time.perf_counter()
        message_obj = await self._fabric.http_api.create_message(
            str(message.channel_id), content="Nyaa!"
        )
        api_latency = round((time.perf_counter() - message_sent) * 1000, 2)
        gateway_latency = round(self._fabric.gateways[None].heartbeat_latency * 1000, 2)
        await self._fabric.http_api.edit_message(
            channel_id=message_obj["channel_id"],
            message_id=message_obj["id"],
            content=f"Pong!:ping_pong:\nAPI: {api_latency}\nGateway:{gateway_latency}",
        )

    async def run(self) -> None:
        self.sql = await asyncpg.create_pool(**self.config.database.dict())
        await super().run()
