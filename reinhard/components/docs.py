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
"""Commands used to search Hikari and Tanjun's docs."""
from __future__ import annotations

__all__: list[str] = ["docs_component"]

import abc
import collections.abc as collections
import dataclasses
import datetime
import json
import typing

import hikari
import markdownify  # pyright: reportMissingTypeStubs=warning
import tanjun
import yuyo

from .. import utility

docs_component = tanjun.Component(name="docs", strict=True)
docs_group = docs_component.with_slash_command(tanjun.slash_command_group("docs", "Search relevant document sites."))


EMPTY_ITER = iter(())
_DocIndexT = typing.TypeVar("_DocIndexT", bound="DocIndex")
_ValueT = typing.TypeVar("_ValueT")
HIKARI_PAGES = "https://hikari-py.github.io/hikari"
TANJUN_PAGES = "https://fasterspeeding.github.io/Tanjun"
SPECIAL_KEYS: frozenset[str] = frozenset(("df", "tf", "docs"))


@dataclasses.dataclass(slots=True)
class DocEntry:
    doc: str
    type: str
    func_def: str | None
    fullname: str
    module_name: str
    qualname: str
    func_def: str | None
    parameters: list[str] | None

    @classmethod
    def from_entry(cls, data: dict[str, typing.Any], doc: str, /) -> DocEntry:
        return cls(
            doc,
            data["type"],
            data.get("funcdef"),
            data["fullname"],
            data["modulename"],
            data["qualname"],
            data.get("parameters"),
        )


def _collect_pdoc_paths(data: dict[str, typing.Any], path_filter: str = "") -> collections.Iterator[str]:
    if docs := data.get("docs"):
        if path_filter:
            yield from (key for key in docs.keys() if key.rsplit(".", 1)[0].endswith(path_filter))

        else:
            yield from docs.keys()

    for key, value in data.items():
        if key not in SPECIAL_KEYS:
            yield from _collect_pdoc_paths(value, path_filter=path_filter)


class DocIndex(abc.ABC):
    __slots__ = ("_metadata", "_search_index")

    def __init__(self, data: dict[str, typing.Any], /, *, process_doc: bool = True) -> None:
        self._metadata: dict[str, DocEntry] = {}

        for name, entry in data["documentStore"]["docs"].items():
            if process_doc:
                doc: str = markdownify.markdownify(entry["doc"]).strip("\n").strip()
            else:
                doc = entry["doc"]
            self._metadata[name] = DocEntry.from_entry(entry, doc)

        # Qualname doesn't seem to include modules but fullname does
        self._search_index: dict[str, typing.Any] = data["index"]["fullname"]

    @classmethod
    def from_json(cls: type[_DocIndexT], data: str | bytes, /) -> _DocIndexT:
        return cls(json.loads(data))

    def get_entry(self, path: str, /) -> DocEntry:
        return self._metadata[path]

    @abc.abstractmethod
    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        ...

    def search(self, full_name: str, /) -> collections.Iterator[DocEntry]:
        full_name = full_name.lower()
        if not full_name:
            return EMPTY_ITER

        try:
            path, name = full_name.rsplit(".", 1)
        except ValueError:
            path = ""
            name = full_name

        position: dict[str, typing.Any] = self._search_index["root"]
        for char in name:
            if not (new_position := position.get(char)):
                # Sometimes the search path ends a bit pre-maturely.
                if docs := position.get("docs"):
                    return (self._metadata[path] for path in docs.keys() if full_name in path.lower())

                return EMPTY_ITER

            position = new_position

        return map(self._metadata.__getitem__, _collect_pdoc_paths(position, path_filter=path))


PLACEHOLDER = "???"


def process_hikari_index(data: dict[str, typing.Any]) -> dict[str, typing.Any]:
    base_urls: dict[str, typing.Any] = {}

    for path in (".".join(url.split("/")) for url in data["urls"]):
        position = base_urls
        for char in path:
            try:
                position = position[char]

            except KeyError:
                position[char] = position = {}

    built_data: dict[str, typing.Any] = {"documentStore": {"docs": {}}, "index": {"fullname": {"root": {}}}}
    docs_store = built_data["documentStore"]["docs"]
    index_store = built_data["index"]["fullname"]["root"]

    for entry in data["index"]:
        fullpath: str = entry["r"]
        path = fullpath.removeprefix("hikari.")
        doc: str = entry["d"]

        position = base_urls
        last_dot = 0
        for index, char in enumerate(path):
            if char == ".":
                last_dot = index

            try:
                position = position[char]

            except KeyError:
                break

        docs_store[fullpath] = {
            "doc": doc,
            "type": PLACEHOLDER,
            "fullname": fullpath,
            "modulename": path[:last_dot],
            "qualname": fullpath.removeprefix(path[:last_dot] + "."),
            "parameters": [PLACEHOLDER],
        }
        for node in map(str.lower, path.split(".")):
            position: dict[str, typing.Any] = index_store
            for char in node:
                try:
                    position = position[char]

                except KeyError:
                    position[char] = position = {}

            try:
                position["docs"][fullpath] = PLACEHOLDER

            except KeyError:
                position["docs"] = {fullpath: PLACEHOLDER}

    return built_data


class HikariIndex(DocIndex):
    __slots__ = ()

    def __init__(self, data: dict[str, typing.Any], /) -> None:
        super().__init__(process_hikari_index(data), process_doc=False)

    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        fragment = ""
        if entry.fullname.removeprefix(entry.module_name):
            fragment = "#" + entry.fullname

        return base_url + "/".join(entry.module_name.split(".")) + fragment


class PdocIndex(DocIndex):
    __slots__ = ()

    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        fragment = ""
        if in_module := entry.fullname.removeprefix(entry.module_name):
            fragment = "#" + in_module.removeprefix(".")

        return base_url + "/".join(entry.module_name.split(".")) + fragment


def _chunk(iterator: collections.Iterator[_ValueT], max: int) -> collections.Iterator[list[_ValueT]]:
    chunk: list[_ValueT] = []
    for entry in iterator:
        chunk.append(entry)
        if len(chunk) == max:
            yield chunk
            chunk = []

    if chunk:
        yield chunk


def _form_description(metadata: DocEntry, *, description_splitter: str = "\n") -> str:
    if metadata.doc:
        summary = metadata.doc.split(description_splitter, 1)[0]
        if description_splitter != "\n":
            summary += description_splitter
    else:
        summary = "NONE"
    if metadata.func_def:
        type_line = "Type: Async function" if metadata.func_def == "async def" else "Type: Sync function"
        params = ", ".join(metadata.parameters or "")
        return f"{type_line}\n\nSummary:\n```md\n{summary}\n```\nParameters:\n`{params}`"

    return f"Type: {metadata.type.capitalize()}\n\nSummary\n```md\n{summary}\n```"


async def _docs_command(
    ctx: tanjun.abc.Context,
    path: str | None,
    component_client: yuyo.ComponentClient,
    index: DocIndex,
    public: bool,
    simple: bool,
    base_url: str,
    docs_url: str,
    name: str,
    description_splitter: str = "\n",
) -> None:
    if not path:
        await ctx.respond(base_url)
        return

    if simple:
        results = map(
            lambda metadata: f"[{metadata.fullname}]({index.make_link(docs_url, metadata)})", index.search(path)
        )
        iterator = (
            (
                hikari.UNDEFINED,
                hikari.Embed(
                    description="\n".join(entries),
                    color=utility.embed_colour(),
                    title=f"{name} Documentation",
                    url=docs_url,
                ).set_footer(text=f"Page {index + 1}"),
            )
            for index, entries in enumerate(_chunk(results, 10))
        )

    else:
        iterator = (
            (
                hikari.UNDEFINED,
                hikari.Embed(
                    description=_form_description(metadata, description_splitter=description_splitter),
                    color=utility.embed_colour(),
                    title=metadata.fullname,
                    url=index.make_link(docs_url, metadata),
                ),
            )
            for metadata in index.search(path)
        )

    paginator = yuyo.ComponentPaginator(iterator, authors=(ctx.author,) if public else ())
    if first_response := await paginator.get_next_entry():
        content, embed = first_response
        message = await ctx.respond(content=content, component=paginator, embed=embed, ensure_result=True)
        component_client.add_executor(message, paginator)
        return

    await ctx.respond("Entry not found")


@docs_group.with_command
@tanjun.with_bool_slash_option("simple", "Whether this should only list links. Defaults to False.", default=False)
@tanjun.with_bool_slash_option(
    "public", "Whether other people should be able to interact with the response. Defaults to False", default=False
)
@tanjun.with_str_slash_option("path", "Optional path to query Hikari's documentation by.", default=None)
@tanjun.as_slash_command("hikari", "Search Hikari's documentation")
async def docs_hikari_command(
    ctx: tanjun.abc.Context,
    path: str | None,
    public: bool,
    simple: bool,
    index: HikariIndex = tanjun.injected(
        callback=tanjun.cache_callback(
            utility.FetchedResource(HIKARI_PAGES + "/hikari/index.json", HikariIndex.from_json),
            expire_after=datetime.timedelta(hours=12),
        )
    ),
    component_client: yuyo.ComponentClient = tanjun.injected(type=yuyo.ComponentClient),
) -> None:
    """Search Hikari's documentation.

    Arguments
        * path: Optional argument to query Hikari's documentation by.
    """
    await _docs_command(
        ctx,
        path,
        component_client,
        index,
        public,
        simple,
        HIKARI_PAGES,
        HIKARI_PAGES + "/hikari/",
        "Hikari",
        description_splitter=".",
    )


@docs_group.with_command
@tanjun.with_bool_slash_option("simple", "Whether this should only list links. Defaults to False.", default=False)
@tanjun.with_bool_slash_option(
    "public", "Whether other people should be able to interact with the response. Defaults to False", default=False
)
@tanjun.with_str_slash_option("path", "Optional path to query Tanjun's documentation by.", default=None)
@tanjun.as_slash_command("tanjun", "Search Tanjun's documentation")
async def tanjun_docs_command(
    ctx: tanjun.abc.Context,
    path: str | None,
    public: bool,
    simple: bool,
    component_client: yuyo.ComponentClient = tanjun.injected(type=yuyo.ComponentClient),
    index: DocIndex = tanjun.injected(
        callback=tanjun.cache_callback(
            utility.FetchedResource(TANJUN_PAGES + "/master/search.json", PdocIndex.from_json),
            expire_after=datetime.timedelta(hours=12),
        )
    ),
) -> None:
    await _docs_command(
        ctx, path, component_client, index, public, simple, TANJUN_PAGES, TANJUN_PAGES + "/master/", "Tanjun"
    )


@tanjun.as_loader
def load_component(cli: tanjun.abc.Client, /) -> None:
    cli.add_component(docs_component.copy())
