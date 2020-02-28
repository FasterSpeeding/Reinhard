from __future__ import annotations

import contextlib
import logging
import time
import typing


from hikari.internal_utilities import loggers
from hikari.orm import models
import asyncpg


from reinhard.util import command_client
from reinhard import config
from reinhard import sql

logging.getLogger().setLevel(logging.DEBUG)


class BotClient(command_client.CommandClient):
    def __init__(self, bot_config: config.Config, *, modules: typing.List[str] = None,) -> None:
        super().__init__(
            prefixes=bot_config.prefixes, modules=modules, options=bot_config.options,
        )
        self.config = bot_config
        self.logger = loggers.get_named_logger(self)
        self.sql_pool: typing.Optional[asyncpg.pool.Pool] = None
        self.sql_scripts = sql.CachedScripts(pattern=r"[.*schema.sql]|[*prefix.sql]")

    @command_client.command
    async def about(self, ctx: command_client.Context, _) -> None:
        await ctx.reply(content="TODO: This")

    @command_client.command(level=5)
    async def error(self, ctx: command_client.Context, _) -> None:
        raise Exception("This is an exception, get used to it.")

    async def on_error(self, ctx: command_client.Context, e: BaseException) -> None:
        with contextlib.suppress(command_client.PermissionError):
            await ctx.reply(
                embed=models.embeds.Embed(
                    title=f"An unexpected {type(e).__name__} occurred",
                    color=15746887,
                    description=f"```python\n{str(e)[:1950]}```",
                ),
            )

    @command_client.command(level=5)
    async def echo(self, ctx: command_client.Context, args) -> typing.Optional[str]:
        await ctx.reply(content=" ".join(args))

    @command_client.command(level=5)
    async def eval(self, ctx: command_client.Context, args) -> None:
        " ".join(args).strip("```")

    async def get_guild_prefix(self, guild_id: int) -> typing.Optional[str]:
        async with self.sql_pool.acquire() as conn:
            data = await conn.fetchrow(self.sql_scripts.find_guild_prefix, guild_id)
            return data["prefix"] if data is not None else data

    @command_client.command
    async def ping(self, ctx: command_client.Context, _) -> None:
        message_sent = time.perf_counter()
        message_obj = await ctx.reply(content="Nyaa!")
        api_latency = round((time.perf_counter() - message_sent) * 1000)
        gateway_latency = round(self.heartbeat_latencies[0] * 1000)

        await ctx.fabric.http_adapter.update_message(
            message_obj, content=f"Pong! :ping_pong:\nAPI: {api_latency}\nGateway:{gateway_latency}",
        )

    async def shutdown(self, *args, **kwargs) -> None:
        await super().shutdown(*args, **kwargs)
        await self.sql_pool.close()

    async def start(self, *args, **kwargs) -> None:
        self.sql_pool = await asyncpg.create_pool(**self.config.database.to_dict())
        async with self.sql_pool.acquire() as conn:
            await sql.initialise_schema(self.sql_scripts, conn)

        await super().start(*args, **kwargs)
