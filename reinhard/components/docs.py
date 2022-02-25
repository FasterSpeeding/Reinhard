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
"""Commands used to search Hikari and Tanjun's docs."""
from __future__ import annotations

__all__: list[str] = ["load_docs"]

import abc
import collections.abc as collections
import dataclasses
import datetime
import json
import typing

import alluka
import hikari
import markdownify  # pyright: reportMissingTypeStubs=warning
import tanjun
import yuyo

from .. import utility

docs_group = tanjun.slash_command_group("docs", "Search relevant document sites.")

_T = typing.TypeVar("_T")
_CoroT = typing.Coroutine[typing.Any, typing.Any, _T]
_DocIndexT = typing.TypeVar("_DocIndexT", bound="DocIndex")
_MessageCommandT = typing.TypeVar("_MessageCommandT", bound=tanjun.MessageCommand[typing.Any])
_SlashCommandT = typing.TypeVar("_SlashCommandT", bound=tanjun.SlashCommand[typing.Any])
HIKARI_PAGES = "https://www.hikari-py.dev"
SAKE_PAGES = "https://sake.cursed.solutions"
TANJUN_PAGES = "https://tanjun.cursed.solutions"
YUYO_PAGES = "https://yuyo.cursed.solutions"
SPECIAL_KEYS: frozenset[str] = frozenset(("df", "tf", "docs"))


@dataclasses.dataclass(slots=True)
class DocEntry:
    """Dataclass used to represent a documentation entry."""

    doc: str
    """The entry's doc string."""

    type: str
    """The type of entry this is.

    This will be either "function", "class", "module" or "???".
    """

    func_def: str | None
    """How this function was defined if this is a function.

    This will be either "def", "async def" or `None`.
    """

    fullname: str
    """The entry's fullname."""

    module_name: str
    """Name of the module this entry is in."""

    qualname: str
    """The entry's qualified name."""

    signature: list[str] | None
    """A list of the entry's parameter names if this is a function."""

    bases: str | None
    """The classes a class inherits from."""

    default_value: str | None
    """The value assigned to the initial annotated declaration of a variable."""

    annotation: str | None
    """Annotation of a variable."""

    @classmethod
    def from_entry(cls, data: dict[str, typing.Any], doc: str, /) -> DocEntry:
        return cls(
            doc,
            data["type"],
            data.get("funcdef"),
            data["fullname"],
            data["modulename"],
            # qualname isn't included for modules on 8.3.0 so we can use fullname
            # or modulename as a default here
            data.get("qualname") or data["fullname"],
            data.get("signature"),
            data.get("bases") or None,
            data.get("default_value"),
            data.get("annotation"),
        )


def _collect_pdoc_paths(data: dict[str, typing.Any], /, *, target: str = "") -> collections.Iterator[str]:
    if docs := data.get("docs"):
        if target:
            yield from (key for key in docs.keys() if target in key.lower())

        else:
            yield from docs.keys()

    for key, value in data.items():
        if key not in SPECIAL_KEYS:
            yield from _collect_pdoc_paths(value, target=target)


class DocIndex(abc.ABC):
    """Abstract class of a documentation store index."""

    __slots__ = ("_metadata", "_search_index")

    def __init__(self, data: dict[str, typing.Any], /, *, process_doc: bool = True) -> None:
        self._metadata: dict[str, DocEntry] = {}

        for name, entry in data["documentStore"]["docs"].items():
            if process_doc:
                doc = typing.cast(str, markdownify.markdownify(entry["doc"])).strip("\n").strip()
            else:
                doc = entry["doc"]
            self._metadata[name] = DocEntry.from_entry(entry, doc)

        # Qualname doesn't seem to include modules but fullname does
        self._search_index: dict[str, typing.Any] = data["index"]["fullname"]

    @classmethod
    def from_json(cls: type[_DocIndexT], data: str | bytes, /) -> _DocIndexT:
        """Build this index from a JSON payload."""
        return cls(json.loads(data))

    def get_entry(self, path: str, /) -> DocEntry:
        """Get an entry from the index from an absolute path.

        Parameters
        ----------
        path : str
            The absolute path to the entry.

            This is matched case-sensitively.

        Returns
        -------
        DocEntry
            The entry.

        Raises
        ------
        KeyError
            If the path is not found.
        """
        return self._metadata[path]

    @abc.abstractmethod
    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        """Make a web link to a documentation entry.

        Parameters
        ----------
        base_url : str
            The base URL of the documentation site.

        entry : DocEntry
            The entry to link to.

        Returns
        -------
        str
            The link.
        """

    def search(self, search_path: str, /) -> collections.Iterator[DocEntry]:
        """Search the index for an entry.

        Parameters
        ----------
        search_path : str
            The partial path to search for.

            This is matched case-insensitively.

        Returns
        -------
        collections.abc.Iterator[DocEntry]
            An iterator of the matching entries.
        """
        search_path = search_path.lower()
        if not search_path:
            return

        try:
            _, name = search_path.rsplit(".", 1)[-1].rsplit("_", 1)
        except ValueError:
            name = search_path.rsplit(".", 1)[-1]

        position: dict[str, typing.Any] = self._search_index["root"]
        for char in name:
            if not (new_position := position.get(char)):
                # Sometimes the search path ends a bit pre-maturely.
                if docs := position.get("docs"):
                    # Since this isn't recursive, no de-duplication is necessary.
                    yield from (self._metadata[path] for path in docs.keys() if search_path in path.lower())
                    return

                return

            position = new_position

        # Since this is recursive we need to check for duplicated entries.
        already_yielded = set[str]()
        for path in _collect_pdoc_paths(position, target=search_path):
            if path not in already_yielded:
                already_yielded.add(path)
                yield self._metadata[path]


PLACEHOLDER = "???"


def process_hikari_index(data: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Process Hikari's unique index format to make it compatible with the logic for Tanjun's index.

    Parameters
    ----------
    data : dict[str, typing.Any]
        The index data.

    Returns
    -------
    dict[str, typing.Any]
        The processed index data.
    """
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
            "signature": PLACEHOLDER,
            "bases": [PLACEHOLDER],
        }
        for node in map(str.lower, path.rsplit(".")[-1].split("_")):
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
    """Doc index specialised for Hikari's documentation."""

    __slots__ = ()

    def __init__(self, data: dict[str, typing.Any], /) -> None:
        super().__init__(process_hikari_index(data), process_doc=False)

    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        fragment = ""
        if entry.fullname.removeprefix(entry.module_name):
            fragment = "#" + entry.fullname

        return base_url + "/".join(entry.module_name.split(".")) + fragment


class PdocIndex(DocIndex):
    """Doc index specialised for Pdoc indexes."""

    __slots__ = ()

    def make_link(self, base_url: str, entry: DocEntry, /) -> str:
        fragment = ""
        if in_module := entry.fullname.removeprefix(entry.module_name + "."):
            fragment = "#" + in_module

        return base_url + "/".join(entry.module_name.split(".")) + fragment


def _form_description(metadata: DocEntry, *, desc_splitter: str = "\n") -> str:
    if metadata.doc:
        summary = metadata.doc.split(desc_splitter, 1)[0]
        if desc_splitter != "\n":
            summary += desc_splitter
    else:
        summary = "NONE"

    match metadata.type:
        case "function":
            type_line = "Type: Async function" if metadata.func_def == "async def" else "Type: Sync function"
            return f"{type_line}\n\nSummary:\n```{summary}```\nSignature:\n```py\n{metadata.signature}```"
        case "variable":
            annotation = (metadata.annotation or "NONE").removeprefix(":").lstrip()
            return f"Type: Variable\n\nSummary\n```{summary}```\nAnnotation: `{annotation}`"
        case "class":
            return f"Type: Class\n\nSummary\n```{summary}```\nBases: `({metadata.bases})`"
        case _:
            return f"Type: {metadata.type.capitalize()}\n\nSummary\n```{summary}```"


async def _docs_command(
    ctx: tanjun.abc.Context,
    component_client: yuyo.ComponentClient,
    index: DocIndex,
    base_url: str,
    docs_url: str,
    name: str,
    path: str | None,
    public: bool,
    desc_splitter: str = "\n",
    **kwargs: typing.Any,
) -> None:
    if not path:
        await ctx.respond(base_url, component=utility.delete_row(ctx))
        return

    if kwargs["list"]:
        iterator = utility.embed_iterator(
            utility.chunk((f"[{m.fullname}]({index.make_link(docs_url, m)})" for m in index.search(path)), 10),
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
            make_files=lambda: [hikari.Bytes("\n".join(m.fullname for m in index.search(str(path))), "results.txt")],
        )
        components = executor.builders

    else:
        iterator = (
            (
                hikari.UNDEFINED,
                hikari.Embed(
                    description=_form_description(metadata, desc_splitter=desc_splitter),
                    color=utility.embed_colour(),
                    title=metadata.fullname,
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

        await ctx.set_choices({entry.qualname: entry.qualname for entry, _ in zip(index.search(value), range(25))})

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
            .add_bool_option("list", "Whether this should return alist of links. Defaults to False.", default=False)
        )

    return decorator


def _with_docs_message_options(command: _MessageCommandT, /) -> _MessageCommandT:
    return command.set_parser(
        tanjun.ShlexParser()
        .add_argument("path", default=None)
        .add_option("public", "-p", "--public", converters=tanjun.to_bool, default=False, empty_value=True)
        .add_option("list", "-l", "--list", converters=tanjun.to_bool, default=False, empty_value=True)
    )


hikari_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(HIKARI_PAGES + "/hikari/index.json", HikariIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs hikari")
@docs_group.with_command
@_with_docs_slash_options(hikari_index)
@tanjun.as_slash_command("hikari", "Search Hikari's documentation")
def docs_hikari_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: typing.Annotated[HikariIndex, alluka.inject(callback=hikari_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    """Search Hikari's documentation.

    Arguments
        * path: Optional argument to query Hikari's documentation by.
    """
    return _docs_command(
        ctx, component_client, index, HIKARI_PAGES, HIKARI_PAGES + "/hikari/", "Hikari", desc_splitter=".", **kwargs
    )


sake_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(SAKE_PAGES + "/master/search.json", PdocIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs sake")
@docs_group.with_command
@_with_docs_slash_options(sake_index)
@tanjun.as_slash_command("sake", "Search Sake's documentation")
def sake_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: typing.Annotated[DocIndex, alluka.inject(callback=sake_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    return _docs_command(ctx, component_client, index, SAKE_PAGES, SAKE_PAGES + "/master/", "Sake", **kwargs)


tanjun_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(TANJUN_PAGES + "/master/search.json", PdocIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs tanjun")
@docs_group.with_command
@_with_docs_slash_options(tanjun_index)
@tanjun.as_slash_command("tanjun", "Search Tanjun's documentation")
def tanjun_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: typing.Annotated[DocIndex, alluka.inject(callback=tanjun_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    return _docs_command(ctx, component_client, index, TANJUN_PAGES, TANJUN_PAGES + "/master/", "Tanjun", **kwargs)


yuyo_index = tanjun.dependencies.data.cache_callback(
    utility.FetchedResource(YUYO_PAGES + "/master/search.json", PdocIndex.from_json),
    expire_after=datetime.timedelta(hours=12),
)


@_with_docs_message_options
@tanjun.as_message_command("docs yuyo")
@docs_group.with_command
@_with_docs_slash_options(yuyo_index)
@tanjun.as_slash_command("yuyo", "Search Yuyo's documentation")
def yuyo_docs_command(
    ctx: tanjun.abc.Context,
    component_client: alluka.Injected[yuyo.ComponentClient],
    index: typing.Annotated[DocIndex, alluka.inject(callback=yuyo_index)],
    **kwargs: typing.Any,
) -> _CoroT[None]:
    return _docs_command(ctx, component_client, index, YUYO_PAGES, YUYO_PAGES + "/master/", "Yuyo", **kwargs)


load_docs = tanjun.Component(name="docs").load_from_scope().make_loader()
