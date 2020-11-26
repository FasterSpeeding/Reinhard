from __future__ import annotations

__all__: typing.Sequence[str] = ["BasicComponent"]

import datetime
import itertools
import platform
import time
import typing

import psutil
from hikari import __url__ as hikari_url
from hikari import __version__ as hikari_version
from hikari import embeds as embeds_
from hikari import errors as hikari_errors
from hikari import undefined
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import parsing
from yuyo import backoff
from yuyo import paginaton

from reinhard.util import constants
from reinhard.util import help as help_util
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import messages
    from hikari import users
    from tanjun import traits as tanjun_traits


__exports__ = ["BasicComponent"]


@help_util.with_component_name("Basic Component")
@help_util.with_component_doc("Commands provided to give information about this bot.")
class BasicComponent(components.Component):
    __slots__: typing.Sequence[str] = ("current_user", "help_embeds", "paginator_pool", "process")

    def __init__(self, *, hooks: typing.Optional[tanjun_traits.Hooks] = None) -> None:
        super().__init__(hooks=hooks)
        self.current_user: typing.Optional[users.OwnUser] = None
        self.help_embeds: typing.Mapping[str, typing.Sequence[embeds_.Embed]] = {}
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None
        self.process = psutil.Process()

    def bind_client(self, client: tanjun_traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest_service, client.dispatch_service)

    async def close(self) -> None:
        if self.paginator_pool is not None:
            await self.paginator_pool.close()

        await super().close()

    async def open(self) -> None:
        if self.client is None or self.paginator_pool is None:
            raise RuntimeError("Cannot open this component without binding a client.")

        await self.paginator_pool.open()
        await super().open()

    @help_util.with_command_doc("Get basic information about the current bot instance.")
    @components.command("about")
    async def about(self, ctx: tanjun_traits.Context) -> None:
        """Get general information about this bot."""
        start_date = datetime.datetime.fromtimestamp(self.process.create_time())
        uptime = datetime.datetime.now() - start_date
        memory_usage = self.process.memory_full_info().uss / 1024 ** 2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()
        memory_percent = self.process.memory_percent()
        avatar = self.current_user.avatar_url or self.current_user.default_avatar_url if self.current_user else None

        embed = (
            embeds_.Embed(description="An experimental pythonic Hikari bot.", color=constants.EMBED_COLOUR)
            .set_author(
                name=f"Reinhard: Shard {ctx.shard.id} of {ctx.client.shard_service.shard_count}",
                icon=avatar,
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

        retry = backoff.Backoff(max_retries=5)
        error_handler = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
        )

        async for _ in retry:
            with error_handler:
                await ctx.message.reply(embed=embed)
                break

    @help_util.with_command_doc("Get information about the commands in this bot.")
    @parsing.option("command_name", "--command", "-c", default=None)
    @parsing.option("component_name", "--component", default=None)
    @components.command("help")  # TODO: specify a group or command
    async def help(
        self, ctx: tanjun_traits.Context, command_name: typing.Optional[str], component_name: typing.Optional[str]
    ) -> None:
        prefix = next(iter(self.client.prefixes)) if self.client and self.client.prefixes else ""

        if not self.help_embeds:
            self.help_embeds = {}
            for component in ctx.client.components:
                if (value := await help_util.generate_help_embeds(component, prefix=prefix)) :
                    self.help_embeds[value[0].lower()] = [v async for v in value[1]]

        if component_name:
            if component_name.lower() not in self.help_embeds:
                raise tanjun_errors.CommandError(f"Couldn't find component `{component_name}`")

            embed_generator = ((undefined.UNDEFINED, embed) for embed in self.help_embeds[component_name.lower()])

        elif command_name is not None:
            for own_prefix in ctx.client.prefixes:
                if command_name.startswith(own_prefix):
                    command_name = command_name[len(own_prefix) :]
                    break

            for command in ctx.client.check_name(command_name):
                command_embeds = help_util.generate_command_embeds(command.command, prefix=prefix)
                embed_generator = ((undefined.UNDEFINED, embed) async for embed in command_embeds)

        else:
            embed_generator = (
                (undefined.UNDEFINED, embed) for embed in itertools.chain.from_iterable(list(self.help_embeds.values()))
            )

        paginator = paginaton.Paginator(
            ctx.client.rest_service, ctx.message.channel_id, embed_generator, authors=(ctx.message.author,)
        )
        message = await paginator.open()
        self.paginator_pool.add_paginator(message, paginator)

    @help_util.with_command_doc("Get the bot's current delay.")
    @components.command("ping")
    async def ping(self, ctx: tanjun_traits.Context) -> None:
        retry = backoff.Backoff(max_retries=5)
        error_handler = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
        )
        message: typing.Optional[messages.Message] = None
        start_time = 0.0
        async for _ in retry:
            with error_handler:
                start_time = time.perf_counter()
                message = await ctx.message.reply(content="Nyaa master!!!")
                break

        # Assume we can't access the channel anymore if this is still None.
        if message is None:
            return

        time_taken = (time.perf_counter() - start_time) * 1_000
        heartbeat_latency = ctx.shard.heartbeat_latency * 1_000
        retry.reset()
        error_handler.clear_rules(break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError))
        async for _ in retry:
            with error_handler:
                await message.edit(f"PONG\n - REST: {time_taken:.0f}ms\n - Gateway: {heartbeat_latency:.0f}ms")
                break
