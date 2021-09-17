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

__all__: list[str] = []

import typing
from typing import Literal

if typing.TYPE_CHECKING:
    import asyncio
    from collections import abc as collections

    import hikari

    from . import protos

    _OtherValueT = typing.TypeVar("_OtherValueT")
    _DatabaseCollectionT = typing.TypeVar("_DatabaseCollectionT", bound="DatabaseCollection[typing.Any, typing.Any]")

_ValueT_co = typing.TypeVar("_ValueT_co", covariant=True)
_FieldT_co = typing.TypeVar("_FieldT_co", bound=str, contravariant=True)

FilterTypeT = typing.Union[
    Literal["lt"],
    Literal["le"],
    Literal["eq"],
    Literal["ne"],
    Literal["ge"],
    Literal["gt"],
    Literal["contains"],
]
# For a reference on what these all mean see https://docs.python.org/3/library/operator.html


StarredMessageFields = (
    Literal["message_id"]
    | Literal["message_content"]
    | Literal["channel_id"]
    | Literal["author_id"]
    | Literal["author_avatar_hash"]
    | Literal["message_status"]
    | Literal["starboard_message_id"]
)
StarFields = Literal["message_id"] | Literal["starrer_id"]
GuildFields = (
    Literal["id"]
    | Literal["starboard_channel_id"]
    | Literal["log_members"]
    | Literal["member_join_log"]
    | Literal["message_spam_system"]
)
BotUserBanFields = Literal["user_id"] | Literal["reason"] | Literal["expires_at"]
BotGuildBanFields = Literal["guild_id"] | Literal["reason"] | Literal["expires_at"]


class SQLError(Exception):
    __slots__: tuple[str, ...] = ("message",)

    def __init__(self, message: str, /) -> None:
        self.message = message

    def __str__(self) -> str:
        return self.message


# TODO: make abstract
# TODO: Remove this as we shouldn't be expecting sql to raise anything other than field already exists errors
# as validation should catch other stuff
class DataError(SQLError):
    __slots__: tuple[str, ...] = ()


class AlreadyExistsError(SQLError):
    __slots__: tuple[str, ...] = ()


class DatabaseCollection(typing.Protocol[_FieldT_co, _ValueT_co]):
    __slots__: tuple[str, ...] = ()

    async def collect(self) -> collections.Collection[_ValueT_co]:
        raise NotImplementedError

    async def count(self) -> int:
        raise NotImplementedError

    def filter(
        self: _DatabaseCollectionT, filter_type: FilterTypeT, *rules: tuple[_FieldT_co, typing.Any]
    ) -> _DatabaseCollectionT:
        raise NotImplementedError

    def filter_truth(self: _DatabaseCollectionT, *fields: _FieldT_co, truth: bool = True) -> _DatabaseCollectionT:
        raise NotImplementedError

    async def iter(self) -> collections.Iterator[_ValueT_co]:
        raise NotImplementedError

    def limit(self: _DatabaseCollectionT, limit: int, /) -> _DatabaseCollectionT:
        raise NotImplementedError

    # TODO: do we want to finalise here?
    async def map(self, cast: typing.Callable[[_ValueT_co], _OtherValueT], /) -> collections.Iterator[_OtherValueT]:
        raise NotImplementedError

    def order_by(self: _DatabaseCollectionT, field: _FieldT_co, /, ascending: bool = True) -> _DatabaseCollectionT:
        raise NotImplementedError


class DatabaseIterator(DatabaseCollection[_FieldT_co, _ValueT_co], typing.Protocol[_FieldT_co, _ValueT_co]):
    __slots__: tuple[str, ...] = ()

    def __await__(self) -> collections.Generator[typing.Any, None, collections.Iterable[_ValueT_co]]:
        raise NotImplementedError


class FilteredClear(DatabaseCollection[_FieldT_co, _ValueT_co], typing.Protocol[_FieldT_co, _ValueT_co]):
    __slots__: tuple[str, ...] = ()

    def __await__(self) -> collections.Generator[typing.Any, None, int]:
        raise NotImplementedError

    async def execute(self) -> int:
        raise NotImplementedError

    def start(self) -> asyncio.Task[int]:
        raise NotImplementedError


class AdminDatabaseHandler(typing.Protocol):
    __slots__ = ()

    async def add_ban_user(self, user: hikari.SnowflakeishOr[hikari.PartialUser], reason: str, /) -> None:
        raise NotImplementedError

    async def ban_guild(self, user: hikari.SnowflakeishOr[hikari.PartialGuild], reason: str, /) -> None:
        raise NotImplementedError


class ModerationDatabaseHandler(typing.Protocol):
    __slots__ = ()


class StarDatabaseHandler(typing.Protocol):
    __slots__ = ()

    async def add_star(
        self, message: hikari.SnowflakeishOr[hikari.PartialMessage], user: hikari.SnowflakeishOr[hikari.PartialUser], /
    ) -> bool:
        raise NotImplementedError

    def clear_stars(self) -> FilteredClear[StarFields, protos.Star]:
        raise NotImplementedError

    async def get_star(
        self, message_id: hikari.SnowflakeishOr[hikari.Message], user_id: hikari.SnowflakeishOr[hikari.User]
    ) -> typing.Optional[protos.Star]:
        raise NotImplementedError

    def iter_stars(self) -> DatabaseIterator[StarFields, protos.Star]:
        raise NotImplementedError

    async def remove_star(
        self, message: hikari.SnowflakeishOr[hikari.PartialMessage], user: hikari.SnowflakeishOr[hikari.PartialUser], /
    ) -> bool:
        raise NotImplementedError

    async def add_starred_message(
        self,
        *,
        channel_id: hikari.SnowflakeishOr[hikari.PartialChannel],
        author: hikari.SnowflakeishOr[hikari.PartialUser],
        message: hikari.SnowflakeishOr[hikari.Message],
        content: str,
        author_avatar_hash: str | None,
        message_status: int,
        starboard_message_id: hikari.SnowflakeishOr[hikari.PartialMessage],
    ) -> None:
        raise NotImplementedError

    def clear_starred_messages(self) -> FilteredClear[StarredMessageFields, protos.StarredMessage]:
        raise NotImplementedError

    async def get_starred_message(
        self, message_id: hikari.SnowflakeishOr[hikari.Message]
    ) -> protos.StarredMessage | None:
        raise NotImplementedError

    def iter_starred_messages(self) -> DatabaseIterator[StarredMessageFields, protos.StarredMessage]:
        raise NotImplementedError
