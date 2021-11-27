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
    "chunk",
    "DELETE_CUSTOM_ID",
    "delete_button_callback",
    "delete_row",
    "delete_row_multiple_authors",
    "embed_iterator",
    "prettify_date",
    "prettify_index",
    "raise_error",
]

import enum
import typing

import hikari
from tanjun import errors

from . import constants

if typing.TYPE_CHECKING:
    import datetime
    from collections import abc as collections

    import yuyo
    from tanjun import abc as tanjun_abc

    _ValueT = typing.TypeVar("_ValueT")


def embed_iterator(
    descriptions: collections.Iterator[_ValueT],
    description_cast: collections.Callable[[_ValueT], str] = lambda v: str(v),
    /,
    *,
    title: typing.Any = None,
    url: typing.Optional[str] = None,
    color: typing.Optional[hikari.Colorish] = None,
    timestamp: typing.Optional[datetime.datetime] = None,
    cast_embed: typing.Optional[collections.Callable[[hikari.Embed], hikari.Embed]] = None,
) -> collections.Iterator[typing.Tuple[hikari.UndefinedType, hikari.Embed]]:
    iterator = (
        (
            hikari.UNDEFINED,
            hikari.Embed(
                description=description_cast(description) if description_cast else description,
                color=constants.embed_colour() if color is None else color,
                title=title,
                url=url,
                timestamp=timestamp,
            ).set_footer(text=f"Page {index + 1}"),
        )
        for index, description in enumerate(descriptions)
    )
    return map(lambda v: (hikari.UNDEFINED, cast_embed(v[1])), iterator) if cast_embed else iterator


def chunk(iterator: collections.Iterator[_ValueT], max: int) -> collections.Iterator[list[_ValueT]]:
    chunk: list[_ValueT] = []
    for entry in iterator:
        chunk.append(entry)
        if len(chunk) == max:
            yield chunk
            chunk = []

    if chunk:
        yield chunk


def prettify_date(date: datetime.datetime) -> str:
    return date.strftime("%a %d %b %Y %H:%M:%S %Z")


def prettify_index(index: int, max_digit_count: int) -> str:
    name = str(index).zfill(max_digit_count)
    match index % 10:
        case 1 if index % 100 == 11:
            return f"{name}st"
        case 2 if index % 100 == 12:
            return f"{name}nd"
        case 3 if index % 100 == 13:
            return f"{name}rd"
        case _:
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
        .set_emoji(constants.DELETE_EMOJI)
        .add_to_container()
    )


def delete_row_multiple_authors(*authors: hikari.Snowflakeish) -> hikari.impl.ActionRowBuilder:
    return (
        hikari.impl.ActionRowBuilder()
        .add_button(hikari.ButtonStyle.DANGER, DELETE_CUSTOM_ID + ",".join(map(str, authors)))
        .set_emoji(constants.DELETE_EMOJI)
        .add_to_container()
    )
