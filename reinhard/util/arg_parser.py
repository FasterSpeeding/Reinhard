from __future__ import annotations

import abc
import inspect
import typing


from reinhard.util import command_client


if typing.TYPE_CHECKING:
    from hikari.internal_utilities import aio
    from hikari.orm import fabric


QUOTE_SEPARATORS = ('"', "'")


def basic_arg_parsers(content: str) -> typing.Iterator[str]:
    last_space: int = -1
    spaces_found_while_quoting: typing.List[int] = []
    last_quote: typing.Optional[int] = None
    i: int = -1
    while i < len(content):
        i += 1
        char = content[i] if i != len(content) else " "
        if char == " " and i - last_space > 1:
            if last_quote:
                spaces_found_while_quoting.append(i)
                continue
            else:
                yield content[last_space + 1 : i]
                last_space = i
        elif char in QUOTE_SEPARATORS:  # and content[i -  1] != "\\":
            if last_quote is None:
                last_quote = i
                spaces_found_while_quoting.append(last_space)
            elif content[last_quote] == char:
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
    _converter_implementations: typing.MutableMapping[typing.Type : AbstractCommandParser] = {}

    def __init_subclass__(cls, **kwargs):
        base_type = kwargs.pop("base_type", None)
        super().__init_subclass__(**kwargs)
        if base_type:
            cls._converter_implementations[base_type] = cls

    @abc.abstractmethod
    async def convert(self, fabric_obj: fabric.Fabric, argument: str) -> typing.Any:
        ...

    @classmethod
    def get_converter_from_type(cls, argument_type: typing.Type) -> typing.Optional[AbstractConverter]:
        return cls._converter_implementations.get(argument_type)


class AbstractCommandParser(abc.ABC):
    @abc.abstractmethod
    async def parse(self, content: str) -> typing.MutableMapping[str, typing.Any]:
        ...


BUILTIN_CONVERTERS = {"int": int, "str": str, "float": float, "snowflake": int}  # CONTEXT?


class CommandParser(AbstractCommandParser):
    __slots__ = ("signature",)

    signature: inspect.Signature

    def __init__(self, func: aio.CoroutineFunctionT) -> None:
        self.signature = inspect.signature(func)

    @staticmethod
    async def _convert(
        fabric_obj: fabric.Fabric, value: str, parameter: inspect.Parameter
    ) -> typing.Any:  # TODO: fabric?
        if parameter.annotation is parameter.empty:
            return value
        # TODO: typing.Optional?
        converter = AbstractConverter.get_converter_from_type(parameter.annotation)
        if converter:
            return await converter.convert(fabric_obj, value)
        return BUILTIN_CONVERTERS.get(parameter.annotation, str)(value)

    async def parse(
        self, ctx: command_client.Context  # TODO: handle end arg optionally grey gooing the rest of the content
    ) -> typing.Tuple[typing.List[typing.Any], typing.MutableMapping[str, typing.Any]]:
        args: typing.List[typing.Any] = []
        kwargs: typing.MutableMapping[str, typing.Any] = {}
        arguments = basic_arg_parsers(ctx.content)
        # values_to_skip = 0
        for parameter in self.signature.parameters.values():
            parameter: inspect.Parameter
            try:
                # if next(arguments).name == "self":
                #   values_to_skip += 1
                value = next(arguments)  # TODO: skip `self` and `ctx`
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


if __name__ == "__main__":

    async def test(
        zz, /, x: int, y: str = "", z: typing.Optional[str] = None, aaa: command_client.Command = None
    ) -> None:
        ...

    import asyncio

    foo = CommandParser(test)
    print(asyncio.run(foo.parse(type("X", (object,), {"content": "I 2 2 2 2 2 2 2 2 2", "fabric": None}))))
