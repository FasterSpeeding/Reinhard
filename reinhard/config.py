# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2022, Faster Speeding
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

import dotenv
import hikari

ConfigT = typing.TypeVar("ConfigT", bound="Config")
DefaultT = typing.TypeVar("DefaultT")
ValueT = typing.TypeVar("ValueT")


@typing.overload
def _cast_or_else(
    data: collections.Mapping[str, typing.Any],
    key: str,
    cast: collections.Callable[[typing.Any], ValueT],
) -> ValueT:
    ...


@typing.overload
def _cast_or_else(
    data: collections.Mapping[str, typing.Any],
    key: str,
    cast: collections.Callable[[typing.Any], ValueT],
    default: DefaultT = ...,
) -> ValueT | DefaultT:
    ...


def _cast_or_else(
    data: collections.Mapping[str, typing.Any],
    key: str,
    cast: collections.Callable[[typing.Any], ValueT],
    default: DefaultT = ...,
) -> ValueT | DefaultT:
    try:
        return cast(data[key])
    except KeyError:
        if default is not ...:
            return default

    raise KeyError(f"{key!r} required environment/config key missing")


class Config(abc.ABC):
    __slots__ = ()

    @classmethod
    @abc.abstractmethod
    def from_env(cls: type[ConfigT]) -> ConfigT:
        raise NotImplementedError

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
    def from_env(cls: type[ConfigT]) -> ConfigT:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> DatabaseConfig:
        return cls(
            password=_cast_or_else(mapping, "database_password", str),
            database=_cast_or_else(mapping, "database", str, "postgres"),
            host=_cast_or_else(mapping, "database_host", str, "localhost"),
            port=_cast_or_else(mapping, "database_port", int, 5432),
            user=_cast_or_else(mapping, "database_user", str, "postgres"),
        )


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class PTFConfig(Config):
    auth_service: str
    file_service: str
    message_service: str
    password: str
    username: str

    @classmethod
    def from_env(cls: type[ConfigT]) -> ConfigT:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> PTFConfig:
        return cls(
            auth_service=_cast_or_else(mapping, "auth_service", str),
            file_service=_cast_or_else(mapping, "file_service", str),
            message_service=_cast_or_else(mapping, "message_service", str),
            username=_cast_or_else(mapping, "ptf_username", str),
            password=_cast_or_else(mapping, "ptf_password", str),
        )


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class Tokens(Config):
    bot: str
    google: str | None = None
    spotify_id: str | None = None
    spotify_secret: str | None = None

    @classmethod
    def from_env(cls: type[ConfigT]) -> ConfigT:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> Tokens:
        return cls(
            bot=str(mapping["token"]),
            google=_cast_or_else(mapping, "google", str, None),
            spotify_id=_cast_or_else(mapping, "spotify_id", str, None),
            spotify_secret=_cast_or_else(mapping, "spotify_secret", str, None),
        )


DEFAULT_CACHE: typing.Final[hikari.api.CacheComponents] = (
    hikari.api.CacheComponents.GUILDS
    | hikari.api.CacheComponents.GUILD_CHANNELS
    | hikari.api.CacheComponents.ROLES
    # | hikari.CacheComponents.ME
)

DEFAULT_INTENTS: typing.Final[hikari.Intents] = hikari.Intents.GUILDS | hikari.Intents.ALL_MESSAGES


@typing.overload
def _str_to_bool(value: str, /) -> bool:
    ...


@typing.overload
def _str_to_bool(value: str, /, *, default: ValueT) -> bool | ValueT:
    ...


def _str_to_bool(value: str, /, *, default: ValueT = ...) -> bool | ValueT:
    if value in ("true", "True", "1"):
        return True

    if value in ("false", "False", "0"):
        return False

    if default is not ...:
        return default

    raise ValueError(f"{value!r} is not a valid boolean")


@dataclasses.dataclass(kw_only=True, repr=False, slots=True)
class FullConfig(Config):
    database: DatabaseConfig
    tokens: Tokens
    cache: hikari.api.CacheComponents = DEFAULT_CACHE
    emoji_guild: hikari.Snowflake | None = None
    intents: hikari.Intents = DEFAULT_INTENTS
    log_level: int | str | None = logging.INFO
    mention_prefix: bool = True
    owner_only: bool = False
    prefixes: collections.Set[str] = frozenset()
    ptf: PTFConfig | None = None
    declare_global_commands: typing.Union[bool, hikari.Snowflake] = True

    @classmethod
    def from_env(cls) -> FullConfig:
        dotenv.load_dotenv()

        return cls(
            cache=_cast_or_else(os.environ, "cache", hikari.api.CacheComponents, DEFAULT_CACHE),
            database=DatabaseConfig.from_env(),
            emoji_guild=_cast_or_else(os.environ, "emoji_guild", hikari.Snowflake, None),
            intents=_cast_or_else(os.environ, "intents", hikari.Intents, DEFAULT_INTENTS),
            log_level=_cast_or_else(os.environ, "log_level", lambda v: int(v) if v.isdigit() else v, logging.INFO),
            mention_prefix=_cast_or_else(os.environ, "mention_prefix", _str_to_bool, True),
            owner_only=_cast_or_else(os.environ, "owner_only", _str_to_bool, False),
            prefixes=_cast_or_else(os.environ, "prefixes", lambda v: frozenset(map(str, v)), frozenset[str]()),
            ptf=PTFConfig.from_env() if os.getenv("ptf_username") else None,
            tokens=Tokens.from_env(),
            declare_global_commands=_cast_or_else(
                os.environ,
                "declare_global_commands",
                lambda v: nv if (nv := _str_to_bool(v, default=None)) is not None else hikari.Snowflake(v),
                True,
            ),
        )

    @classmethod
    def from_mapping(cls, mapping: collections.Mapping[str, typing.Any], /) -> FullConfig:
        log_level = mapping.get("log_level", logging.INFO)
        if not isinstance(log_level, (str, int)):
            raise ValueError("Invalid log level found in config")

        elif isinstance(log_level, str):
            log_level = log_level.upper()

        declare_global_commands = mapping.get("declare_global_commands", True)
        if not isinstance(declare_global_commands, bool):
            declare_global_commands = hikari.Snowflake(declare_global_commands)

        return cls(
            cache=_cast_or_else(mapping, "cache", hikari.api.CacheComponents, DEFAULT_CACHE),
            database=DatabaseConfig.from_mapping(mapping["database"]),
            emoji_guild=_cast_or_else(mapping, "emoji_guild", hikari.Snowflake, None),
            intents=_cast_or_else(mapping, "intents", hikari.Intents, DEFAULT_INTENTS),
            log_level=log_level,
            mention_prefix=bool(mapping.get("mention_prefix", True)),
            owner_only=bool(mapping.get("ownerA_only", False)),
            prefixes=frozenset(map(str, mapping["prefixes"])) if "prefixes" in mapping else frozenset(),
            ptf=_cast_or_else(mapping, "ptf", PTFConfig.from_mapping, None),
            tokens=Tokens.from_mapping(mapping["tokens"]),
            declare_global_commands=declare_global_commands,
        )


def get_config_from_file(file: pathlib.Path | None = None) -> FullConfig:
    import yaml

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
