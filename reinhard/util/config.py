import typing

import attr
from hikari import bases
from hikari.clients import configs
from hikari.internal import marshaller


@marshaller.marshallable()
@attr.s(slots=False, kw_only=True)
class CommandsConfig:
    access_levels: typing.MutableMapping[bases.Snowflake, int] = marshaller.attrib(
        deserializer=lambda levels: {bases.Snowflake(sn): int(level) for sn, level in levels.items()}
    )
    prefixes: typing.Sequence[str] = marshaller.attrib(
        deserializer=lambda prefixes: [str(prefix) for prefix in prefixes]
    )
    # TODO: handle modules (plus maybe other stuff) here?


@marshaller.marshallable()
@attr.s(slots=False, kw_only=True)
class ParserConfig:
    set_parameters_from_annotations: bool = marshaller.attrib(
        deserializer=bool, default=True, if_undefined=lambda: True
    )


@marshaller.marshallable()
@attr.s(slots=False, kw_only=True)
class CommandClientConfig(configs.BotConfig, CommandsConfig, ParserConfig):
    ...
