from __future__ import annotations

import abc
import contextlib
import inspect
import re
import typing

from hikari.internal_utilities import assertions
from hikari.internal_utilities import containers
from hikari.orm.models import bases
from hikari.orm.models import channels
from hikari.orm.models import members
from hikari.orm.models import messages
from hikari.orm.models import users


from reinhard.util import command_client

if typing.TYPE_CHECKING:
    from hikari.internal_utilities import aio

QUOTE_SEPARATORS = ('"', "'")


def basic_arg_parsers(content: str, ceiling: typing.Optional[int]) -> typing.Iterator[str]:
    last_space: int = -1
    spaces_found_while_quoting: typing.List[int] = []
    last_quote: typing.Optional[int] = None
    i: int = -1
    count: int = 1
    while i < len(content):
        i += 1
        char = content[i] if i != len(content) else " "
        if char == " " and i - last_space > 1:
            if last_quote:
                spaces_found_while_quoting.append(i)
                continue
            elif ceiling and count == ceiling:
                yield content[last_space + 1 :]
                return
            else:
                count += 1
                yield content[last_space + 1 : i]
                last_space = i

        elif char in QUOTE_SEPARATORS:  # and content[i -  1] != "\\":
            if last_quote is None:
                last_quote = i
                spaces_found_while_quoting.append(last_space)
            elif content[last_quote] == char:
                count += 1
                yield content[last_quote + 1 : i]
                last_space = i
                spaces_found_while_quoting.clear()
                last_quote = None

    if last_quote:
        i = 1
        while i < len(spaces_found_while_quoting):
            yield content[spaces_found_while_quoting[i - 1] + 1 : spaces_found_while_quoting[i]]
            spaces_found_while_quoting.pop(i - 1)


class ConversionError(ValueError):
    ...  # TODO: this


class AbstractConverter(abc.ABC):
    _converter_implementations: typing.List[typing.Tuple[type(AbstractConverter), typing.Tuple[typing.Type]]] = []
    inheritable: bool

    def __init_subclass__(cls, **kwargs):
        types = kwargs.pop("types", containers.EMPTY_SEQUENCE)
        inheritable = kwargs.pop("inheritable", False)
        super().__init_subclass__(**kwargs)
        for base_type in types:
            assertions.assert_that(
                not cls.get_converter_from_type(base_type), f"Type {base_type} already registered.",
            )
        cls.inheritable = inheritable
        cls._converter_implementations.append((cls(), tuple(types)))

    @abc.abstractmethod
    async def convert(self, ctx: command_client.Context, argument: str) -> typing.Any:
        ...

    @classmethod
    def get_converter_from_type(cls, argument_type: typing.Type) -> typing.Optional[AbstractConverter]:
        for converter in cls._converter_implementations:
            if not converter[0].inheritable and argument_type not in converter[1]:
                continue
            elif (
                converter[0].inheritable
                and inspect.isclass(argument_type)
                and not issubclass(argument_type, converter[1])
            ):
                continue
            return converter[0]

    @classmethod
    def get_converter_from_name(cls, name: str) -> typing.Optional[AbstractConverter]:
        for converter in cls._converter_implementations:
            if any(base_type.__name__ == name for base_type in converter[1]):
                return converter[0]


class BaseIDConverter(AbstractConverter, abc.ABC):
    _id_regex: re.Pattern

    def _match_id(self, value: str) -> typing.Optional[int]:
        if value.isdigit():
            return int(value)
        if result := self._id_regex.findall(value):
            return result[0]
        raise command_client.CommandError("Invalid mention or ID passed.")


class ChannelConverter(BaseIDConverter, types=(channels.Channel,), inheritable=True):
    def __init__(self):
        self._id_regex = re.compile(r"<#(\d+)>")

    async def convert(self, ctx: command_client.Context, argument: str) -> channels.Channel:
        if match := self._match_id(argument):
            return ctx.fabric.state_registry.get_mandatory_channel_by_id(match)


class SnowflakeConverter(BaseIDConverter, types=(bases.SnowflakeMixin,)):
    def __init__(self) -> None:
        self._id_regex = re.compile(r"<[(?:@!?)#&](\d+)>")

    async def convert(self, ctx: command_client.Context, argument: str) -> int:
        if match := self._match_id(argument):
            return int(match)
        raise command_client.CommandError("Invalid mention or ID supplied.")


class UserConverter(BaseIDConverter, types=(users.User,)):
    def __init__(self) -> None:
        self._id_regex = re.compile(r"<@!?(\d+)>")

    async def convert(self, ctx: command_client.Context, argument: str) -> users.BaseUser:
        if match := self._match_id(argument):
            return ctx.fabric.state_registry.get_mandatory_user_by_id(match)


class MemberConverter(UserConverter, types=(members.Member,)):
    async def convert(self, ctx: command_client.Context, argument: str) -> members.Member:
        if not ctx.message.guild:
            raise ConversionError("Cannot get a member from a DM channel.")  # TODO: better error

        if match := self._match_id(argument):
            return ctx.fabric.state_registry.get_mandatory_member_by_id(match, ctx.message.guild_id)


class MessageConverter(SnowflakeConverter, types=(messages.Message,)):
    async def convert(self, ctx: command_client.Context, argument: str) -> messages.Message:
        message_id = super().convert(ctx, argument)
        return ctx.fabric.state_registry.get_mandatory_message_by_id(message_id, ctx.message.channel_id)


class AbstractCommandParser(abc.ABC):
    @abc.abstractmethod
    async def parse(self, ctx: command_client.Context) -> typing.MutableMapping[str, typing.Any]:
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


GLOBAL_CONVERTERS = {"int": int, "str": str, "float": float, "bool": bool}

SUPPORTED_TYPING_WRAPPERS = (typing.Union,)

POSITIONAL_TYPES = (
    inspect.Parameter.VAR_POSITIONAL,
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD,
)


class CommandParser(AbstractCommandParser):
    __slots__ = ("greedy", "signature", "parameters")

    greedy: bool
    signature: inspect.Signature
    parameters: typing.MutableMapping[str, inspect.Parameter]

    def __init__(self, func: aio.CoroutineFunctionT, greedy: bool) -> None:
        self.greedy = greedy
        self.signature = inspect.signature(func)
        self.parameters = self.signature.parameters.copy()
        self._resolve_and_validate_parameters(func)
        # Remove the `context` arg for now, `self` should be trimmed during binding.
        self.trim_parameters(1)

    @staticmethod
    async def _convert_value(ctx: command_client.Context, value: str, annotation) -> typing.Any:
        if converter := AbstractConverter.get_converter_from_type(annotation):
            return await converter.convert(ctx, value)
        try:
            return annotation(value)
        except (TypeError, ValueError) as e:
            raise command_client.CommandError(f"Invalid value provided: {e}")

    async def _convert(self, ctx: command_client.Context, value: str, parameter: inspect.Parameter) -> typing.Any:
        if parameter.annotation is parameter.empty:
            return value

        if typing.get_origin(parameter.annotation) is typing.Union:
            for potential_type in parameter.annotation.__args__:
                if potential_type is None:
                    continue

                with contextlib.suppress(command_client.CommandError):
                    return await self._convert_value(ctx, value, potential_type)
                # TODO: sane default? and handle errors better?
            raise command_client.CommandError(f"Invalid value for argument `{parameter.name}`.")
        return await self._convert_value(ctx, value, parameter.annotation)

    def _resolve_and_validate_parameters(self, func: aio.CoroutineFunctionT) -> None:
        var_position = False
        resolved_type_hints = None
        for key, value in self.parameters.items():
            # If a value is a string than it is a future reference and will need to be resolved.
            if isinstance(value.annotation, str):
                if not resolved_type_hints:
                    #    # TODO: typing.get_type_hints isn't always following wrapped scopes.
                    #    nsobj = func
                    #    while hasattr(nsobj, "__wrapped__"):
                    #        nsobj = nsobj.__wrapped__
                    #    scope = nsobj.__globals__
                    resolved_type_hints = typing.get_type_hints(func)  # , scope)
                self.parameters[key] = value.replace(annotation=resolved_type_hints[value.name])
            if origin := typing.get_origin(self.parameters[key].annotation):
                assertions.assert_that(
                    origin in SUPPORTED_TYPING_WRAPPERS, f"Typing wrapper `{origin}` is not supported by this parser."
                )
            assertions.assert_that(value.kind is not value.VAR_KEYWORD, "**kwargs are not supported by this parser.")
            assertions.assert_that(not var_position, "Keyword arguments after *args are not supported by this parser.")
            var_position = value.kind is value.VAR_POSITIONAL

    def trim_parameters(self, to_trim: int) -> None:
        while to_trim != 0:
            try:
                self.parameters.popitem(last=False)
            except KeyError:
                raise KeyError("Missing required parameter (likely `self` or `context`).")
            else:
                to_trim -= 1

    @staticmethod
    def _get_next_argument(arguments: typing.Iterator[str]) -> typing.Optional[str]:
        try:
            return next(arguments)
        except StopIteration:
            return None

    async def parse(
        self, ctx: command_client.Context
    ) -> typing.Tuple[typing.List[typing.Any], typing.MutableMapping[str, typing.Any]]:
        args: typing.List[typing.Any] = []
        kwargs: typing.MutableMapping[str, typing.Any] = {}
        arguments = basic_arg_parsers(ctx.content, ceiling=len(self.parameters) if self.greedy else None)
        for parameter in self.parameters.values():
            # Just a typing hack, may be removed in the future.
            parameter: inspect.Parameter
            if (
                not (value := self._get_next_argument(arguments))
                and parameter.default is parameter.empty
                # VAR_POSITIONAL parameters should default to an empty tuple anyway.
                and parameter.kind is not parameter.VAR_POSITIONAL
            ):
                raise command_client.CommandError(f"Missing required argument `{parameter.name}`")
            elif not value:
                break

            while True:
                result = await self._convert(ctx, value, parameter)
                if parameter.kind in POSITIONAL_TYPES:
                    args.append(result)
                else:
                    kwargs[parameter.name] = result

                # If we reach a VAR_POSITIONAL parameter we want to want to
                # consume the remaining arguments as positional arguments.
                if parameter.kind is not parameter.VAR_POSITIONAL or not (value := self._get_next_argument(arguments)):
                    break
        return args, kwargs
