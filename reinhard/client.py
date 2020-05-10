from __future__ import annotations

import asyncio
import copy
import datetime
import platform
import time
import typing

import asyncpg
import psutil
from hikari import embeds
from hikari import __url__ as hikari_url
from hikari import __version__ as hikari_version

from reinhard import sql
from reinhard.util import command_client
from reinhard.util import command_hooks
from reinhard.util import constants
from reinhard.util import paginators

if typing.TYPE_CHECKING:
    from hikari import users as _users
    from hikari.clients import components as _components


class CommandClient(command_client.ReinhardCommandClient):
    current_user: typing.Optional[_users.MyUser]
    help_embeds: typing.Mapping[str, embeds.Embed]
    paginator_pool: paginators.PaginatorPool
    process: psutil.Process
    sql_pool: typing.Optional[asyncpg.pool.Pool]
    sql_scripts: sql.CachedScripts

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
        self.current_user = None
        self.help_embeds = {}
        self.paginator_pool = paginators.PaginatorPool(self.components)
        self.process = psutil.Process()
        self.sql_pool = None
        self.sql_scripts = sql.CachedScripts(pattern=r"[.*schema.sql]|[*prefix.sql]")

    async def load(self) -> None:
        await super().load()
        self.sql_pool = await asyncpg.create_pool(
            password=self.components.config.database.password,
            host=self.components.config.database.host,
            user=self.components.config.database.user,
            database=self.components.config.database.database,
            port=self.components.config.database.port,
        )
        self.current_user = await self.components.rest.fetch_me()
        async with self.sql_pool.acquire() as conn:
            await sql.initialise_schema(self.sql_scripts, conn)

    async def unload(self) -> None:
        await super().unload()
        await self.sql_pool.close()

    @command_client.command
    async def about(self, ctx: command_client.Context) -> None:
        """Get general information about this bot."""
        start_date = datetime.datetime.fromtimestamp(self.process.create_time())
        uptime = datetime.datetime.now() - start_date
        memory_usage = self.process.memory_full_info().uss / 1024 ** 2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()
        memory_percent = self.process.memory_percent()
        await ctx.message.reply(
            embed=embeds.Embed(description="An experimental pythonic Hikari bot.", color=constants.EMBED_COLOUR)
            .set_author(
                name=f"Reinhard: Shard {ctx.shard_id} of {ctx.shard.shard_count}",
                icon=self.current_user.avatar_url,
                url=hikari_url,
            )
            .add_field(name="Uptime", value=str(uptime), inline=True)
            .add_field(
                name="Process",
                value=f"{memory_usage:.2f} MiB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU",
                inline=True,
            )
            .set_footer(
                icon="http://i.imgur.com/5BFecvA.png",
                text=f"Made with Hikari v{hikari_version} (python {platform.python_version()})",
            )
        )

    async def get_guild_prefix(self, guild_id: int) -> typing.Optional[str]:
        async with self.sql_pool.acquire() as conn:
            if data := await conn.fetchrow(self.sql_scripts.find_guild_prefix, guild_id):
                return data["prefix"]

    def _form_command_name(self, command: command_client.AbstractCommand) -> str:
        arguments = []
        for parameter in command.parser.signature.parameters.values():
            annotation = ""
            if parameter.annotation is not parameter.empty:
                if args := typing.get_args(parameter.annotation):
                    annotation = " | ".join(getattr(arg, "__name__", str(arg)) for arg in args if arg is not type(None))
                else:
                    annotation = getattr(parameter.annotation, "__name__", str(parameter.annotation))

            name = parameter.name.replace("_", "-")
            if parameter.name == command.parser.is_greedy:
                name = f"{name}..."
            elif parameter.default is not parameter.empty:
                name = f"--{name}"
            arguments.append(f"{name} : {annotation}" if annotation else name)
        arguments = f"<{', '.join(arguments)}>" if arguments else ""
        names = f"({' | '.join(command.triggers)})" if len(command.triggers) > 1 else command.triggers[0]
        return f"{self.components.config.prefixes[0]}{names} {arguments}"

    def generate_help_embed(self) -> typing.Iterator[typing.Tuple[str, embeds.Embed]]:
        for cluster in (self, *self._clusters.values()):
            embed = embeds.Embed(
                title=cluster.__class__.__name__,
                color=constants.EMBED_COLOUR,
                description="Argument key: <required, multi-word..., --optional>",
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

    @command_client.command(greedy="command")
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
                        color=constants.EMBED_COLOUR,
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
