from __future__ import annotations

__all__: list[str] = ["basic_component"]

import collections.abc as collections
import datetime
import itertools
import math
import platform
import time

import hikari
import psutil  # type: ignore[import]
import tanjun
import yuyo
from hikari import snowflakes

from ..util import constants
from ..util import help as help_util
from ..util import rest_manager


def gen_help_embeds(
    ctx: tanjun.abc.Context = tanjun.injected(type=tanjun.abc.Context),
    client: tanjun.abc.Client = tanjun.injected(type=tanjun.abc.Client),
) -> dict[str, list[hikari.Embed]]:
    prefix = next(iter(client.prefixes)) if client and client.prefixes else ""

    help_embeds: dict[str, list[hikari.Embed]] = {}
    for component in ctx.client.components:
        if value := help_util.generate_help_embeds(component, prefix=prefix):
            help_embeds[value[0].lower()] = [v for v in value[1]]

    return help_embeds


basic_component = tanjun.Component(strict=True)
help_util.with_docs(basic_component, "Basic commands", "Commands provided to give information about this bot.")


@basic_component.with_slash_command
@tanjun.as_slash_command("about", "Get basic information about the current bot instance.")
async def about_command(
    ctx: tanjun.abc.Context,
    process: psutil.Process = tanjun.injected(callback=tanjun.cache_callback(psutil.Process)),
) -> None:
    """Get basic information about the current bot instance."""
    start_date = datetime.datetime.fromtimestamp(process.create_time())
    uptime = datetime.datetime.now() - start_date
    memory_usage: float = process.memory_full_info().uss / 1024 ** 2
    cpu_usage: float = process.cpu_percent() / psutil.cpu_count()
    memory_percent: float = process.memory_percent()

    if ctx.shards:
        shard_id = snowflakes.calculate_shard_id(ctx.shards.shard_count, ctx.guild_id) if ctx.guild_id else 0
        name = f"Reinhard: Shard {shard_id} of {ctx.shards.shard_count}"

    else:
        name = "Reinhard: REST Server"

    description = (
        "An experimental pythonic Hikari bot.\n "
        "The source can be found on [Github](https://github.com/FasterSpeeding/Reinhard)."
    )
    embed = (
        hikari.Embed(description=description, colour=constants.embed_colour())
        .set_author(name=name, url=hikari.__url__)
        .add_field(name="Uptime", value=str(uptime), inline=True)
        .add_field(
            name="Process",
            value=f"{memory_usage:.2f} MB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU",
            inline=True,
        )
        .set_footer(
            icon="http://i.imgur.com/5BFecvA.png",
            text=f"Made with Hikari v{hikari.__version__} (python {platform.python_version()})",
        )
    )

    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
    await error_manager.try_respond(ctx, embed=embed)


@basic_component.with_message_command
@tanjun.as_message_command("help")
async def help_command(ctx: tanjun.abc.Context) -> None:
    await ctx.respond("See the slash command menu")


# @basic_component.with_message_command
# @tanjun.with_greedy_argument("command_name", default=None)
# @tanjun.with_option("component_name", "--component", default=None)
# @tanjun.with_parser
# # TODO: specify a group or command
# @tanjun.as_message_command("help")
async def old_help_command(
    ctx: tanjun.abc.Context,
    command_name: str | None,
    component_name: str | None,
    component_client: yuyo.ComponentClient = tanjun.injected(type=yuyo.ComponentClient),
    help_embeds: dict[str, list[hikari.Embed]] = tanjun.injected(callback=tanjun.cache_callback(gen_help_embeds)),
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
                await ctx.respond(embed=command_embed)
                break

        else:
            await ctx.respond(f"Couldn't find `{command_name}` command.")

        return

    if component_name:
        if component_name.lower() not in help_embeds:
            raise tanjun.CommandError(f"Couldn't find component `{component_name}`")

        embed_generator = ((hikari.UNDEFINED, embed) for embed in help_embeds[component_name.lower()])

    else:
        embed_generator = (
            (hikari.UNDEFINED, embed) for embed in itertools.chain.from_iterable(list(help_embeds.values()))
        )

    paginator = yuyo.ComponentPaginator(embed_generator, authors=(ctx.author,))

    if first_entry := await paginator.get_next_entry():
        content, embed = first_entry
        message = await ctx.respond(content=content, embed=embed, component=paginator, ensure_result=True)
        component_client.add_executor(message, paginator)


@basic_component.with_slash_command
@tanjun.as_slash_command("ping", "Get the bot's current delay.")
async def ping_command(ctx: tanjun.abc.Context, /) -> None:
    """Get the bot's current delay."""
    start_time = time.perf_counter()
    await ctx.rest.fetch_my_user()
    time_taken = (time.perf_counter() - start_time) * 1_000
    heartbeat_latency = ctx.shards.heartbeat_latency * 1_000 if ctx.shards else float("NAN")
    await ctx.respond(f"PONG\n - REST: {time_taken:.0f}ms\n - Gateway: {heartbeat_latency:.0f}ms")


_about_lines: list[tuple[str, collections.Callable[[hikari.api.Cache], int]]] = [
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
]


@basic_component.with_slash_command
@tanjun.as_slash_command("cache", "Get general information about this bot's cache.")
async def cache_command(
    ctx: tanjun.abc.Context,
    process: psutil.Process = tanjun.injected(callback=tanjun.cache_callback(psutil.Process)),
    cache: hikari.api.Cache = tanjun.injected(type=hikari.api.Cache),
) -> None:
    """Get general information about this bot."""
    start_date = datetime.datetime.fromtimestamp(process.create_time())
    uptime = datetime.datetime.now() - start_date
    memory_usage: float = process.memory_full_info().uss / 1024 ** 2
    cpu_usage: float = process.cpu_percent() / psutil.cpu_count()
    memory_percent: float = process.memory_percent()

    cache_stats_lines: list[tuple[str, float]] = []

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
        hikari.Embed(description="An experimental pythonic Hikari bot.", color=0x55CDFC)
        .set_author(name="Hikari: testing client", icon=avatar, url=hikari.__url__)
        .add_field(name="Uptime", value=str(uptime), inline=True)
        .add_field(
            name="Process",
            value=f"{memory_usage:.2f} MiB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU",
            inline=True,
        )
        .add_field(name="Standard cache stats", value=f"```{cache_stats}```")
        .set_footer(
            icon="http://i.imgur.com/5BFecvA.png",
            text=f"Made with Hikari v{hikari.__version__} (python {platform.python_version()})",
        )
    )

    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
    await error_manager.try_respond(ctx, content=f"{storage_time_taken * 1_000:.4g} ms", embed=embed)


@cache_command.with_check
def _cache_command_check(ctx: tanjun.abc.Context) -> bool:
    if ctx.cache:
        return True

    raise tanjun.CommandError("Client is cache-less")


@tanjun.as_loader
def load_component(cli: tanjun.abc.Client, /) -> None:
    cli.add_component(basic_component.copy())
