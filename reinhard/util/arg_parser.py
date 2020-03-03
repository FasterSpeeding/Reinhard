from __future__ import annotations

import abc
import inspect
import re
import typing


from hikari.internal_utilities import assertions
from hikari.internal_utilities import containers


from reinhard.util import command_client


if typing.TYPE_CHECKING:
    from hikari.internal_utilities import aio
    from hikari.orm import fabric


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


class AbstractConverter(abc.ABC):
    _converter_implementations: typing.List[typing.Tuple[type(AbstractConverter), typing.Tuple[typing.Type]]] = []

    def __init_subclass__(cls, **kwargs):
        types = kwargs.pop("types", containers.EMPTY_SEQUENCE)
        super().__init_subclass__(**kwargs)
        for base_type in types:
            assertions.assert_that(
                not cls.get_converter_from_type(base_type), f"Type {base_type} already registered.",
            )
        cls._converter_implementations.append((cls, tuple(types)))

    @abc.abstractmethod
    async def convert(self, fabric_obj: fabric.Fabric, argument: str) -> typing.Any:
        ...

    @classmethod
    def get_converter_from_type(cls, argument_type: typing.Type) -> typing.Optional[AbstractConverter]:
        for converter in cls._converter_implementations:
            if argument_type in converter[1]:
                return converter[0]

    @classmethod
    def get_converter_from_name(cls, name: str) -> typing.Optional[AbstractConverter]:
        for converter in cls._converter_implementations:
            if any(base_type.__name__ == name for base_type in converter[1]):
                return converter[0]


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


SNOWFLAKE_REG = re.compile(r"<[(?:@!?)#&](\d+)>")
# TODO: doesn't support role mentions


def get_snowflake(content: str) -> int:
    if content.isdigit():
        sf = content
    else:
        if matches := SNOWFLAKE_REG.findall(content):
            sf = matches[0]
        else:
            raise command_client.CommandError("Invalid mention or ID supplied.")
    return int(sf)


GLOBAL_CONVERTERS = {"int": int, "str": str, "snowflake": get_snowflake, "float": float, "bool": bool}
# TODO: handle snowflake properly

TYPE_ENCAPSULATION_REG = re.compile(r"(?<=\[).+?(?=\])")


class CommandParser(AbstractCommandParser):
    __slots__ = ("greedy", "signature", "parameters")

    greedy: bool
    signature: inspect.Signature
    parameters: typing.MutableMapping[str, inspect.Parameter]

    def __init__(self, func: aio.CoroutineFunctionT, greedy: bool) -> None:
        self.greedy = greedy
        self.signature = inspect.signature(func)
        self.parameters = self.signature.parameters.copy()
        for key, value in self.parameters.items():
            # If a value is a string than it is a future reference and will need to be retrieved.
            if isinstance(value.annotation, str):
                self.parameters[key] = value.replace(
                    annotation=self._try_resolve_forward_reference(func, value.annotation)
                )
        # Remove the `context` arg for now, `self` should be trimmed during binding.
        self.trim_parameters(1)

    @staticmethod
    def _try_resolve_forward_reference(func: aio.CoroutineFunctionT, reference: str) -> typing.Optional[typing.Any]:
        # OWO YIKES but PEP-563 forced me to do it sir.
        # This regex matches any instances where a type may be wrapped by typing (e.g. typing.Optional[str]).
        if match := TYPE_ENCAPSULATION_REG.search(reference):
            reference = match.group()

        # If it's a builtin it shouldn't ever be a path.
        if (converter := GLOBAL_CONVERTERS.get(reference)) is None:
            # Handle both paths and top level attributes.
            path = iter(reference.split("."))
            converter = func.__globals__.get(next(path))
            for attr in path:
                converter = getattr(converter, attr)
        return converter

    @staticmethod
    async def _convert(fabric_obj: fabric.Fabric, value: str, parameter: inspect.Parameter) -> typing.Any:
        if parameter.annotation is parameter.empty:
            return value
        # TODO: typing.Optional?
        if converter := AbstractConverter.get_converter_from_type(parameter.annotation):
            return await converter.convert(fabric_obj, value)
        else:
            return parameter.annotation(value)

    def trim_parameters(self, to_trim: int):
        while to_trim != 0:
            try:
                self.parameters.popitem(last=False)
            except KeyError:
                raise KeyError("Missing required parameter (likely `self` or `context`).")
            else:
                to_trim -= 1

    async def parse(
        self, ctx: command_client.Context
    ) -> typing.Tuple[typing.List[typing.Any], typing.MutableMapping[str, typing.Any]]:
        args: typing.List[typing.Any] = []
        kwargs: typing.MutableMapping[str, typing.Any] = {}
        arguments = basic_arg_parsers(ctx.content, ceiling=len(self.parameters) if self.greedy else None)
        # values_to_skip = 0
        for parameter in self.parameters.values():
            parameter: inspect.Parameter
            try:
                value = next(arguments)
            except StopIteration:
                if parameter.default is parameter.empty:
                    raise command_client.CommandError(f"Missing required argument `{parameter.name}`")
                else:
                    break
            else:
                result = await self._convert(ctx.fabric, value, parameter)
                if parameter.kind is parameter.POSITIONAL_ONLY:
                    args.append(result)
                else:
                    kwargs[parameter.name] = result
        return args, kwargs
