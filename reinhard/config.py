from __future__ import annotations
import dataclasses


from hikari.orm.models import bases
import typing


from reinhard import command_client


@dataclasses.dataclass()
class DatabaseConfig(bases.MarshalMixin):
    password: str = dataclasses.field(repr=False)
    host: str = dataclasses.field(default="localhost", repr=False)
    user: str = dataclasses.field(default="postgres", repr=False)
    database: str = dataclasses.field(default="postgres", repr=False)
    port: int = dataclasses.field(default=5432, repr=False)


@dataclasses.dataclass()
class Config(bases.MarshalMixin):
    database: DatabaseConfig
    token: str = dataclasses.field(repr=False)
    log_level: str = "INFO"
    prefixes: typing.List[str] = dataclasses.field(default_factory=lambda: ["."])
    options: command_client.CommandClientOptions = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        self.database = DatabaseConfig.from_dict(self.database)
        self.options = command_client.CommandClientOptions.from_dict(self.options)
