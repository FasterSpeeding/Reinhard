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
"""Commands used to search Tanjun's docs."""
from __future__ import annotations

__all__: list[str] = ["load_docs"]

import abc
import datetime
import hashlib
import json
import typing
from collections import abc as collections
from typing import Annotated

import aiohttp
import alluka
import hikari
import lunr  # type: ignore
import lunr.exceptions  # type: ignore
import lunr.index  # type: ignore
import markdownify  # pyright: ignore[reportMissingTypeStubs]
import tanjun
import typing_extensions
import yuyo
from tanchan import doc_parse
from tanchan.components import buttons
from tanjun.annotations import Bool
from tanjun.annotations import Flag
from tanjun.annotations import Name
from tanjun.annotations import Str

from .. import utility

if typing.TYPE_CHECKING:
    from typing_extensions import Self

docs_group = doc_parse.slash_command_group("docs", "Search relevant document sites.")

_T = typing.TypeVar("_T")
_CoroT = collections.Coroutine[typing.Any, typing.Any, _T]
_DocIndexT = typing.TypeVar("_DocIndexT", bound="DocIndex")


def hash_path(value: str, /) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class DocEntry:
    __slots__ = ("hashed_location", "text", "title", "url")

    def __init__(self, base_url: str, location: str, entry: dict[str, typing.Any], /) -> None:
        text: typing.Any = entry["text"]
        title: typing.Any = entry["title"]
        assert isinstance(location, str)
        assert isinstance(text, str)
        assert isinstance(title, str)
        text = markdownify.markdownify(text)  # pyright: ignore[reportUnknownMemberType]
        title = markdownify.markdownify(title, escape_underscores=False)  # pyright: ignore[reportUnknownMemberType]
        assert isinstance(text, str)
        assert isinstance(title, str)

        split_text = text.split("\n", 10)
        text = "\n".join(split_text[:10]).rstrip()
        if len(text) >= 500:
            text = text[:497] + "..."

        elif len(split_text) == 11:
            text = text + "\n..."

        self.hashed_location = hash_path(location)
        self.text = text
        self.title = title
        self.url = f"{base_url}/{location}"

    def to_embed(self) -> hikari.Embed:
        return hikari.Embed(description=self.text, color=utility.embed_colour(), title=self.title, url=self.url)


class DocIndex(abc.ABC):
    """Abstract class of a documentation store index."""

    __slots__ = ("_autocomplete_refs", "_data", "_search_index")

    def __init__(self, data: list[dict[str, str]], /) -> None:
        # Since the top level dir dupes other places in my projects this can be skipped to improve performance.
        data = [entry for entry in data if not entry["location"].startswith("reference/#")]
        self._data: dict[str, DocEntry] = {
            entry["location"]: DocEntry(self.docs_url(), entry["location"], entry) for entry in data
        }
        self._autocomplete_refs: dict[str, DocEntry] = {entry.hashed_location: entry for entry in self._data.values()}
        self._search_index: lunr.index.Index = lunr.lunr(  # pyright: ignore[reportUnknownMemberType]
            "location", ("title", "location"), data
        )

    @classmethod
    @abc.abstractmethod
    def docs_url(cls) -> str: ...

    @classmethod
    def fetch_url(cls) -> str:
        return f"{cls.docs_url()}/search/search_index.json"

    @classmethod
    @abc.abstractmethod
    def name(cls) -> str: ...

    @classmethod
    def from_json(cls, data: str | bytes, /) -> Self:
        """Build this index from a JSON payload."""
        return cls(json.loads(data)["docs"])

    def get_autocomplete_result(self, path: str, /) -> DocEntry | None:
        """Try to get the autocomplete result for a "path" option.

        Parameters
        ----------
        path
            The path to look for an autocomplete for.

            Autocomplete will provide a special cased hashed ID  for the path
            value.

        Returns
        -------
        DocEntry
            The found doc entry if `path` is a valid special cased ID.
        """
        return self._autocomplete_refs.get(path)

    def search(
        self, ctx: tanjun.abc.Context | tanjun.abc.AutocompleteContext, search_path: str, /
    ) -> collections.Iterator[DocEntry]:
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
            reason: str = exc.args[0]
            raise tanjun.CommandError(f"Invalid query: `{reason}`", component=buttons.delete_row(ctx)) from None

        return (self._data[entry["ref"]] for entry in results)


async def _docs_command(
    ctx: tanjun.abc.Context,
    component_client: yuyo.ComponentClient,
    index: DocIndex,
    path: str | None = None,
    public: bool = False,
    return_list: bool = False,
) -> None:
    if not path:
        await ctx.respond(index.docs_url(), component=buttons.delete_row(ctx))
        return

    if autocomplete_result := index.get_autocomplete_result(path):
        await ctx.respond(embed=autocomplete_result.to_embed())
        return

    if return_list:
        iterator = utility.page_iterator(
            utility.chunk((f"[{m.title}]({m.url})" for m in index.search(ctx, path)), 10),
            lambda entries: "\n".join(entries),
            title=f"{index.name()} Documentation",
            url=index.docs_url(),
        )
        paginator = utility.make_paginator(iterator, author=None if public else ctx.author, full=True)
        utility.add_file_button(
            paginator,
            make_files=lambda: [hikari.Bytes("\n".join(m.title for m in index.search(ctx, str(path))), "results.txt")],
        )

    else:
        iterator = (yuyo.Page(metadata.to_embed()) for metadata in index.search(ctx, path))
        paginator = utility.make_paginator(iterator, author=None if public else ctx.author, full=True)

    if first_response := await paginator.get_next_entry():
        message = await ctx.respond(components=paginator.rows, **first_response.to_kwargs(), ensure_result=True)
        component_client.register_executor(paginator, message=message)
        return

    await ctx.respond("Entry not found", component=buttons.delete_row(ctx))


def make_autocomplete(index_type: type[DocIndex]) -> tanjun.abc.AutocompleteSig[str]:
    async def _autocomplete(
        ctx: tanjun.abc.AutocompleteContext,
        value: str,
        # Annotated can't be used here cause forward annotations
        index: utility.Refreshed[DocIndex] = alluka.inject(type=utility.Refreshed[index_type]),
    ) -> None:
        """Autocomplete strategy."""
        if not value:
            await ctx.set_choices()
            return

        try:
            # A hash of the location is used as the raw partial paths can easily get over 100 characters
            # (the value length limit).
            await ctx.set_choices(
                {
                    entry.title: entry.hashed_location
                    for entry, _ in zip(index.get_value().search(ctx, value), range(25))
                }
            )
        except tanjun.CommandError:
            await ctx.set_choices()

    return _autocomplete


def make_lifetimes(index_type: type[_DocIndexT], /) -> tanjun.schedules.AbstractSchedule:
    async def fetch(session: alluka.Injected[aiohttp.ClientSession]) -> _DocIndexT:
        data = await utility.fetch_resource(session, index_type.fetch_url())
        return index_type.from_json(data)

    # Annotated can't be used here for interval cause forward annotations
    @tanjun.as_interval(datetime.timedelta(hours=6))
    async def interval(
        *,
        index: utility.Refreshed[_DocIndexT] | None = alluka.inject(type=utility.Refreshed[index_type] | None),
        client: alluka.Injected[alluka.abc.Client],
        session: alluka.Injected[aiohttp.ClientSession],
    ) -> None:
        if index is None:
            data = await fetch(session)
            client.set_type_dependency(utility.Refreshed[index_type], utility.Refreshed(fetch, data))

        else:
            await index.refresh(client)

    return interval.set_start_callback(interval.callback)


class _DocsOptions(typing.TypedDict, total=False):
    """Reused options for doc commands.

    Parameters
    ----------
    path
        Optional path to query the documentation by.
    public
        Whether other people should be able to itneract with the response. Defaults to False.
    return_list
        Whether this should return a list of links. Defaults to False.
    """

    path: Str
    public: Annotated[Bool, Flag(aliases=["-p"], empty_value=True)]
    return_list: Annotated[Bool, Name("list"), Flag(aliases=["-l"], empty_value=True)]


class HikariIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Hikari"

    @classmethod
    def docs_url(cls) -> str:
        return "https://docs.hikari-py.dev/en/latest"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("hikari")
@tanjun.as_message_command("docs hikari")
def hikari_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[HikariIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Sake's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


hikari_docs_command.set_str_autocomplete("path", make_autocomplete(HikariIndex))
hikari_interval = make_lifetimes(HikariIndex)


class SakeIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Sake"

    @classmethod
    def docs_url(cls) -> str:
        return "https://sake.cursed.solutions"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("sake")
@tanjun.as_message_command("docs sake")
def sake_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[SakeIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Sake's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


sake_docs_command.set_str_autocomplete("path", make_autocomplete(SakeIndex))
sake_interval = make_lifetimes(SakeIndex)


class TanjunIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Tanjun"

    @classmethod
    def docs_url(cls) -> str:
        return "https://tanjun.cursed.solutions"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("tanjun")
@tanjun.as_message_command("docs tanjun")
def tanjun_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[TanjunIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Tanjun's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


tanjun_docs_command.set_str_autocomplete("path", make_autocomplete(TanjunIndex))
tanjun_interval = make_lifetimes(TanjunIndex)


class YuyoIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Yuyo"

    @classmethod
    def docs_url(cls) -> str:
        return "https://yuyo.cursed.solutions"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("yuyo")
@tanjun.as_message_command("docs yuyo")
def yuyo_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[YuyoIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Yuyo's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


yuyo_docs_command.set_str_autocomplete("path", make_autocomplete(YuyoIndex))
yuyo_interval = make_lifetimes(YuyoIndex)


class ArcIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Arc"

    @classmethod
    def docs_url(cls) -> str:
        return "https://arc.hypergonial.com"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("arc")
@tanjun.as_message_command("docs arc")
def arc_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[ArcIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Arc's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


arc_docs_command.set_str_autocomplete("path", make_autocomplete(ArcIndex))
arc_interval = make_lifetimes(ArcIndex)


class CrescentIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Crescent"

    @classmethod
    def docs_url(cls) -> str:
        return "https://hikari-crescent.github.io/hikari-crescent"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("crescent")
@tanjun.as_message_command("docs crescent")
def crescent_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[CrescentIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Crescent's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


crescent_docs_command.set_str_autocomplete("path", make_autocomplete(CrescentIndex))
crescent_interval = make_lifetimes(CrescentIndex)


class MiruIndex(DocIndex):
    __slots__ = ()

    @classmethod
    def name(cls) -> str:
        return "Miru"

    @classmethod
    def docs_url(cls) -> str:
        return "https://miru.hypergonial.com"


@doc_parse.with_annotated_args(follow_wrapped=True)
@docs_group.as_sub_command("miru")
@tanjun.as_message_command("docs miru")
def miru_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: alluka.Injected[utility.Refreshed[MiruIndex]],
    **kwargs: typing_extensions.Unpack[_DocsOptions],
) -> _CoroT[None]:
    """Search Miru's documentation."""
    return _docs_command(ctx, component_client, index.get_value(), **kwargs)


miru_docs_command.set_str_autocomplete("path", make_autocomplete(MiruIndex))
miru_interval = make_lifetimes(MiruIndex)


load_docs = tanjun.Component(name="docs").load_from_scope().make_loader()
