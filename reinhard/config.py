from __future__ import annotations
import dataclasses


from hikari.orm.models import bases
import typing


from reinhard.util import command_client


@dataclasses.dataclass()
class DatabaseConfig(bases.MarshalMixin):
    password: str = dataclasses.field(repr=False)
    host: str = dataclasses.field(default="localhost", repr=False)
    user: str = dataclasses.field(default="postgres", repr=False)
    database: str = dataclasses.field(default="postgres", repr=False)
    port: int = dataclasses.field(default=5432, repr=False)


@dataclasses.dataclass()
class BotConfig(bases.MarshalMixin):
    token: str = dataclasses.field(repr=False)
    log_level: str = "INFO"


@dataclasses.dataclass()
class ExtendedOptions(command_client.CommandClientOptions):
    bot: BotConfig = dataclasses.field(default_factory=BotConfig)
    database: DatabaseConfig = dataclasses.field(default_factory=DatabaseConfig)
    prefixes: typing.List[str] = dataclasses.field(default_factory=lambda: ["."])

    def __post_init__(self) -> None:
        self.access_levels = {int(key): value for key, value in self.access_levels.items()}
        self.bot = BotConfig.from_dict(self.bot)
        self.database = DatabaseConfig.from_dict(self.database)
