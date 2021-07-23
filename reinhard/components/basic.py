from __future__ import annotations

__all__: typing.Sequence[str] = ["basic_component"]

import datetime
import itertools
import math
import platform
import time
import typing

import psutil  # type: ignore[import]
from hikari import __url__ as hikari_url
from hikari import __version__ as hikari_version
from hikari import embeds as embeds_
from hikari import errors as hikari_errors
from hikari import traits as hikari_traits
from hikari import undefined
from hikari.api import cache as cache_api
from tanjun import checks
from tanjun import clients
from tanjun import commands
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import injector
from tanjun import parsing
from tanjun import traits as tanjun_traits
from yuyo import backoff
from yuyo import paginaton

from ..util import constants
from ..util import help as help_util
from ..util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import messages


def gen_help_embeds(
    ctx: tanjun_traits.MessageContext = injector.injected(type=tanjun_traits.MessageContext),
    client: tanjun_traits.Client = injector.injected(type=tanjun_traits.Client),
) -> typing.Dict[str, typing.List[embeds_.Embed]]:
    prefix = next(iter(client.prefixes)) if client and client.prefixes else ""

    help_embeds: typing.Dict[str, typing.List[embeds_.Embed]] = {}
    for component in ctx.client.components:
        if value := help_util.generate_help_embeds(component, prefix=prefix):
            help_embeds[value[0].lower()] = [v for v in value[1]]

    return help_embeds


basic_component = components.Component()
help_util.with_docs(basic_component, "Basic commands", "Commands provided to give information about this bot.")


@basic_component.with_message_command
@commands.as_message_command("about")
async def about_command(
    ctx: tanjun_traits.MessageContext,
    process: psutil.Process = injector.injected(callback=injector.cache_callback(psutil.Process)),
) -> None:
    """Get basic information about the current bot instance."""
    start_date = datetime.datetime.fromtimestamp(process.create_time())
    uptime = datetime.datetime.now() - start_date
    memory_usage = process.memory_full_info().uss / 1024 ** 2
    cpu_usage = process.cpu_percent() / psutil.cpu_count()
    memory_percent = process.memory_percent()

    name = f"Reinhard: Shard {ctx.shard.id} of {ctx.shards.shard_count}" if ctx.shard and ctx.shards else "Reinhard"
    description = (
        "An experimental pythonic Hikari bot.\n "
        "The source can be found on [Github](https://github.com/FasterSpeeding/Reinhard)."
    )
    embed = (
        embeds_.Embed(description=description, colour=constants.embed_colour())
        .set_author(name=name, url=hikari_url)
        .add_field(name="Uptime", value=str(uptime), inline=True)
        .add_field(
            name="Process",
            value=f"{memory_usage:.2f} MB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU",
            inline=True,
        )
        .set_footer(
            icon="http://i.imgur.com/5BFecvA.png",
            text=f"Made with Hikari v{hikari_version} (python {platform.python_version()})",
        )
    )

    error_manager = rest_manager.HikariErrorManager(
        break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
    )
    await error_manager.try_respond(ctx, embed=embed)


@basic_component.with_message_command
@parsing.with_greedy_argument("command_name", default=None)
@parsing.with_option("component_name", "--component", default=None)
@parsing.with_parser
# TODO: specify a group or command
@commands.as_message_command("help")
async def help_command(
    ctx: tanjun_traits.MessageContext,
    command_name: typing.Optional[str],
    component_name: typing.Optional[str],
    paginator_pool: paginaton.PaginatorPool = injector.injected(type=paginaton.PaginatorPool),
    help_embeds: typing.Dict[str, typing.List[embeds_.Embed]] = injector.injected(
        callback=injector.cache_callback(gen_help_embeds)
    ),
    rest_service: hikari_traits.RESTAware = injector.injected(type=hikari_traits.RESTAware),
) -> None:
    """Get information about the commands in this bot.

    Arguments
        * command name: Optional greedy argument of a name to get a command's documentation by.

    Options
        * component name (--component): Name of a component to get the documentation for.
    """
    if command_name is not None:
        for own_prefix in ctx.client.prefixes:
            if command_name.startswith(own_prefix):
                command_name = command_name[len(own_prefix) :]
                break

        prefix = next(iter(ctx.client.prefixes)) if ctx.client.prefixes else ""
        for _, command in ctx.client.check_message_name(command_name):
            if command_embed := help_util.generate_command_embed(command, prefix=prefix):
                await ctx.message.respond(embed=command_embed)
                break

        else:
            await ctx.message.respond(f"Couldn't find `{command_name}` command.")

        return

    if component_name:
        if component_name.lower() not in help_embeds:
            raise tanjun_errors.CommandError(f"Couldn't find component `{component_name}`")

        embed_generator = ((undefined.UNDEFINED, embed) for embed in help_embeds[component_name.lower()])

    else:
        embed_generator = (
            (undefined.UNDEFINED, embed) for embed in itertools.chain.from_iterable(list(help_embeds.values()))
        )

    paginator = paginaton.Paginator(rest_service, ctx.channel_id, embed_generator, authors=(ctx.author,))
    message = await paginator.open()
    paginator_pool.add_paginator(message, paginator)


@basic_component.with_message_command
@commands.as_message_command("ping")
async def ping_command(ctx: tanjun_traits.MessageContext, /) -> None:
    """Get the bot's current delay."""
    retry = backoff.Backoff(max_retries=5)
    error_manager = rest_manager.HikariErrorManager(
        retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
    )
    message: typing.Optional[messages.Message] = None
    start_time = 0.0
    async for _ in retry:
        with error_manager:
            start_time = time.perf_counter()
            message = await ctx.message.respond(content="Nyaa master!!!")
            break

    # Assume we can't access the channel anymore if this is still None.
    if message is None:
        return

    time_taken = (time.perf_counter() - start_time) * 1_000
    heartbeat_latency = ctx.shard.heartbeat_latency * 1_000 if ctx.shard else float("NAN")
    retry.reset()
    error_manager.clear_rules(break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError))
    async for _ in retry:
        with error_manager:
            await message.edit(f"PONG\n - REST: {time_taken:.0f}ms\n - Gateway: {heartbeat_latency:.0f}ms")
            break


_about_lines: typing.Sequence[typing.Tuple[str, typing.Callable[[cache_api.Cache], int]]] = (
    ("Guild channels: {0}", lambda c: len(c.get_guild_channels_view())),
    ("Emojis: {0}", lambda c: len(c.get_emojis_view())),
    ("Available Guilds: {0}", lambda c: len(c.get_available_guilds_view())),
    ("Unavailable Guilds: {0}", lambda c: len(c.get_unavailable_guilds_view())),
    ("Invites: {0}", lambda c: len(c.get_invites_view())),
    ("Members: {0}", lambda c: sum(len(record) for record in c.get_members_view().values())),
    ("Messages: {0}", lambda c: len(c.get_messages_view())),
    ("Presences: {0}", lambda c: sum(len(record) for record in c.get_presences_view().values())),
    ("Roles: {0}", lambda c: len(c.get_roles_view())),
    ("Users: {0}", lambda c: len(c.get_users_view())),
    ("Voice states: {0}", lambda c: sum(len(record) for record in c.get_voice_states_view().values())),
)


@basic_component.with_message_command
@checks.with_check(lambda ctx: bool(ctx.cache))
@commands.as_message_command("cache")
async def cache_command(
    ctx: tanjun_traits.MessageContext,
    process: psutil.Process = injector.injected(callback=injector.cache_callback(psutil.Process)),
    cache: cache_api.Cache = injector.injected(type=cache_api.Cache),
) -> None:
    """Get general information about this bot."""
    start_date = datetime.datetime.fromtimestamp(process.create_time())
    uptime = datetime.datetime.now() - start_date
    memory_usage = process.memory_full_info().uss / 1024 ** 2
    cpu_usage = process.cpu_percent() / psutil.cpu_count()
    memory_percent = process.memory_percent()

    cache_stats_lines = []

    storage_start_time = time.perf_counter()
    for line_template, callback in _about_lines:
        line_start_time = time.perf_counter()
        line = line_template.format(callback(cache))
        cache_stats_lines.append((line, (time.perf_counter() - line_start_time) * 1_000))

    storage_time_taken = time.perf_counter() - storage_start_time
    # This also accounts for the decimal place and 4 decimal places
    left_pad = math.floor(math.log(max(num for _, num in cache_stats_lines), 10)) + 6
    largest_line = max(len(line) for line, _ in cache_stats_lines)
    cache_stats = "\n".join(
        line + " " * (largest_line + 2 - len(line)) + "{0:0{left_pad}.4f} ms".format(time_taken, left_pad=left_pad)
        for line, time_taken in cache_stats_lines
    )

    # TODO: try cache first + backoff
    avatar = (await ctx.rest.fetch_my_user()).avatar_url
    embed = (
        embeds_.Embed(description="An experimental pythonic Hikari bot.", color=0x55CDFC)
        .set_author(name="Hikari: testing client", icon=avatar, url=hikari_url)
        .add_field(name="Uptime", value=str(uptime), inline=True)
        .add_field(
            name="Process",
            value=f"{memory_usage:.2f} MiB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU",
            inline=True,
        )
        .add_field(name="Standard cache stats", value=f"```{cache_stats}```")
        .set_footer(
            icon="http://i.imgur.com/5BFecvA.png",
            text=f"Made with Hikari v{hikari_version} (python {platform.python_version()})",
        )
    )

    error_manager = rest_manager.HikariErrorManager(
        break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
    )
    await error_manager.try_respond(ctx, content=f"{storage_time_taken * 1_000:.4g} ms", embed=embed)


@clients.as_loader
def load_component(cli: tanjun_traits.Client, /) -> None:
    cli.add_component(basic_component.copy())
