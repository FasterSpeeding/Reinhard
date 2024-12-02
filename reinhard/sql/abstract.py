# BSD 3-Clause License
#
# Copyright (c) 2020-2025, Faster Speeding
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
    from typing import Self

    import hikari

    from . import protos

    _OtherValueT = typing.TypeVar("_OtherValueT")

_ValueT_co = typing.TypeVar("_ValueT_co", covariant=True)
_FieldT_contra = typing.TypeVar("_FieldT_contra", bound=str, contravariant=True)

FilterTypeT = Literal["lt", "le", "eq", "ne", "ge", "gt", "contains"]

# For a reference on what these all mean see https://docs.python.org/3/library/operator.html


StarredMessageFields = Literal[
    "message_id",
    "message_content",
    "channel_id",
    "author_id",
    "author_avatar_hash",
    "message_status",
    "starboard_message_id",
]
StarFields = Literal["message_id", "starrer_id"]
GuildFields = Literal["id", "starboard_channel_id", "log_members", "member_join_log", "message_spam_system"]
BotUserBanFields = Literal["user_id", "reason", "expires_at"]
BotGuildBanFields = Literal["guild_id", "reason", "expires_at"]


class SQLError(Exception):
    def __init__(self, message: str, /) -> None:
        self.message = message

    def __str__(self) -> str:
        return self.message


# TODO: make abstract
# TODO: Remove this as we shouldn't be expecting sql to raise anything other than field already exists errors
# as validation should catch other stuff
class DataError(SQLError): ...


class AlreadyExistsError(SQLError): ...


class DatabaseCollection(typing.Protocol[_FieldT_contra, _ValueT_co]):
    __slots__ = ()

    async def collect(self) -> collections.Collection[_ValueT_co]:
        raise NotImplementedError

    async def count(self) -> int:
        raise NotImplementedError

    def filter(self, filter_type: FilterTypeT, *rules: tuple[_FieldT_contra, typing.Any]) -> Self:
        raise NotImplementedError

    def filter_truth(self, *fields: _FieldT_contra, truth: bool = True) -> Self:
        raise NotImplementedError

    async def iter(self) -> collections.Iterator[_ValueT_co]:
        raise NotImplementedError

    def limit(self, limit: int, /) -> Self:
        raise NotImplementedError

    # TODO: do we want to finalise here?
    async def map(
        self, cast: collections.Callable[[_ValueT_co], _OtherValueT], /
    ) -> collections.Iterator[_OtherValueT]:
        raise NotImplementedError

    def order_by(self, field: _FieldT_contra, /, *, ascending: bool = True) -> Self:
        raise NotImplementedError


class DatabaseIterator(DatabaseCollection[_FieldT_contra, _ValueT_co], typing.Protocol[_FieldT_contra, _ValueT_co]):
    __slots__ = ()

    def __await__(self) -> collections.Generator[typing.Any, None, collections.Iterable[_ValueT_co]]:
        raise NotImplementedError


class FilteredClear(DatabaseCollection[_FieldT_contra, _ValueT_co], typing.Protocol[_FieldT_contra, _ValueT_co]):
    __slots__ = ()

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
    ) -> protos.Star | None:
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
