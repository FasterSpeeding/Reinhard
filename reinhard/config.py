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

__all__: list[str] = ["DatabaseConfig", "Tokens", "FullConfig"]

import abc
import collections.abc as collections
import dataclasses
import logging
import os
import pathlib
import typing

import hikari
import yaml

ConfigT = typing.TypeVar("ConfigT", bound="Config")
DefaultT = typing.TypeVar("DefaultT")
ValueT = typing.TypeVar("ValueT")


def _cast_or_default(
    data: collections.Mapping[typing.Any, typing.Any],
    key: str,
    cast: collections.Callable[[typing.Any], ValueT],
    default: DefaultT,
) -> ValueT | DefaultT:
    return cast(data[key]) if key in data else default


class Config(abc.ABC):
    __slots__ = ()

    @classmethod
    @abc.abstractmethod
    def from_mapping(cls: type[ConfigT], mapping: collections.Mapping[str, typing.Any], /) -> ConfigT:
        raise NotImplementedError


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class DatabaseConfig(Config):
    password: str
    database: str = "postgres"
    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> DatabaseConfig:
        return cls(
            password=str(mapping["password"]),
            database=_cast_or_default(mapping, "database", str, "postgres"),
            host=_cast_or_default(mapping, "host", str, "localhost"),
            port=_cast_or_default(mapping, "port", int, 5432),
            user=_cast_or_default(mapping, "user", str, "postgres"),
        )


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class PTFConfig(Config):
    auth_service: str
    file_service: str
    message_service: str
    password: str
    username: str

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> PTFConfig:
        return cls(
            auth_service=str(mapping["auth_service"]),
            file_service=str(mapping["file_service"]),
            message_service=str(mapping["message_service"]),
            username=str(mapping["username"]),
            password=str(mapping["password"]),
        )


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class Tokens(Config):
    bot: str
    google: str | None = None
    spotify_id: str | None = None
    spotify_secret: str | None = None

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> Tokens:
        return cls(
            bot=str(mapping["bot"]),
            google=_cast_or_default(mapping, "google", str, None),
            spotify_id=_cast_or_default(mapping, "spotify_id", str, None),
            spotify_secret=_cast_or_default(mapping, "spotify_secret", str, None),
        )


DEFAULT_CACHE: typing.Final[hikari.CacheComponents] = (
    hikari.CacheComponents.GUILDS
    | hikari.CacheComponents.GUILD_CHANNELS
    | hikari.CacheComponents.ROLES
    # | hikari.CacheComponents.ME
)

DEFAULT_INTENTS: typing.Final[hikari.Intents] = hikari.Intents.GUILDS | hikari.Intents.ALL_MESSAGES


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class FullConfig(Config):
    database: DatabaseConfig
    tokens: Tokens
    cache: hikari.CacheComponents = DEFAULT_CACHE
    emoji_guild: hikari.Snowflake | None = None
    intents: hikari.Intents = DEFAULT_INTENTS
    log_level: int | str | dict[str, typing.Any] | None = logging.INFO
    mention_prefix: bool = True
    owner_only: bool = False
    prefixes: collections.Set[str] = frozenset()
    ptf: PTFConfig | None = None
    set_global_commands: typing.Union[bool, hikari.Snowflake] = True

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> FullConfig:
        log_level = mapping.get("log_level", logging.INFO)
        if not isinstance(log_level, (str, int)):
            raise ValueError("Invalid log level found in config")

        elif isinstance(log_level, str):
            log_level = log_level.upper()

        set_global_commands = mapping.get("set_global_commands", True)
        if not isinstance(set_global_commands, bool):
            set_global_commands = hikari.Snowflake(set_global_commands)

        return cls(
            cache=_cast_or_default(mapping, "cache", hikari.CacheComponents, DEFAULT_CACHE),
            database=DatabaseConfig.from_mapping(mapping["database"]),
            emoji_guild=_cast_or_default(mapping, "emoji_guild", hikari.Snowflake, None),
            intents=_cast_or_default(mapping, "intents", hikari.Intents, DEFAULT_INTENTS),
            log_level=log_level,
            mention_prefix=bool(mapping.get("mention_prefix", True)),
            owner_only=bool(mapping.get("owner_only", False)),
            prefixes=frozenset(map(str, mapping["prefixes"])) if "prefixes" in mapping else frozenset(),
            ptf=_cast_or_default(mapping, "ptf", PTFConfig.from_mapping, None),
            tokens=Tokens.from_mapping(mapping["tokens"]),
            set_global_commands=set_global_commands,
        )


def get_config_from_file(file: pathlib.Path | None = None) -> FullConfig:
    if file is None:
        file = pathlib.Path("config.json")
        file = pathlib.Path("config.yaml") if not file.exists() else file

        if not file.exists():
            raise RuntimeError("Couldn't find valid yaml or json configuration file")

    data = file.read_text()
    return FullConfig.from_mapping(yaml.safe_load(data))


def load_config() -> FullConfig:
    config_location = os.getenv("REINHARD_CONFIG_FILE")
    config_path = pathlib.Path(config_location) if config_location else None

    if config_path and not config_path.exists():
        raise RuntimeError("Invalid configuration given in environment variables")

    return get_config_from_file(config_path)
