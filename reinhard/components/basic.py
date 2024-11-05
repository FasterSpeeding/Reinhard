# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2024, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__: list[str] = ["load_basic"]

import datetime
import importlib.metadata
import math
import platform
import time
from collections import abc as collections
from typing import Annotated

import alluka
import hikari
import psutil
import tanjun
from hikari import snowflakes
from tanchan import doc_parse
from tanchan.components import buttons

from .. import utility

try:
    import alluka_rust  # type: ignore

    alluka_rust_ver = "v" + importlib.metadata.version("alluka_rust")


except ImportError:
    alluka_rust = None
    alluka_rust_ver = None

try:
    import rukari  # type: ignore

    rukari_ver: str | None = "v" + importlib.metadata.version("rukari")

except ImportError:
    rukari = None
    rukari_ver = None

ALLUKA_VER = "v" + importlib.metadata.version("alluka")
HIKARI_VER = "v" + importlib.metadata.version("hikari")


@tanjun.as_message_command("about")
@doc_parse.as_slash_command()
async def about(
    ctx: tanjun.abc.Context,
    process: Annotated[psutil.Process, tanjun.cached_inject(psutil.Process)],
    bot: alluka.Injected[hikari.ShardAware | None],
) -> None:
    """Get basic information about the current bot instance."""
    start_date = datetime.datetime.fromtimestamp(process.create_time())
    uptime = datetime.datetime.now() - start_date
    memory_usage: float = process.memory_full_info().uss / 1024**2
    memory_percent: float = process.memory_percent()

    if (cpu_count := psutil.cpu_count()) is not None:
        cpu_usage: float = process.cpu_percent() / cpu_count

    else:
        cpu_usage = -1.0 

    if ctx.shards:
        shard_id = snowflakes.calculate_shard_id(ctx.shards.shard_count, ctx.guild_id) if ctx.guild_id else 0
        name = f"Reinhard: Shard {shard_id} of {ctx.shards.shard_count}"

    else:
        name = "Reinhard: REST Server"

    if alluka_rust and isinstance(
        ctx.injection_client, alluka_rust.Client  # pyright: ignore [reportUnknownMemberType]
    ):
        alluka_ver = f"Rust ({alluka_rust_ver})"

    else:
        alluka_ver = f"Pure-Python ({ALLUKA_VER})"

    if bot and rukari and isinstance(bot, rukari.Bot):  # pyright: ignore [reportUnknownMemberType]
        hikari_ver = f"Rukari ({rukari_ver})"

    else:
        hikari_ver = f"Pure-Python ({HIKARI_VER})"

    description = (
        "An experimental pythonic Hikari bot.\n "
        "The source can be found on [Github](https://github.com/FasterSpeeding/Reinhard)."
    )
    embed = (
        hikari.Embed(description=description, colour=utility.embed_colour())
        .set_author(name=name, url=hikari.__url__)
        .add_field(name="Uptime", value=str(uptime), inline=True)
        .add_field(
            name="Process", value=f"{memory_usage:.2f} MB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU", inline=True
        )
        .add_field(name="Hikari impl", value=hikari_ver, inline=True)
        .add_field(name="Alluka impl", value=alluka_ver, inline=True)
        .set_footer(
            icon="http://i.imgur.com/5BFecvA.png", text=f"Made with Hikari (python {platform.python_version()})"
        )
    )

    await ctx.respond(embed=embed, component=buttons.delete_row(ctx))


@tanjun.as_message_command("ping")
@doc_parse.as_slash_command()
async def ping(ctx: tanjun.abc.Context, /) -> None:
    """Get the bot's current delay."""
    start_time = time.perf_counter()
    await ctx.rest.fetch_my_user()
    time_taken = (time.perf_counter() - start_time) * 1_000
    heartbeat_latency = ctx.shards.heartbeat_latency * 1_000 if ctx.shards else float("NAN")
    await ctx.respond(
        f"PONG\n- REST: {time_taken:.0f}ms\n- Gateway: {heartbeat_latency:.0f}ms", component=buttons.delete_row(ctx)
    )


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


def cache_check(ctx: tanjun.abc.Context) -> bool:
    if ctx.cache:
        return True

    raise tanjun.CommandError("Client is cache-less", component=buttons.delete_row(ctx))


@tanjun.with_check(cache_check, follow_wrapped=True)
@tanjun.as_message_command("cache")
@doc_parse.as_slash_command()
async def cache(
    ctx: tanjun.abc.Context,
    cache: alluka.Injected[hikari.api.Cache],
    me: Annotated[hikari.OwnUser, tanjun.inject_lc(hikari.OwnUser)],
    process: Annotated[psutil.Process, tanjun.cached_inject(psutil.Process)],
) -> None:
    """Get general information about this bot's cache."""
    start_date = datetime.datetime.fromtimestamp(process.create_time())
    uptime = datetime.datetime.now() - start_date
    memory_usage: float = process.memory_full_info().uss / 1024**2
    memory_percent: float = process.memory_percent()

    if (cpu_count := psutil.cpu_count()) is not None:
        cpu_usage: float = process.cpu_percent() / cpu_count

    else:
        cpu_usage = -1.0

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
        line + " " * (largest_line + 2 - len(line)) + f"{time_taken:0{left_pad}.4f} ms"
        for line, time_taken in cache_stats_lines
    )

    embed = (
        hikari.Embed(description="An experimental pythonic Hikari bot.", color=0x55CDFC)
        .set_author(name="Hikari: testing client", icon=me.avatar_url or me.default_avatar_url, url=hikari.__url__)
        .add_field(name="Uptime", value=str(uptime), inline=True)
        .add_field(
            name="Process", value=f"{memory_usage:.2f} MB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU", inline=True
        )
        .add_field(name="Standard cache stats", value=f"```{cache_stats}```")
        .set_footer(
            icon="http://i.imgur.com/5BFecvA.png",
            text=f"Made with Hikari {HIKARI_VER} (python {platform.python_version()})",
        )
    )

    await ctx.respond(content=f"{storage_time_taken * 1_000:.4g} ms", embed=embed, component=buttons.delete_row(ctx))


@tanjun.as_message_command("invite")
@doc_parse.as_slash_command()
async def invite(ctx: tanjun.abc.Context, me: Annotated[hikari.OwnUser, tanjun.inject_lc(hikari.OwnUser)]) -> None:
    """Invite the bot to your server(s)."""
    await ctx.respond(
        f"https://discord.com/oauth2/authorize?client_id={me.id}&scope=bot%20applications.commands&permissions=8",
        component=buttons.delete_row(ctx),
    )


load_basic = tanjun.Component(name="basic", strict=True).load_from_scope().make_loader()
