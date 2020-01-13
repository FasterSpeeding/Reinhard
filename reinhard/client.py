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
        self, bot_config: config.Config, *, modules: typing.List[str] = None,
    ):
        super().__init__(
            prefixes=bot_config.prefixes, token=bot_config.token, modules=modules, options=bot_config.options,
        )
        self.config = bot_config
        self.logger = loggers.get_named_logger(self)
        self.sql_pool: typing.Optional[asyncpg.pool.Pool] = None
        self.sql_scripts = sql.CachedScripts(pattern=".*schema.sql")

    @command_client.Command(level=5)
    async def error(self, message: models.messages.Message, args) -> None:
        raise Exception("This is an exception, get used to it.")

    async def error_handler(self, e: BaseException, message: models.messages.Message) -> None:
        await self._fabric.http_api.create_message(
            str(message.channel_id),
            embed={
                "title": "An exception occured",
                "color": 15746887,
                "description": f"```python\n{str(e)[:1950]}```",
            },
        )

    @command_client.Command(level=5)
    async def echo(self, _, args) -> typing.Optional[str]:
        return args

    @command_client.Command(level=5)
    async def eval(self, message: models.messages.Message, args):
        args.strip(" ").strip("```")

    @command_client.Command
    async def ping(self, message: models.messages.Message, _) -> None:
        message_sent = time.perf_counter()
        message_obj = await self._fabric.http_api.create_message(str(message.channel_id), content="Nyaa!")
        api_latency = round((time.perf_counter() - message_sent) * 1000)
        gateway_latency = round(self._fabric.gateways[None].heartbeat_latency * 1000)
        await self._fabric.http_api.edit_message(
            channel_id=message_obj["channel_id"],
            message_id=message_obj["id"],
            content=f"Pong! :ping_pong:\nAPI: {api_latency}\nGateway:{gateway_latency}",
        )

    async def run(self) -> None:
        self.sql_pool = await asyncpg.create_pool(**self.config.database.to_dict())
        async with self.sql_pool.acquire() as conn:
            await sql.initalise_schema(self.sql_scripts, conn)  # TODO: separate schemas and folders?
        await super().run()
