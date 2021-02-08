from __future__ import annotations

__all__: typing.Sequence[str] = ["DatabaseConfig", "Tokens", "FullConfig"]

import abc
import logging
import os
import pathlib
import typing

import yaml
from hikari import snowflakes

ConfigT = typing.TypeVar("ConfigT", bound="Config")
DefaultT = typing.TypeVar("DefaultT")
ValueT = typing.TypeVar("ValueT")


def _cast_or_default(
    data: typing.Mapping[typing.Any, typing.Any],
    key: str,
    cast: typing.Callable[[typing.Any], ValueT],
    default: DefaultT,
) -> typing.Union[ValueT, DefaultT]:
    return cast(data[key]) if key in data else default


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
            database=_cast_or_default(mapping, "database", str, "postgres"),
            host=_cast_or_default(mapping, "host", str, "localhost"),
            port=_cast_or_default(mapping, "port", int, 5432),
            user=_cast_or_default(mapping, "user", str, "postgres"),
        )


class Tokens(Config):
    __slots__: typing.Sequence[str] = ("bot", "google", "spotify_id", "spotify_secret")

    def __init__(
        self,
        bot: str,
        *,
        google: typing.Optional[str] = None,
        spotify_id: typing.Optional[str] = None,
        spotify_secret: typing.Optional[str] = None,
    ) -> None:
        self.bot = bot
        self.google = google
        self.spotify_id = spotify_id
        self.spotify_secret = spotify_secret

    @classmethod
    def from_mapping(cls, mapping: typing.Mapping[str, typing.Any], /) -> Tokens:
        return cls(
            bot=str(mapping["bot"]),
            google=_cast_or_default(mapping, "google", str, None),
            spotify_id=_cast_or_default(mapping, "spotify_id", str, None),
            spotify_secret=_cast_or_default(mapping, "spotify_secret", str, None),
        )


class FullConfig(Config):
    __slots__: typing.Sequence[str] = ("database", "emoji_guild", "log_level", "prefixes", "tokens")

    def __init__(
        self,
        *,
        database: DatabaseConfig,
        emoji_guild: typing.Optional[snowflakes.Snowflake] = None,
        log_level: typing.Union[None, int, str, typing.Dict[str, typing.Any]] = logging.INFO,
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
        log_level = mapping.get("log_level", logging.INFO)
        if not isinstance(log_level, (str, int)):
            raise ValueError("Invalid log level found in config")

        return cls(
            database=DatabaseConfig.from_mapping(mapping["database"]),
            emoji_guild=_cast_or_default(mapping, "emoji_guild", snowflakes.Snowflake, None),
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


def load_config() -> FullConfig:
    config_location = os.getenv("REINHARD_CONFIG_FILE")
    config_path = pathlib.Path(config_location) if config_location else None

    if config_path and not config_path.exists():
        raise RuntimeError("Invalid configuration given in environment variables")

    return get_config_from_file(config_path)
