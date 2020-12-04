from __future__ import annotations

__all__: typing.Sequence[str] = [
    "generate_command_embeds",
    "generate_help_embeds",
    "get_command_doc",
    "get_component_doc",
    "get_parameter_docs",
    "with_command_doc",
    "with_component_doc",
    "with_parameter_doc",
]

import typing

from hikari import embeds as embeds_
from tanjun import traits
from yuyo import paginaton

if typing.TYPE_CHECKING:
    from tanjun import traits


_CommandT = typing.TypeVar("_CommandT", bound="traits.CommandDescriptor")
_ComponentT = typing.TypeVar("_ComponentT", bound="traits.Component")
DOC_ATTRIBUTE: typing.Final[str] = "__reinhard_doc__"
DOC_FLAG: typing.Final[str] = "doc"
NAME_ATTRIBUTE: typing.Final[str] = "__reinhard_name__"
PARAMETER_DOCS_FLAG: typing.Final[str] = "parameter_docs"


def with_command_doc(doc_string: str, /) -> typing.Callable[[_CommandT], _CommandT]:
    def decorator(command: _CommandT, /) -> _CommandT:
        command.metadata[DOC_FLAG] = doc_string
        return command

    return decorator


def with_component_doc(doc_string: str, /) -> typing.Callable[[typing.Type[_ComponentT]], typing.Type[_ComponentT]]:
    def decorator(component: typing.Type[_ComponentT], /) -> typing.Type[_ComponentT]:
        setattr(component, DOC_ATTRIBUTE, doc_string)
        return component

    return decorator


def with_component_name(name: str, /) -> typing.Callable[[typing.Type[_ComponentT]], typing.Type[_ComponentT]]:
    def decorator(component: typing.Type[_ComponentT]) -> typing.Type[_ComponentT]:
        setattr(component, NAME_ATTRIBUTE, name)
        return component

    return decorator


def with_parameter_doc(parameter: str, doc_string: str, /) -> typing.Callable[[_CommandT], _CommandT]:
    def decorator(command: _CommandT, /) -> _CommandT:
        if PARAMETER_DOCS_FLAG not in command.metadata:
            command.metadata[PARAMETER_DOCS_FLAG] = {}

        command.metadata[PARAMETER_DOCS_FLAG][parameter] = doc_string
        return command

    return decorator


def get_command_doc(command: traits.ExecutableCommand, /) -> typing.Optional[str]:
    return str(command.metadata[DOC_FLAG]) if DOC_FLAG in command.metadata else None


def get_component_doc(component: traits.Component, /) -> typing.Optional[str]:
    return str(getattr(component, DOC_ATTRIBUTE)) if hasattr(component, DOC_ATTRIBUTE) else None


def get_component_name(component: traits.Component, /) -> typing.Optional[str]:
    name = getattr(component, NAME_ATTRIBUTE, None)

    if isinstance(name, str):
        return name

    return type(component).__name__


def get_parameter_docs(command: traits.ExecutableCommand, /) -> typing.Mapping[str, str]:
    docs = command.metadata.get(PARAMETER_DOCS_FLAG)

    if docs is None:
        return {}

    if not isinstance(docs, dict):
        raise RuntimeError("Invalid data found under parameter docs flag metadata")

    return docs


async def generate_help_embeds(
    component: traits.Component, /, *, prefix: str = ""
) -> typing.Optional[typing.Tuple[str, typing.AsyncIterator[embeds_.Embed]]]:
    component_doc = get_component_doc(component)
    component_name = get_component_name(component)

    if component_doc is None or component_name is None:
        return None

    command_docs: typing.MutableSequence[str] = []

    for command in component.commands:
        if (command_name := next(iter(command.names), None)) is None:
            continue

        command_description = get_command_doc(command)
        command_docs.append(f" - {prefix}{command_name}: {command_description}")

    pages = paginaton.string_paginator(iter(command_docs), wrapper=f"{component_doc}\n {'{}'}")
    embeds = (
        embeds_.Embed(title=f"{component_name}", description=content).set_footer(text=f"page {page + 1}")
        async for content, page in pages
    )

    return component_name, embeds


def generate_command_embeds(
    command: traits.ExecutableCommand, /, *, prefix: str = ""
) -> typing.Optional[typing.AsyncIterator[embeds_.Embed]]:
    if not command.names:
        return None

    if (command_description := get_command_doc(command)) is None:
        return None

    if len(command.names) > 1:
        command_names = "(" + ", ".join(command.names) + ")"

    else:
        command_names = next(iter(command.names))

    lines = command_description.splitlines(keepends=False)

    parameter_docs = get_parameter_docs(command)

    if parameter_docs:
        lines.extend(("", "Arguments:"))
        for name, doc in parameter_docs.items():
            lines.append(f" - {name}: {doc}")

    pages = paginaton.string_paginator(iter(lines))
    return (
        embeds_.Embed(title=f"{prefix}{command_names}", description=content).set_footer(text=f"page {page + 1}")
        async for content, page in pages
    )
