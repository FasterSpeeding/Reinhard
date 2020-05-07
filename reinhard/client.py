from __future__ import annotations

import asyncio
import copy
import time
import typing

import asyncpg
from hikari import embeds

from reinhard import sql
from reinhard.util import command_client
from reinhard.util import command_hooks
from reinhard.util import paginators

if typing.TYPE_CHECKING:
    from hikari.clients import components as _components


class CommandClient(command_client.ReinhardCommandClient):
    def __init__(self, components: _components.Components, *, modules: typing.List[str] = None) -> None:
        if modules is None:
            modules = [f"reinhard.modules.{module}" for module in ("stars", "moderation", "sudo")]
        super().__init__(
            components=components,
            hooks=command_client.CommandHooks(
                on_error=command_hooks.error_hook, on_conversion_error=command_hooks.on_conversion_error
            ),
            modules=modules,
        )
        self.sql_pool: typing.Optional[asyncpg.pool.Pool] = None
        self.sql_scripts = sql.CachedScripts(pattern=r"[.*schema.sql]|[*prefix.sql]")
        self.help_embeds = {}
        self.paginator_pool = paginators.PaginatorPool(self.components)

    async def load(self) -> None:
        await super().load()
        self.sql_pool = await asyncpg.create_pool(
            password=self.components.config.database.password,
            host=self.components.config.database.host,
            user=self.components.config.database.user,
            database=self.components.config.database.database,
            port=self.components.config.database.port,
        )
        async with self.sql_pool.acquire() as conn:
            await sql.initialise_schema(self.sql_scripts, conn)

    async def unload(self) -> None:
        await super().unload()
        await self.sql_pool.close()

    @command_client.command
    async def about(self, ctx: command_client.Context) -> None:
        """Get general information about this bot."""
        await ctx.message.reply(content="TODO: This")

    async def get_guild_prefix(self, guild_id: int) -> typing.Optional[str]:
        async with self.sql_pool.acquire() as conn:
            if data := await conn.fetchrow(self.sql_scripts.find_guild_prefix, guild_id):
                return data["prefix"]

    def _form_command_name(self, command: command_client.AbstractCommand) -> str:
        requireds = []
        optionals = []
        for parameter in command.parser.signature.parameters.values():
            if parameter.annotation is parameter.empty:
                argument = parameter.name
            else:
                if args := typing.get_args(parameter.annotation):
                    annotation = " | ".join(getattr(arg, "__name__", str(arg)) for arg in args if arg is not type(None))
                else:
                    annotation = getattr(parameter.annotation, "__name__", str(parameter.annotation))
                argument = f"{parameter.name}: {annotation}"
            if parameter.default is parameter.empty:
                requireds.append(argument)
            else:
                optionals.append(argument)
        if command.parser.greedy:
            if optionals:
                optionals.append(optionals.pop() + "...")
            elif requireds:
                requireds.append(requireds.pop() + "...")
        requireds = f"<{', '.join(requireds)}> " if requireds else ""
        optionals = f"[{', '.join(optionals)}]" if optionals else ""
        names = f"({' | '.join(command.triggers)})" if len(command.triggers) > 1 else command.triggers[0]
        return f"{self.components.config.prefixes[0]}{names} {requireds}{optionals}"

    def generate_help_embed(self) -> typing.Iterator[typing.Tuple[str, embeds.Embed]]:
        for cluster in (self, *self._clusters.values()):
            embed = embeds.Embed(
                title=cluster.__class__.__name__,
                color=0x55CDFC,
                description="Argument key: <required> [optional], with '...'specifying a multi-word argument",
            )
            for command in cluster.commands:
                if len(embed.fields) == 25:
                    yield embed
                    embed = copy.copy(embed)
                    embed.fields = []
                value = (command.docstring or "...").split("\n")[0]
                if len(value) > 70:
                    value = value[:-67] + "..."

                embed.add_field(
                    name=self._form_command_name(command), value=value, inline=False,
                )
            yield cluster.__class__.__name__, embed  # TODO: better name generation

    @command_client.command(greedy=True)
    async def help(
        self, ctx: command_client.Context, command: typing.Optional[str] = None
    ) -> None:  # TODO: do we even support typing.Union?
        """Get information about this bot's loaded commands."""
        if not self.help_embeds:
            self.help_embeds = dict(self.generate_help_embed())
        if command:
            try:
                command = next(self.get_global_command_from_name(command))[0]
            except StopIteration:
                embed = self.help_embeds.get(command)
                if embed:
                    await ctx.message.reply(embed=embed)
                else:
                    await ctx.message.reply(content="No command or command group found with that name.")
            else:
                await ctx.message.reply(
                    embed=embeds.Embed(
                        title=self._form_command_name(command),
                        description=command.docstring[:2000] if command.docstring else "...",
                        color=0x55CDFC,
                    )
                )
        else:
            help_embeds = (("", embed) for embed in self.help_embeds.values())
            first_embed = next(help_embeds)
            message = await ctx.message.reply(embed=first_embed[1])
            await self.paginator_pool.register_message(
                message, first_entry=first_embed, generator=help_embeds, authors=[ctx.message.author.id]
            )

    @command_client.command
    async def ping(self, ctx: command_client.Context, delay: int = 0) -> None:
        """Get statistics about the latency between this bot and Discord's API."""
        await asyncio.sleep(delay)
        message_sent = time.perf_counter()
        message_obj = await ctx.message.reply(content="Nyaa!")
        api_latency = round((time.perf_counter() - message_sent) * 1000)
        gateway_latency = round(ctx.shard.heartbeat_latency * 1000)

        await ctx.components.rest.update_message(
            message=message_obj,
            channel=message_obj.channel_id,
            content=f"Pong! :ping_pong:\nAPI: {api_latency}\nGateway: {gateway_latency}",
        )
