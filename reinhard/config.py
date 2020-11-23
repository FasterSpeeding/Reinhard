from __future__ import annotations

__all__: typing.Sequence[str] = ["DatabaseConfig", "Tokens", "FullConfig"]

import abc
import logging
import pathlib
import typing

import yaml
from hikari import snowflakes

if typing.TYPE_CHECKING:
    from hikari.impl import bot

ConfigT = typing.TypeVar("ConfigT", bound="Config")


class Config(abc.ABC):
    __slots__: typing.Sequence[str] = ()

    @classmethod
    @abc.abstractmethod
    def from_mapping(cls: typing.Type[ConfigT], mapping: typing.Mapping[str, typing.Any], /) -> ConfigT:
        raise NotImplementedError


class DatabaseConfig(Config):
    __slots__: typing.Sequence[str] = ("password", "database", "host", "port", "user")

    def __init__(
        self,
        password: str,
        /,
        *,
        database: str = "postgres",
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
    ) -> None:
        self.password = password
        self.database = database
        self.host = host
        self.port = port
        self.user = user

    @classmethod
    def from_mapping(cls, mapping: typing.Mapping[str, typing.Any], /) -> DatabaseConfig:
        return cls(
            str(mapping["password"]),
            database=str(mapping["database"]) if "database" in mapping else "postgres",
            host=str(mapping["host"]) if "host" in mapping else "localhost",
            port=int(mapping["port"]) if "port" in mapping else 5432,
            user=str(mapping["user"]) if "user" in mapping else "postgres",
        )


class Tokens(Config):
    __slots__: typing.Sequence[str] = (
        "bot",
        "google",
    )

    def __init__(self, bot: str, *, google: typing.Optional[str] = None) -> None:
        self.bot = bot
        self.google = google

    @classmethod
    def from_mapping(cls, mapping: typing.Mapping[str, typing.Any], /) -> Tokens:
        return cls(bot=str(mapping["bot"]), google=str(mapping["google"]) if "google" in mapping else None)


class FullConfig(Config):
    __slots__: typing.Sequence[str] = ("database", "emoji_guild", "log_level", "prefixes", "tokens")

    def __init__(
        self,
        *,
        database: DatabaseConfig,
        emoji_guild: typing.Optional[snowflakes.Snowflake] = None,
        log_level: bot.LoggerLevelT = logging.INFO,
        prefixes: typing.Iterable[str] = ("r.",),
        tokens: Tokens,
    ) -> None:
        self.database = database
        self.emoji_guild = emoji_guild
        self.log_level = log_level.upper() if isinstance(log_level, str) else log_level
        self.prefixes = set(prefixes)
        self.tokens = tokens

    @classmethod
    def from_mapping(cls, mapping: typing.Mapping[str, typing.Any], /) -> FullConfig:
        log_level = mapping.get("log_level", logging.DEBUG)
        if not isinstance(log_level, (str, int)):
            raise ValueError("Invalid log level found in config")

        return cls(
            database=DatabaseConfig.from_mapping(mapping["database"]),
            emoji_guild=snowflakes.Snowflake(mapping["emoji_guild"]) if "emoji_guild" in mapping else None,
            log_level=log_level,
            prefixes=list(map(str, mapping["prefixes"])) if "prefixes" in mapping else ("r.",),
            tokens=Tokens.from_mapping(mapping["tokens"]),
        )


def get_config_from_file(file: typing.Optional[pathlib.Path] = None) -> FullConfig:
    if file is None:
        file = pathlib.Path("config.json")
        file = pathlib.Path("config.yaml") if not file.exists() else file

        if not file.exists():
            raise RuntimeError("Couldn't find valid yaml or json configuration file")

    data = file.read_text()
    return FullConfig.from_mapping(yaml.safe_load(data))
