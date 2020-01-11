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
    prefixes: typing.List[str] = dataclasses.field(default_factory=lambda: ["."])
    options: command_client.CommandsClientOptions = dataclasses.field(
        default_factory=command_client.CommandsClientOptions
    )

    def __post_init__(self):
        self.database = DatabaseConfig.from_dict(self.database)
        #  TODO: push changes to hikari
        if self.prefixes is None:
            self.prefixes = ["."]
        if isinstance(self.options, dict):
            self.options = command_client.CommandsClientOptions(
                **self.options
            )  # TODO: from_dict later on
