from __future__ import annotations

__all__: typing.Sequence[str] = [
    "generate_command_embed",
    "generate_help_embeds",
    "get_command_doc",
    "get_component_doc",
    "with_docs",
]

import inspect
import typing

from hikari import embeds as embeds_
from yuyo import paginaton

from ..util import constants

if typing.TYPE_CHECKING:
    from tanjun import traits


COMPONENT_DOC_KEY: typing.Final[str] = "REINHARD_COMPONENT_DOC"


def with_docs(component: traits.Component, name: str, doc: str) -> None:
    component.metadata[COMPONENT_DOC_KEY] = (name, doc)


def get_command_doc(command: traits.ExecutableCommand, /) -> typing.Optional[str]:
    return inspect.getdoc(command.function) or None


def get_component_doc(component: traits.Component, /) -> typing.Optional[typing.Tuple[str, str]]:
    return component.metadata.get(COMPONENT_DOC_KEY)


def generate_help_embeds(
    component: traits.Component, /, *, prefix: str = ""
) -> typing.Optional[typing.Tuple[str, typing.Iterator[embeds_.Embed]]]:
    component_info = get_component_doc(component)

    if not component_info:
        return None

    component_name, component_doc = component_info
    command_docs: typing.MutableSequence[str] = []

    for command in component.commands:
        command_doc = get_command_doc(command)
        if (command_name := next(iter(command.names), None)) is None or not command_doc:
            continue

        command_docs.append(f" - {prefix}{command_name}: {command_doc.splitlines()[0]}")

    pages = paginaton.string_paginator(iter(command_docs), wrapper=f"{component_doc}\n {'{}'}")
    embeds = (
        embeds_.Embed(title=f"{component_name}", description=content, colour=constants.embed_colour()).set_footer(
            text=f"page {page + 1}"
        )
        for content, page in pages
    )

    return component_name, embeds


def generate_command_embed(command: traits.ExecutableCommand, /, *, prefix: str = "") -> typing.Optional[embeds_.Embed]:
    if not command.names:
        return None

    if not (command_description := get_command_doc(command)):
        return None

    if len(command.names) > 1:
        command_names = "(" + ", ".join(command.names) + ")"

    else:
        command_names = next(iter(command.names))

    split = command_description.split("\n", 1)

    if len(split) == 2:
        command_description = f"{split[0]}\n```md\n{split[1]}```"

    return embeds_.Embed(
        title=f"{prefix}{command_names}", description=command_description, colour=constants.embed_colour()
    )
