# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2022, Faster Speeding
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
"""Commands used to search Tanjun's docs."""
from __future__ import annotations

__all__: list[str] = ["load_docs"]

import datetime
import json
import typing
from collections import abc as collections
from typing import Annotated

import alluka
import hikari
import lunr  # type: ignore
import lunr.exceptions  # type: ignore
import lunr.index  # type: ignore
import tanjun
import yuyo

from .. import utility

docs_group = tanjun.slash_command_group("docs", "Search relevant document sites.")

_T = typing.TypeVar("_T")
_CoroT = collections.Coroutine[typing.Any, typing.Any, _T]
_DocIndexT = typing.TypeVar("_DocIndexT", bound="DocIndex")
_MessageCommandT = typing.TypeVar("_MessageCommandT", bound=tanjun.MessageCommand[typing.Any])
_SlashCommandT = typing.TypeVar("_SlashCommandT", bound=tanjun.SlashCommand[typing.Any])
SAKE_PAGES = "https://sake.cursed.solutions"
TANJUN_PAGES = "https://tanjun.cursed.solutions"
YUYO_PAGES = "https://yuyo.cursed.solutions"


class DocEntry:
    __slots__ = ("location", "text", "title")

    def __init__(self, location: str, entry: dict[str, typing.Any], /) -> None:
        text = entry["text"]
        title = entry["title"]
        assert isinstance(location, str)
        assert isinstance(text, str)
        assert isinstance(title, str)
        self.location = location
        self.text = text
        self.title = title


class DocIndex:
    """Abstract class of a documentation store index."""

    __slots__ = ("_data", "_search_index")

    def __init__(self, data: list[dict[str, str]], /) -> None:
        self._search_index: lunr.index.Index = lunr.lunr("location", ("title", "location"), data)
        self._data: dict[str, DocEntry] = {entry["location"]: DocEntry(entry["location"], entry) for entry in data}

    @classmethod
    def from_json(cls: type[_DocIndexT], data: str | bytes, /) -> _DocIndexT:
        """Build this index from a JSON payload."""
        return cls(json.loads(data)["docs"])

    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        """Make a web link to a documentation entry.

        Parameters
        ----------
        base_url
            The base URL of the documentation site.
        entry
            The entry to link to.

        Returns
        -------
        str
            The link.
        """
        return f"{base_url}/{entry.location}"

    def search(self, search_path: str, /) -> collections.Iterator[DocEntry]:
        """Search the index for an entry.

        Parameters
        ----------
        search_path
            The partial path to search for.

            This is matched case-insensitively.

        Returns
        -------
        collections.abc.Iterator[DocEntry]
            An iterator of the matching entries.
        """
        try:
            results: list[dict[str, str]] = self._search_index.search(search_path)
        except lunr.exceptions.QueryParseError as exc:
            raise tanjun.CommandError(f"Invalid query: `{exc.args[0]}`")
        return (self._data[entry["ref"]] for entry in results)


async def _docs_command(
    ctx: tanjun.abc.Context,
    component_client: yuyo.ComponentClient,
    index: DocIndex,
    docs_url: str,
    name: str,
    path: str | None,
    public: bool,
    desc_splitter: str = "\n",
    **kwargs: typing.Any,
) -> None:
    if not path:
        await ctx.respond(docs_url, component=utility.delete_row(ctx))
        return

    if kwargs["list"]:
        iterator = utility.embed_iterator(
            utility.chunk((f"[{m.title}]({index.make_link(docs_url, m)})" for m in index.search(path)), 10),
            lambda entries: "\n".join(entries),
            title=f"{name} Documentation",
            url=docs_url,
        )
        paginator = yuyo.ComponentPaginator(
            iterator,
            authors=(ctx.author,) if not public else (),
            triggers=(
                yuyo.pagination.LEFT_DOUBLE_TRIANGLE,
                yuyo.pagination.LEFT_TRIANGLE,
                yuyo.pagination.STOP_SQUARE,
                yuyo.pagination.RIGHT_TRIANGLE,
                yuyo.pagination.RIGHT_DOUBLE_TRIANGLE,
            ),
            timeout=datetime.timedelta(days=99999),  # TODO: switch to passing None here
        )
        executor = utility.paginator_with_to_file(
            ctx,
            paginator,
            make_files=lambda: [hikari.Bytes("\n".join(m.title for m in index.search(str(path))), "results.txt")],
        )
        components = executor.builders

    else:
        iterator = (
            (
                hikari.UNDEFINED,
                hikari.Embed(
                    description=metadata.text[:87] + "..." if len(metadata.text) > 90 else metadata.text,
                    color=utility.embed_colour(),
                    title=metadata.title,
                    url=index.make_link(docs_url, metadata),
                ),
            )
            for metadata in index.search(path)
        )
        executor = paginator = yuyo.ComponentPaginator(
            iterator,
            authors=(ctx.author,) if not public else (),
            triggers=(
                yuyo.pagination.LEFT_DOUBLE_TRIANGLE,
                yuyo.pagination.LEFT_TRIANGLE,
                yuyo.pagination.STOP_SQUARE,
                yuyo.pagination.RIGHT_TRIANGLE,
                yuyo.pagination.RIGHT_DOUBLE_TRIANGLE,
            ),
        )
        components = executor.builder()

    if first_response := await paginator.get_next_entry():
        content, embed = first_response
        message = await ctx.respond(content=content, components=components, embed=embed, ensure_result=True)
        component_client.set_executor(message, executor)
        return

    await ctx.respond("Entry not found", component=utility.delete_row(ctx))


def make_autocomplete(get_index: collections.Callable[..., _CoroT[_DocIndexT]]) -> tanjun.abc.AutocompleteCallbackSig:
    async def _autocomplete(
        ctx: tanjun.abc.AutocompleteContext,
        value: str,
        # Annotated can't be used here cause forward annotations
        index: _DocIndexT = alluka.inject(callback=get_index),
    ) -> None:
        """Autocomplete strategy."""
        if not value:
            return

        try:
            await ctx.set_choices({entry.title: entry.location for entry, _ in zip(index.search(value), range(25))})
        except tanjun.CommandError:
            await ctx.set_choices()

    return _autocomplete


def _with_docs_slash_options(
    get_index: collections.Callable[..., _CoroT[_DocIndexT]], /
) -> collections.Callable[[_SlashCommandT], _SlashCommandT]:
    def decorator(command: _SlashCommandT, /) -> _SlashCommandT:
        return (
            command.add_str_option(
                "path",
                "Optional path to query the documentation by.",
                default=None,
                autocomplete=make_autocomplete(get_index),
            )
            .add_bool_option(
                "public",
                "Whether other people should be able to interact with the response. Defaults to False",
                default=False,
            )
            .add_bool_option("list", "Whether this should return a list of links. Defaults to False.", default=False)
        )

    return decorator


def _with_docs_message_options(command: _MessageCommandT, /) -> _MessageCommandT:
    return command.set_parser(
        tanjun.ShlexParser()
        .add_argument("path", default=None)
        .add_option("public", "-p", "--public", converters=tanjun.to_bool, default=False, empty_value=True)
        .add_option("list", "-l", "--list", converters=tanjun.to_bool, default=False, empty_value=True)
    )


sake_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(SAKE_PAGES + "/search/search_index.json", DocIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs sake")
@_with_docs_slash_options(sake_index)
@docs_group.as_sub_command("sake", "Search Sake's documentation")
def sake_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: Annotated[DocIndex, alluka.inject(callback=sake_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    return _docs_command(ctx, component_client, index, SAKE_PAGES, "Sake", **kwargs)


tanjun_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(TANJUN_PAGES + "/search/search_index.json", DocIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs tanjun")
@_with_docs_slash_options(tanjun_index)
@docs_group.as_sub_command("tanjun", "Search Tanjun's documentation")
def tanjun_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: Annotated[DocIndex, alluka.inject(callback=tanjun_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    return _docs_command(ctx, component_client, index, TANJUN_PAGES, "Tanjun", **kwargs)


yuyo_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(YUYO_PAGES + "/search/search_index.json", DocIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs yuyo")
@_with_docs_slash_options(yuyo_index)
@docs_group.as_sub_command("yuyo", "Search Yuyo's documentation")
def yuyo_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: Annotated[DocIndex, alluka.inject(callback=yuyo_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    return _docs_command(ctx, component_client, index, YUYO_PAGES, "Yuyo", **kwargs)


load_docs = tanjun.Component(name="docs").load_from_scope().make_loader()
