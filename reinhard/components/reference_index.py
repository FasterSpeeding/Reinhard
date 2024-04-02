# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2024, Faster Speeding
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
"""Commands used to find the references for a type in Hikari and Tanjun."""
from __future__ import annotations

__slots__: list[str] = ["load_reference"]

import dataclasses
import json
import os
import pathlib
import typing
from collections import abc as collections

import alluka
import hikari
import hikari.events
import hikari.interactions
import tanjun
import yuyo
from tanchan.components import buttons

from .. import utility

if typing.TYPE_CHECKING:
    from typing_extensions import Self

_MessageCommandT = typing.TypeVar("_MessageCommandT", bound=tanjun.MessageCommand[typing.Any])
_SlashCommandT = typing.TypeVar("_SlashCommandT", bound=tanjun.SlashCommand[typing.Any])


_END_KEY = "_link"
_INDEXES_DIR = pathlib.Path(os.environ.get("REINHARD_INDEX_DIR", "./"))


def _search_tree(index: dict[str, typing.Any], path: str, partial_search: bool = False) -> collections.Iterator[str]:
    for char in path.rsplit(".", 1)[-1].lower():
        if new_position := index.get(char):
            index = new_position
            continue

        return None

    if end := index.get(_END_KEY):
        key: str
        for key in end:
            if partial_search or key.endswith(path):
                yield key


@dataclasses.dataclass(slots=True)
class ReferenceIndex:
    """Index used for tracking references to types in specified modules."""

    _aliases: dict[str, str]
    _alias_search_tree: dict[str, typing.Any]
    _object_paths_to_uses: dict[str, list[str]]
    _object_search_tree: dict[str, typing.Any]
    _version: str

    @classmethod
    def from_file(cls, path: pathlib.Path, /) -> Self:
        with path.open("r") as file:
            data = json.load(file)

        return cls(
            _aliases=data["aliases"],
            _alias_search_tree=data["alias_search_tree"],
            _object_paths_to_uses=data["object_paths_to_uses"],
            _object_search_tree=data["object_search_tree"],
            _version=data["version"],
        )

    @property
    def version(self) -> str:
        return self._version

    def search(self, path: str, /) -> tuple[str, collections.Sequence[str]] | None:
        """Search for a type to get its references.

        Parameters
        ----------
        path
            Partial path of the type to search for.

            This will be matched case-insensitively.

        Returns
        -------
        tuple[str, collections.abc.Sequence[str]] | None
            The type's full path and a list of references to it.

            If the type was not found then `None` is returned.
        """
        if result := next(_search_tree(self._object_search_tree, path), None):
            return (result, self._object_paths_to_uses[result])

        if result := next(_search_tree(self._alias_search_tree, path), None):
            result = self._aliases[result]
            return result, self._object_paths_to_uses[result]

    def search_paths(self, path: str, /, partial_search: bool = False) -> collections.Iterator[str]:
        yield from _search_tree(self._object_search_tree, path, True)
        yield from _search_tree(self._alias_search_tree, path, True)

    def get_references(self, path: str, /) -> collections.Sequence[str] | None:
        """Get the tracked references for a type by its absolute path.

        Parameters
        ----------
        path
            The absolute path of the type to get references for.

            This is matched case-sensitively.

        Returns
        -------
        collections.abc.Sequence[str] | None
            The references to the type if found else `None`.
        """
        if result := self._object_paths_to_uses.get(path):
            return result

        if alias := self._aliases.get(path):
            return self._object_paths_to_uses[alias]


reference_group = tanjun.slash_command_group("references", "Find the references for a type in a library")


@dataclasses.dataclass(eq=False, slots=True)
class _IndexCommand:
    """Search the reference for types and callbacks in a Python library."""

    __weakref__: typing.Any = dataclasses.field(init=False)

    index: ReferenceIndex
    library_repr: str

    async def __call__(
        self,
        ctx: tanjun.abc.Context,
        path: str,
        absolute: bool,
        public: bool,
        component_client: alluka.Injected[yuyo.ComponentClient],
    ) -> None:
        if absolute:
            if not (result := self.index.get_references(path)):
                raise tanjun.CommandError(
                    f"No references found for the absolute path `{path}`", component=buttons.delete_row(ctx)
                )

            full_path = path
            uses = result

        else:
            if not (result := self.index.search(path)):
                raise tanjun.CommandError(f"No references found for `{path}`", component=buttons.delete_row(ctx))

            full_path, uses = result

        iterator = utility.page_iterator(
            utility.chunk(iter(uses), 10),
            lambda entries: "Note: This only searches return types and attributes.\n\n" + "\n".join(entries),
            title=f"{len(uses)} references found for {full_path}",
            cast_embed=lambda e: e.set_footer(text=self.library_repr),
        )
        paginator = utility.make_paginator(iterator, author=None if public else ctx.author, full=True)
        utility.add_file_button(paginator, make_files=lambda: [hikari.Bytes("\n".join(uses), "results.txt")])

        first_response = await paginator.get_next_entry()
        assert first_response
        message = await ctx.respond(**first_response.to_kwargs(), components=paginator.rows, ensure_result=True)
        component_client.register_executor(paginator, message=message)


@dataclasses.dataclass(eq=False, slots=True)
class _IndexAutocomplete:
    __weakref__: typing.Any = dataclasses.field(init=False)

    index: ReferenceIndex

    async def __call__(self, ctx: tanjun.abc.AutocompleteContext, value: str) -> None:
        await ctx.set_choices({entry: entry for entry, _ in zip(self.index.search_paths(value), range(25))})


def _with_index_message_options(command: _MessageCommandT) -> _MessageCommandT:
    return command.set_parser(
        tanjun.ShlexParser()
        .add_argument("path")
        .add_option("absolute", "--absolute", "-a", converters=tanjun.to_bool, default=False, empty_value=True)
        .add_option("public", "--public", "-p", converters=tanjun.to_bool, default=False, empty_value=True)
    )


def _with_index_slash_options(command: _SlashCommandT, index: ReferenceIndex, /) -> _SlashCommandT:
    return (
        command.add_str_option(
            "path", "Path to the type to find references for", autocomplete=_IndexAutocomplete(index)
        )
        .add_bool_option("absolute", "Whether to treat path as an absolute path rather than search path", default=False)
        .add_bool_option(
            "public",
            "Whether other people should be able to interact with the response. Defaults to False",
            default=False,
        )
    )


hikari_index = ReferenceIndex.from_file(_INDEXES_DIR / "hikari_index.json")
hikari_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(hikari_index, f"Hikari v{hikari_index.version}"),
            "hikari",
            "Find the references for types in hikari",
        ),
        hikari_index,
    )
)
hikari_command = _with_index_message_options(tanjun.MessageCommand(hikari_command.callback, "references hikari"))


lightbulb_index = ReferenceIndex.from_file(_INDEXES_DIR / "lightbulb_index.json")
lightbulb_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(lightbulb_index, f"Lightbulb v{lightbulb_index.version}"),
            "lightbulb",
            "Find the references for types in lightbulb",
        ),
        lightbulb_index,
    )
)
lightbulb_command = _with_index_message_options(
    tanjun.MessageCommand(lightbulb_command.callback, "references lightbulb")
)


sake_index = ReferenceIndex.from_file(_INDEXES_DIR / "sake_index.json")
sake_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(sake_index, f"Sake v{sake_index.version}"), "sake", "Find the references for types in Sake"
        ),
        sake_index,
    )
)
sake_command = _with_index_message_options(tanjun.MessageCommand(sake_command.callback, "references sake"))


tanjun_index = ReferenceIndex.from_file(_INDEXES_DIR / "tanjun_index.json")
tanjun_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(tanjun_index, f"Tanjun v{tanjun_index.version}"),
            "tanjun",
            "Find the references for types in Tanjun",
        ),
        tanjun_index,
    )
)
tanjun_command = _with_index_message_options(tanjun.MessageCommand(tanjun_command.callback, "references tanjun"))


yuyo_index = ReferenceIndex.from_file(_INDEXES_DIR / "yuyo_index.json")
yuyo_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(yuyo_index, f"Yuyo v{yuyo_index.version}"),
            "yuyo",
            "Find the references for a Yuyo type in Yuyo",
        ),
        yuyo_index,
    )
)
yuyo_command = _with_index_message_options(tanjun.MessageCommand(yuyo_command.callback, "references yuyo"))


arc_index = ReferenceIndex.from_file(_INDEXES_DIR / "arc_index.json")
arc_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(arc_index, f"Arc v{arc_index.version}"), "arc", "Find the references for a Arc type in Arc"
        ),
        arc_index,
    )
)
arc_command = _with_index_message_options(tanjun.MessageCommand(arc_command.callback, "references arc"))


crescent_index = ReferenceIndex.from_file(_INDEXES_DIR / "crescent_index.json")
crescent_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(crescent_index, f"Crescent v{crescent_index.version}"),
            "crescent",
            "Find the references for a Crescent type in Crescent",
        ),
        crescent_index,
    )
)
crescent_command = _with_index_message_options(tanjun.MessageCommand(crescent_command.callback, "references crescent"))


miru_index = ReferenceIndex.from_file(_INDEXES_DIR / "miru_index.json")
miru_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(miru_index, f"Miru v{miru_index.version}"),
            "miru",
            "Find the references for a Miru type in Miru",
        ),
        miru_index,
    )
)
miru_command = _with_index_message_options(tanjun.MessageCommand(miru_command.callback, "references miru"))


load_reference = tanjun.Component(name="reference").load_from_scope().make_loader()
