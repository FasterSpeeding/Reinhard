# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__: list[str] = [
    "generate_command_embed",
    "generate_help_embeds",
    "get_command_doc",
    "get_component_doc",
    "with_docs",
]

import inspect
import typing
from collections import abc as collections

from hikari import embeds as embeds_
from yuyo import pagination

from ..utility import constants

if typing.TYPE_CHECKING:
    from tanjun import abc as tanjun_abc


COMPONENT_DOC_KEY: typing.Final[str] = "REINHARD_COMPONENT_DOC"


def with_docs(component: tanjun_abc.Component, name: str, doc: str) -> None:
    component.metadata[COMPONENT_DOC_KEY] = (name, doc)


def get_command_doc(command: tanjun_abc.MessageCommand, /) -> str | None:
    return inspect.getdoc(command.callback) or None


def get_component_doc(component: tanjun_abc.Component, /) -> tuple[str, str] | None:
    return component.metadata.get(COMPONENT_DOC_KEY)


def generate_help_embeds(
    component: tanjun_abc.Component, /, *, prefix: str = ""
) -> tuple[str, collections.Iterator[embeds_.Embed]] | None:
    component_info = get_component_doc(component)

    if not component_info:
        return None

    component_name, component_doc = component_info
    command_docs: list[str] = []

    for command in component.message_commands:
        command_doc = get_command_doc(command)
        if (command_name := next(iter(command.names), None)) is None or not command_doc:
            continue

        command_docs.append(f" - {prefix}{command_name}: {command_doc.splitlines()[0]}")

    pages = pagination.sync_paginate_string(iter(command_docs), wrapper=f"{component_doc}\n {'{}'}")
    embeds = (
        embeds_.Embed(title=f"{component_name}", description=content, colour=constants.embed_colour()).set_footer(
            text=f"page {page + 1}"
        )
        for content, page in pages
    )

    return component_name, embeds


def generate_command_embed(command: tanjun_abc.MessageCommand, /, *, prefix: str = "") -> embeds_.Embed | None:
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
