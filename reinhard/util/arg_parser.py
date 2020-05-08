from __future__ import annotations

import abc
import inspect
import re
import shlex
import typing
import distutils.util

import attr
import click
from hikari import bases
from hikari import channels
from hikari import errors as hikari_errors
from hikari import guilds
from hikari import intents
from hikari import messages
from hikari import users
from hikari.internal import assertions
from hikari.internal import conversions
from hikari.internal import helpers
from hikari.internal import more_collections


from reinhard.util import errors
from reinhard.util import command_client

if typing.TYPE_CHECKING:
    import enum

    from hikari.clients import components as _components


def calculate_missing_flags(
    value: enum.IntFlag, required: enum.IntFlag, origin_enum: typing.Type[enum.IntFlag]
) -> enum.IntFlag:
    missing = origin_enum(0)
    for flag in origin_enum.__members__.values():
        if (flag & required) == flag and (flag & value) != flag:
            missing |= flag
    return missing


class AbstractConverter(abc.ABC):  # These shouldn't be making requests therefore there is no need for async.
    _converter_implementations: typing.List[typing.Tuple[AbstractConverter, typing.Tuple[typing.Type, ...]]]
    inheritable: bool
    missing_intents_default: typing.Optional[AbstractConverter]
    _required_intents: intents.Intent

    def __init_subclass__(cls, **kwargs):
        types = kwargs.pop("types", more_collections.EMPTY_SEQUENCE)
        super().__init_subclass__(**kwargs)
        if not types:
            return

        if not hasattr(AbstractConverter, "_converter_implementations"):
            AbstractConverter._converter_implementations = []

        for base_type in types:
            assertions.assert_that(
                #  get_from_name avoids it throwing errors on an inheritable overlapping with a non-inheritable
                not AbstractConverter.get_converter_from_name(base_type.__name__),
                f"Type {base_type} already registered.",
            )  #  TODO: make sure no overlap between inheritables while allowing overlap between inheritable and non-inheritables

        AbstractConverter._converter_implementations.append((cls(), tuple(types)))
        # Prioritize non-inheritable converters over inheritable ones.
        AbstractConverter._converter_implementations.sort(key=lambda entry: entry[0].inheritable, reverse=False)

    @abc.abstractmethod
    def __init__(
        self,
        inheritable: bool,
        missing_intents_default: typing.Optional[AbstractConverter],
        required_intents: intents.Intent,
    ) -> None:
        self.inheritable = inheritable
        self.missing_intents_default = missing_intents_default  # TODO: get_converter_from_type?
        self._required_intents = required_intents

    @abc.abstractmethod
    def convert(self, ctx: command_client.Context, argument: str) -> typing.Any:  # Cache only
        ...

    def verify_intents(self, components: _components.Components) -> bool:
        failed = []
        for shard in components.shards.values():
            if shard.intents is not None and (self._required_intents & shard.intents) != self._required_intents:
                failed[shard.shard_id] = calculate_missing_flags(self._required_intents, shard.intents, intents.Intent)
        if failed:
            message = (
                f"Missing intents required for {self.__class__.__name__} converter being used on shards. "
                "This will default to pass-through or be ignored."
            )
            helpers.warning(message, category=hikari_errors.IntentWarning, stack_level=4)  # Todo: stack_level
            return True
        return False

    @classmethod
    def get_converter_from_type(cls, argument_type: typing.Type) -> typing.Optional[AbstractConverter]:
        for converter, types in cls._converter_implementations:
            if not converter.inheritable and argument_type not in types:
                continue
            elif converter.inheritable and inspect.isclass(argument_type) and not issubclass(argument_type, types):
                continue
            return converter

    @classmethod
    def get_converter_from_name(cls, name: str) -> typing.Optional[AbstractConverter]:
        for converter, types in cls._converter_implementations:
            if any(base_type.__name__ == name for base_type in types):
                return converter


class BaseIDConverter(AbstractConverter, abc.ABC):
    _id_regex: re.Pattern

    def __init__(
        self,
        inheritable: bool = True,
        missing_intents_default: typing.Optional[AbstractConverter] = None,
        required_intents: intents.Intent = intents.Intent(0),
    ) -> None:
        super().__init__(
            inheritable=inheritable, missing_intents_default=missing_intents_default, required_intents=required_intents
        )

    def _match_id(self, value: str) -> typing.Optional[int]:
        if value.isdigit():
            return int(value)
        if result := self._id_regex.findall(value):
            return result[0]
        raise ValueError("Invalid mention or ID passed.")


class ChannelIDConverter(BaseIDConverter):
    def __init__(
        self,
        inheritable: bool = True,
        missing_intents_default: typing.Optional[AbstractConverter] = None,
        required_intents: intents.Intent = intents.Intent(0),
    ) -> None:
        super().__init__(
            inheritable=inheritable, missing_intents_default=missing_intents_default, required_intents=required_intents
        )
        self._id_regex = re.compile(r"<#(\d+)>")

    def convert(self, _: command_client.Context, argument: str) -> typing.Any:
        return self._match_id(argument)


class ChannelConverter(ChannelIDConverter, types=(channels.PartialChannel,)):
    def __init__(self):
        super().__init__(
            inheritable=True, missing_intents_default=ChannelIDConverter(), required_intents=intents.Intent.GUILDS,
        )

    def convert(self, ctx: command_client.Context, argument: str) -> channels.PartialChannel:
        if match := self._match_id(argument):
            return ctx.fabric.state_registry.get_mandatory_channel_by_id(match)  # TODO: cache


class SnowflakeConverter(BaseIDConverter, types=(bases.UniqueEntity,)):
    def __init__(
        self,
        inheritable: bool = True,
        missing_intents_default: typing.Optional[AbstractConverter] = None,
        required_intents: intents.Intent = intents.Intent(0),
    ) -> None:
        super().__init__(
            inheritable=inheritable, missing_intents_default=missing_intents_default, required_intents=required_intents,
        )
        self._id_regex = re.compile(r"<[(?:@!?)#&](\d+)>")

    def convert(self, ctx: command_client.Context, argument: str) -> int:
        if match := self._match_id(argument):
            return int(match)
        raise ValueError("Invalid mention or ID supplied.")


class UserConverter(BaseIDConverter, types=(users.User,)):
    def __init__(
        self,
        inheritable: bool = False,
        missing_intents_default: typing.Optional[AbstractConverter] = None,
        required_intents: intents.Intent = intents.Intent.GUILD_MEMBERS,
    ) -> None:  # TODO: Intent.GUILD_MEMBERS and/or intents.GUILD_PRESENCES?
        super().__init__(
            inheritable=inheritable,
            missing_intents_default=missing_intents_default or SnowflakeConverter(),
            required_intents=required_intents,
        )
        self._id_regex = re.compile(r"<@!?(\d+)>")

    def convert(self, ctx: command_client.Context, argument: str) -> users.User:
        if match := self._match_id(argument):
            return ctx.fabric.state_registry.get_mandatory_user_by_id(match)


class MemberConverter(UserConverter, types=(guilds.GuildMember,)):
    def convert(self, ctx: command_client.Context, argument: str) -> guilds.GuildMember:
        if not ctx.message.guild:
            raise ValueError("Cannot get a member from a DM channel.")  # TODO: better error and error

        if match := self._match_id(argument):
            return ctx.fabric.state_registry.get_mandatory_member_by_id(match, ctx.message.guild_id)


class MessageConverter(SnowflakeConverter, types=(messages.Message,)):
    def __init__(self) -> None:  # TODO: message cache checks?
        super().__init__(
            inheritable=False, missing_intents_default=SnowflakeConverter(), required_intents=intents.Intent(0)
        )

    def convert(self, ctx: command_client.Context, argument: str) -> messages.Message:
        message_id = super().convert(ctx, argument)
        return ctx.fabric.state_registry.get_mandatory_message_by_id(message_id, ctx.message.channel_id)
        #  TODO: state and error handling?


class AbstractCommandParser(abc.ABC):
    @abc.abstractmethod
    def parse(self, ctx: command_client.Context) -> typing.MutableMapping[str, typing.Any]:
        ...

    @abc.abstractmethod
    def resolve_and_validate_annotations(self, components: _components.Components) -> None:
        ...

    @abc.abstractmethod
    def trim_parameters(self, to_trim: int) -> None:
        """
        Trim parameters from our list, will usually be `1` to trim `context`
        or `2` to trim both the `self` and `context` arguments.

        Arguments:
            to_trim:
                The :class:`int` amount of parameters to trim.

        Raises:
            KeyError:
                If the `to_trim` passed is higher than the amount of known parameters.
        """


BUILTIN_OVERRIDES = {bool: distutils.util.strtobool}


SUPPORTED_TYPING_WRAPPERS = (typing.Union,)  # typing.Optional just resolves to typing.Union[type, NoneType]

POSITIONAL_TYPES = (
    inspect.Parameter.VAR_POSITIONAL,
    inspect.Parameter.POSITIONAL_ONLY,
)


@attr.attrs(init=False, slots=True)
class CommandParser(AbstractCommandParser):
    _converters: typing.Mapping[str, typing.Tuple[typing.Tuple[typing.Callable, bool], ...]] = attr.attrib()
    greedy: typing.Optional[str] = attr.attrib()
    _option_parser: typing.Optional[click.OptionParser] = attr.attrib()
    _shlex: shlex.shlex
    signature: inspect.Signature = attr.attrib()

    def __init__(
        self,
        func: typing.Callable[[...], typing.Coroutine[typing.Any, typing.Any, typing.Any]],
        greedy: typing.Optional[str] = None,
    ) -> None:
        self._converters = {}
        self.greedy = greedy
        self._option_parser = None
        self._shlex = shlex.shlex("", posix=True)
        self._shlex.whitespace = "\t\r "
        self._shlex.whitespace_split = True
        self._shlex.commenters = ""
        self.signature = conversions.resolve_signature(func)
        # Remove the `ctx` arg for now, `self` should be trimmed by the command object itself.
        self.trim_parameters(1)

    def _convert(self, ctx: command_client.Context, value: str, parameter: inspect.Parameter) -> typing.Any:
        if parameter.annotation is parameter.empty:
            return value

        failed = []
        for converter, requires_ctx in self._converters[parameter.name]:
            try:
                if requires_ctx:
                    return converter(ctx, value)
                else:
                    return converter(value)
            except Exception as exc:
                failed.append(exc)
        if failed:
            raise errors.ConversionError(
                msg=f"Invalid value for argument `{parameter.name.replace('_', '-')}`.", origins=failed
            ) from failed[0]
        return value

    def _resolve_annotation(
        self, components: _components.Components, annotation: typing.Any
    ) -> typing.Union[typing.Any, typing.Sequence[typing.Any], None]:
        if args := typing.get_args(annotation):
            return tuple((self._resolve_annotation(components, arg) for arg in args if arg not in (type(None), None)))

        if converter := AbstractConverter.get_converter_from_type(annotation):
            if not converter.verify_intents(components):
                return converter.missing_intents_default, True if converter.missing_intents_default else None
            return converter, True
        return BUILTIN_OVERRIDES.get(annotation, annotation), False

    def resolve_and_validate_annotations(self, components: _components.Components) -> None:
        greedy_found = False
        parser = click.OptionParser()
        var_position = False
        # As this doesn't handle defaults, we have to do that ourselves.
        parser.ignore_unknown_options = True
        assertions.assert_that(
            not self.greedy or self.greedy in self.signature.parameters, f"Unknown greedy argument set `{self.greedy}`."
        )
        for key, value in self.signature.parameters.items():
            assertions.assert_that(
                value.kind not in POSITIONAL_TYPES or not greedy_found,
                "Positional arguments after a greedy argument aren't supported by this parser.",
            )
            if origin := typing.get_origin(value.annotation):
                assertions.assert_that(
                    origin in SUPPORTED_TYPING_WRAPPERS, f"Typing wrapper `{origin}` is not supported by this parser."
                )
                self._converters[key] = self._resolve_annotation(components=components, annotation=value.annotation)
            elif value.annotation is inspect.Parameter.empty:
                self._converters[key] = ()
            else:
                converter = self._resolve_annotation(components=components, annotation=value.annotation)
                self._converters[key] = (converter,) if converter is not None else ()

            if self.greedy == key:
                greedy_found = True
            # We don't want this to parse greedy arguments
            elif value.default is inspect.Parameter.empty and value.kind is not value.VAR_POSITIONAL:
                parser.add_argument(key)
            elif value.kind is not value.VAR_POSITIONAL:
                parser.add_option([f"--{key.replace('_', '-')}"], key)
            assertions.assert_that(value.kind is not value.VAR_KEYWORD, "**kwargs are not supported by this parser.")
            var_position = value.kind is value.VAR_POSITIONAL
        assertions.assert_that(
            not (var_position and self.greedy), "The `greedy` parser flag and *args are mutually exclusive."
        )
        self._option_parser = parser

    def trim_parameters(self, to_trim: int) -> None:
        parameters = list(self.signature.parameters.values())
        try:
            self.signature = self.signature.replace(parameters=parameters[to_trim:])
        except KeyError:
            raise KeyError("Missing required parameter (likely `self` or `ctx`).")

        for parameter in parameters[:to_trim]:
            if parameter.name in self._converters:
                del self._converters[parameter.name]

    def parse(
        self, ctx: command_client.Context
    ) -> typing.Tuple[typing.Sequence[typing.Any], typing.MutableMapping[str, typing.Any]]:
        args: typing.Sequence[typing.Any] = []
        kwargs: typing.MutableMapping[str, typing.Any] = {}
        if ctx.content:
            self._shlex.push_source(ctx.content)
            self._shlex.state = " "
        try:
            values, arguments, _ = self._option_parser.parse_args(list(self._shlex) if ctx.content else [])
        except Exception as exc:
            raise errors.ConversionError(str(exc), [exc]) from exc

        if self.greedy:
            parameter = self.signature.parameters[self.greedy]
            result = self._convert(ctx, " ".join(arguments), parameter)
            if parameter.kind in POSITIONAL_TYPES:
                args.append(result)
            else:
                kwargs[parameter.name] = result
            arguments = []

        for parameter in self.signature.parameters.values():
            # Just a typing hack, may be removed in the future.
            parameter: inspect.Parameter
            # greedy and VAR_POSITIONAL should be exclusive anyway
            if parameter.name == self.greedy:
                continue

            # If we reach a VAR_POSITIONAL parameter then we want to consume all of the positional arguments.
            if parameter.kind is parameter.VAR_POSITIONAL:
                args.extend(self._convert(ctx, value, parameter) for value in arguments)
                continue

            # VAR_POSITIONAL parameters should default to an empty tuple anyway.
            if (value := values.get(parameter.name)) is None and parameter.default is parameter.empty:
                raise errors.ConversionError(f"Missing required argument `{parameter.name}`")

            if value is None:
                value = parameter.default
            else:
                value = self._convert(ctx, value, parameter)

            if parameter.kind in POSITIONAL_TYPES:
                args.append(value)
            else:
                kwargs[parameter.name] = value
        return args, kwargs
