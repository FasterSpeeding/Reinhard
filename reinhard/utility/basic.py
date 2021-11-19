# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
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

__all__: list[str] = [
    "basic_name_grid",
    "DELETE_CUSTOM_ID",
    "delete_button_callback",
    "delete_row",
    "delete_row_multiple_authors",
    "prettify_date",
    "prettify_index",
    "raise_error",
]

import enum
import typing

import hikari
from tanjun import errors

if typing.TYPE_CHECKING:
    import datetime

    import yuyo
    from tanjun import abc as tanjun_abc


def prettify_date(date: datetime.datetime) -> str:
    return date.strftime("%a %d %b %Y %H:%M:%S %Z")


def prettify_index(index: int, max_digit_count: int) -> str:
    remainder = index % 10
    name = str(index).zfill(max_digit_count)
    if remainder == 1 and index % 100 != 11:
        return f"{name}st"
    if remainder == 2 and index % 100 != 12:
        return f"{name}nd"
    if remainder == 3 and index % 100 != 13:
        return f"{name}rd"

    return f"{name}th"


class _ErrorRaiserT(typing.Protocol):
    def __call__(self, arg: typing.Any = None, /) -> typing.NoReturn:
        raise NotImplementedError


def raise_error(
    message: str | None, /, error_type: type[BaseException] = errors.CommandError
) -> _ErrorRaiserT:  # TODO: better typing for the callable return
    def raise_command_error_(_: typing.Any = None) -> typing.NoReturn:
        if message:
            raise error_type(message) from None

        raise error_type from None

    return raise_command_error_


def basic_name_grid(flags: enum.IntFlag) -> str:  # TODO: actually deal with max len lol
    names = [name for name, flag in type(flags).__members__.items() if flag != 0 and (flag & flags) == flag]
    names.sort()
    if not names:
        return ""

    name_grid: list[str] = []
    line = ""
    for name in names:
        if line:
            name_grid.append(f"`{line}`, `{name}`,")
            line = ""
        else:
            line = name

    if line:
        name_grid.append(f"`{line}`")

    name_grid[-1] = name_grid[-1].strip(",")
    return "\n".join(name_grid)


async def delete_button_callback(ctx: yuyo.ComponentContext) -> None:
    author_ids = set(map(hikari.Snowflake, ctx.interaction.custom_id.removeprefix(DELETE_CUSTOM_ID).split(",")))
    if (
        ctx.interaction.user.id in author_ids
        or ctx.interaction.member
        and author_ids.intersection(ctx.interaction.member.role_ids)
    ):
        await ctx.defer(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        await ctx.delete_initial_response()

    else:
        await ctx.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE, "You do not own this message", flags=hikari.MessageFlag.EPHEMERAL
        )


DELETE_CUSTOM_ID = "AUTHOR_DELETE_BUTTON:"


def delete_row(ctx: tanjun_abc.Context) -> hikari.impl.ActionRowBuilder:
    return (
        hikari.impl.ActionRowBuilder()
        .add_button(hikari.ButtonStyle.DANGER, DELETE_CUSTOM_ID + str(ctx.author.id))
        .set_emoji("\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}")
        .add_to_container()
    )


def delete_row_multiple_authors(*authors: hikari.Snowflakeish) -> hikari.impl.ActionRowBuilder:
    author_ids = ",".join(map(str, authors))
    return (
        hikari.impl.ActionRowBuilder()
        .add_button(hikari.ButtonStyle.DANGER, DELETE_CUSTOM_ID + author_ids)
        .set_emoji("\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}")
        .add_to_container()
    )
