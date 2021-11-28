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
"""Commands used to find the references for a type in Hikari and Tanjun."""
from __future__ import annotations

__slots__: list[str] = ["reference_loader"]

import datetime
import inspect
import logging
import re
import sys
import types
import typing
from collections import abc as collections

import hikari
import hikari.events
import hikari.interactions
import tanjun
import yuyo

from .. import utility

_ReferenceIndexT = typing.TypeVar("_ReferenceIndexT", bound="ReferenceIndex")
_SlashCommandT = typing.TypeVar("_SlashCommandT", bound=tanjun.SlashCommand)
_LOGGER = logging.getLogger("hikari.reinhard.reference_index")


def _is_public(key: str) -> bool:
    return not key.startswith("_")


def _is_public_key(entry: tuple[str, typing.Any]) -> bool:
    return _is_public(entry[0])


_GENERIC_CAPTURE_PATTERN = re.compile(r"([\w\.]+)\[(.+)\]$", flags=re.ASCII)
_NAME_PATTERN = re.compile(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", flags=re.ASCII)
_IMPORT_CAPTURE_PATTERN = re.compile(
    r"\s*import ([\w\.]+)(?: as (\w+))?|\s*from ([\w\.]+) import ([\w\.]+)(?: as (\w+))?", flags=re.ASCII
)
_RELATIVE_IMPORT_DOT_PATTERN = re.compile(r"^(\.*)")
_BUILTIN_TYPES = set(filter(_is_public, __builtins__.keys()))
_END_KEY = "_link"


def _combine_imports(part_1: str, part_2: str) -> str:
    # If this is a relative import then adding a dot in would break it.
    if part_1.startswith("."):
        return f"{part_1}{part_2}"

    return f"{part_1}.{part_2}"


def _process_relative_import(import_link: str, current_module: str) -> str:
    dots = _RELATIVE_IMPORT_DOT_PATTERN.match(import_link)
    assert dots, "We already know this starts with dots so this'll always pass"
    dot_count = len(dots.group())
    assert current_module.count(".") > (dot_count - 2), "This import is invalid, how'd you get this far?"
    return current_module.rsplit(".", dot_count)[0] + import_link[dot_count - 1 :]


class ReferenceIndex:
    """Index used for tracking references to types in specified modules.

    Other Parameters
    ----------------
    track_3rd_party : bool
        Whether to track references to types in 3rd party (non-indexed) modules.
    track_builtins : bool
        Whether to track references to types in the builtin module.
    """

    __slots__ = (
        "_is_tracking_3rd_party",
        "_is_tracking_builtins",
        "_indexed_modules",
        "_module_imports",
        "_object_paths_to_uses",
        "_object_search_tree",
        "_top_level_modules",
    )

    def __init__(self, *, track_builtins: bool = False, track_3rd_party: bool = False) -> None:
        self._is_tracking_3rd_party = track_3rd_party
        self._is_tracking_builtins = track_builtins
        self._indexed_modules: dict[str, types.ModuleType] = {}
        self._module_imports: dict[str, dict[str, str]] = {}
        self._object_paths_to_uses: dict[str, list[str]] = {}
        self._object_search_tree: dict[str, typing.Any] = {}
        self._top_level_modules: set[str] = set()

    def _add_use(self, path: str, use: str) -> None:
        if uses := self._object_paths_to_uses.get(path):
            uses.append(use)

        else:
            self._object_paths_to_uses[path] = [use]

    def _get_or_parse_module_imports(self, module_name: str) -> dict[str, str]:
        imports: typing.Optional[dict[str, str]]
        if (imports := self._module_imports.get(module_name)) is not None:
            return imports

        imports = {}
        module_path = sys.modules[module_name].__file__
        assert (
            module_path is not None
        ), "These modules were all imported using the normal import system so this should never be None"
        with open(module_path, "r") as file:
            for match in filter(None, map(_IMPORT_CAPTURE_PATTERN.match, file.readlines())):
                groups = match.groups()
                if groups[1]:  # `import {0} as {1}`
                    imported_name = groups[1]
                    imported_from = groups[0]

                elif groups[0]:  # `import {0}`
                    imported_name = imported_from = groups[0]

                elif groups[4]:  # `from {2} import {3} as {4}`
                    imported_name = groups[4]
                    imported_from = _combine_imports(groups[2], groups[3])

                elif groups[3]:  # `from {2} import {3}`
                    imported_name = groups[3]
                    imported_from = _combine_imports(groups[2], imported_name)

                else:  # Case not defined by the regex
                    raise RuntimeError("This shouldn't ever happen")

                if imported_from.startswith("."):
                    imported_from = _process_relative_import(imported_from, module_name)

                if self._is_tracking_3rd_party or imported_from.split(".", 1)[0] in self._top_level_modules:
                    imports[imported_name] = imported_from

        self._module_imports[module_name] = imports
        return imports

    def _capture_generic(self, module_name: str, path: str, annotation: str) -> bool:
        if match := _GENERIC_CAPTURE_PATTERN.fullmatch(annotation):
            outer, inner = match.groups()
            self._handle_annotation(module_name, path, outer)
            last_index = 0
            bracket_depth = 0
            char = ""

            for index, char in enumerate(inner):
                if char == "[":
                    bracket_depth += 1
                elif char == "]":
                    bracket_depth -= 1

                elif char == "," and bracket_depth == 0:
                    value = inner[last_index:index].strip()
                    if value.startswith("[") and value.endswith("]"):
                        value = value.removeprefix("[").removesuffix("]")

                    self._handle_annotation(module_name, path, value)
                    last_index = index + 1

            if char != "":
                self._handle_annotation(module_name, path, inner[last_index:].strip())

            return True

        return False

    def _handle_annotation(self, module_name: str, path: str, annotation: typing.Union[type[typing.Any], str]) -> None:
        if not isinstance(annotation, str):
            return

        annotation = annotation.strip()
        module_imports = self._get_or_parse_module_imports(module_name)
        if (
            self._capture_generic(module_name, path, annotation)
            or not _NAME_PATTERN.fullmatch(annotation)
            or not _is_public(annotation)
        ):
            return

        if annotation in _BUILTIN_TYPES:
            if self._is_tracking_builtins:
                self._add_use(f"builtins.{annotation}", path)

            return

        if "." in annotation:
            for name, import_path in module_imports.items():
                without_key = annotation.removeprefix(name)
                if without_key[0] == ".":
                    self._add_use(import_path + without_key, path)
                    return

            # If we hit this statement then this indicates that the annotation
            # refers to a 3rd party type and that we aren't tracking 3rd party
            # types so this can be safely ignored.
            else:
                _LOGGER.debug("Ignoring %r annotation from out-of-scope library at %r", annotation, path)

        else:
            # If we got this far then it is located in the current module.
            self._add_use(f"{module_name}.{annotation}", path)

    def _recurse_object(
        self, path: str, obj: typing.Union[types.MethodType, types.FunctionType, type[typing.Any]]
    ) -> bool:
        if isinstance(obj, (types.MethodType, types.FunctionType, classmethod)):
            if return_type := obj.__annotations__.get("return"):
                self._handle_annotation(obj.__module__, f"{path}()", return_type)
                return True

        elif isinstance(obj, property):
            if return_type := obj.fget.__annotations__.get("return"):
                self._handle_annotation(obj.fget.__module__, path, return_type)
                return True

        elif isinstance(obj, type):
            # Used to track attributes which'd been overwritten through inheritance.
            found_attributes: set[str] = set()

            for name, attribute in filter(_is_public_key, inspect.getmembers(obj)):
                if self._recurse_object(f"{path}.{name}", attribute):
                    found_attributes.add(attribute)

            try:
                # If we ever find a class like ABCMeta, this will error.
                mro = obj.mro()
            except TypeError:
                return True

            # We have to traverse the class's mro to find annotations since __annotations__
            # doesn't include inherited attributes in-order to make resolving said annotations
            # possible (as you need to know the scope they were defined in).
            for mro_cls in mro:  # obj.mro() includes the class itself at the start.
                try:
                    # Some classes like object just don't have annotations cause thx python.
                    annotations = mro_cls.__annotations__
                except AttributeError:
                    continue

                for name, annotation in filter(_is_public_key, annotations.items()):
                    if name not in found_attributes:
                        self._handle_annotation(mro_cls.__module__, f"{path}.{name}", annotation)
                        found_attributes.add(name)

            return True

        return False

    def build_search_tree(self: _ReferenceIndexT) -> _ReferenceIndexT:
        """Build the internal search tree to enable searching for types.

        .. warning::
            If this isn't called then `search` and `get_references` will always return
            `None`.
        """
        for full_path in self._object_paths_to_uses.keys():
            _, name = full_path.rsplit(".", 1)

            position = self._object_search_tree
            for char in name.lower():
                if char not in position:
                    position[char] = position = {}

                else:
                    position = position[char]

            if links := position.get(_END_KEY):
                if full_path not in links:
                    links.append(full_path)

            else:
                links = position[_END_KEY] = [full_path]

        return self

    def index_module(self: _ReferenceIndexT, module: types.ModuleType, /) -> _ReferenceIndexT:
        """Add a module to the internal index of in-scope modules.

        Any types declared in these modules will have their uses tracked.

        Parameters
        ----------
        module : types.ModuleType
            The module to index.
        """
        self._indexed_modules[module.__name__] = module
        self._top_level_modules.add(module.__name__.split(".", 1)[0])
        return self

    def _walk_sub_modules(
        self: _ReferenceIndexT,
        start_point: str,
        found_modules: set[str],
        callback: collections.Callable[[types.ModuleType], typing.Any],
        module: types.ModuleType,
        /,
        *,
        check: typing.Optional[collections.Callable[[types.ModuleType], bool]],
        children_only: bool,
        recursive: bool,
    ) -> _ReferenceIndexT:
        for _, sub_module in filter(_is_public_key, inspect.getmembers(module)):
            if isinstance(sub_module, types.ModuleType) and sub_module.__name__ not in found_modules:
                if children_only and not sub_module.__name__.startswith(start_point):
                    continue

                found_modules.add(sub_module.__name__)
                if check and not check(sub_module):
                    continue

                callback(sub_module)
                if recursive:
                    self._walk_sub_modules(
                        start_point,
                        found_modules,
                        callback,
                        sub_module,
                        check=check,
                        children_only=children_only,
                        recursive=True,
                    )

        return self

    def index_sub_modules(
        self: _ReferenceIndexT,
        module: types.ModuleType,
        /,
        *,
        check: typing.Optional[collections.Callable[[types.ModuleType], bool]] = None,
        children_only: bool = True,
        recursive: bool = True,
    ) -> _ReferenceIndexT:
        """Add a module's sub-modules to the internal index of in-scope modules.

        Any types declared in these modules will have their uses tracked.

        Parameters
        ----------
        module : types.ModuleType
            The module to index the sub-modules in.

        Other Parameters
        ----------------
        check : typing.Optional[collections.Callable[[types.ModuleType], bool]]
            If provided, a callback which will decide which sub-modules should be indexed.
            If `None` then all sub-modules will be indexed.
        children_only : bool
            Whether found modules which aren't direct children of the passed
            module should be ignored.

            Defaults to `True`.
        recursive : bool
            If `True` then this will recursively index sub-modules instead of just
            indexing modules directly on the provided module.

            Defaults to `True`.
        """
        return self._walk_sub_modules(
            module.__name__,
            set(),
            self.index_module,
            module,
            check=check,
            children_only=children_only,
            recursive=recursive,
        )

    def scan_indexed_modules(self: _ReferenceIndexT) -> _ReferenceIndexT:
        """Scan the indexed modules for type references."""
        for module in self._indexed_modules.values():
            self.scan_module(module)

        return self

    def scan_module(self: _ReferenceIndexT, module: types.ModuleType, /) -> _ReferenceIndexT:
        """Scan a module for type references.

        Parameters
        ----------
        module : types.ModuleType
            The module to scan for type references.
        """
        module_members = dict[str, typing.Any](filter(_is_public_key, inspect.getmembers(module)))
        for name, obj in module_members.items():
            if isinstance(obj, (types.MethodType, types.FunctionType, type)):
                self._recurse_object(f"{module.__name__}.{name}", obj)

        return self

    def scan_sub_modules(
        self: _ReferenceIndexT,
        module: types.ModuleType,
        /,
        *,
        check: typing.Optional[collections.Callable[[types.ModuleType], bool]] = None,
        children_only: bool = True,
        recursive: bool = True,
    ) -> _ReferenceIndexT:
        """Scan sub-modules for type references.

        Parameters
        ----------
        module : types.ModuleType
            The module to scan sub-modules in.

        Other Parameters
        ----------------
        check : typing.Optional[collections.Callable[[types.ModuleType], bool]]
            If provided, a callback which will decide which sub-modules should be scanned.
            If `None` then all sub-modules will be scanned.
        children_only : bool
            Whether found modules which aren't direct children of the passed
            module should be ignored.

            Defaults to `True`.
        recursive : bool
            If `True` then this will recursively scan sub-modules instead of just
            scanning modules directly on the provided module.

            Defaults to `True`.
        """
        return self._walk_sub_modules(
            module.__name__,
            set(),
            self.index_module,
            module,
            check=check,
            children_only=children_only,
            recursive=recursive,
        )

    def search(self, path: str, /) -> typing.Optional[tuple[str, collections.Sequence[str]]]:
        """Search for a type to get its references.

        Parameters
        ----------
        path : str
            Partial path of the type to search for.

            This will be matched case-insensitively.

        Returns
        -------
        typing.Optional[tuple[str, collections.Sequence[str]]]
            The type's full path and a list of references to it.

            If the type was not found then `None` is returned.
        """
        split = path.rsplit(".", 1)
        if len(split) > 1:
            name = split[1]

        else:
            name = path

        position = self._object_search_tree
        for char in name.lower():
            if new_position := position.get(char):
                position = new_position
                continue

            return None

        if end := position.get(_END_KEY):
            key: str
            for key in end:
                if key.endswith(path):
                    return (key, self._object_paths_to_uses[key])

    def get_references(self, path: str, /) -> typing.Optional[collections.Sequence[str]]:
        """Get the tracked references for a type by its absolute path.

        Parameters
        ----------
        path : str
            The absolute path of the type to get references for.

            This is matched case-sensitively.

        Returns
        -------
        typing.Optional[collections.Sequence[str]]
            The references to the type if found else `None`.
        """
        return self._object_paths_to_uses.get(path)


hikari_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_sub_modules(hikari)
    .scan_indexed_modules()
    .build_search_tree()
)
tanjun_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_sub_modules(tanjun)
    .scan_indexed_modules()
    .build_search_tree()
)
yuyo_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_sub_modules(yuyo)
    .scan_indexed_modules()
    .build_search_tree()
)
reference_group = tanjun.slash_command_group("find_references", "Find the references for a type in a library")


def _with_index_command_options(command: _SlashCommandT, /) -> _SlashCommandT:
    return (
        command.add_str_option("path", "Path to the type to find references for")
        .add_bool_option("absolute", "Whether to treat path as an absolute path rather than search path", default=False)
        .add_bool_option(
            "public",
            "Whether other people should be able to interact with the response. Defaults to False",
            default=False,
        )
    )


async def _index_command(
    ctx: tanjun.abc.Context,
    component_client: yuyo.ComponentClient,
    index: ReferenceIndex,
    path: str,
    absolute: bool,
    public: bool,
):
    if absolute:
        if not (result := index.get_references(path)):
            raise tanjun.CommandError(f"No references found for the absolute path `{path}`")

        full_path = path
        uses = result

    else:
        if not (result := index.search(path)):
            raise tanjun.CommandError(f"No references found for `{path}`")

        full_path, uses = result

    iterator = utility.embed_iterator(
        utility.chunk(iter(uses), 10),
        lambda entries: "Note: This only searches return types and attributes.\n\n" + "\n".join(entries),
        title=f"{len(uses)} references found for {full_path}",
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

    executor = (
        yuyo.MultiComponentExecutor()  # TODO: add authors here
        .add_executor(paginator)
        .add_builder(paginator)
        .add_action_row()
        .add_button(
            hikari.ButtonStyle.SECONDARY,
            utility.FileCallback(
                ctx, make_files=lambda: [hikari.Bytes("\n".join(uses), "results.txt")], post_components=[paginator]
            ),
        )
        .set_emoji(utility.FILE_EMOJI)
        .add_to_container()
        .add_to_parent()
    )

    first_response = await paginator.get_next_entry()
    assert first_response
    content, embed = first_response
    message = await ctx.respond(content=content, components=executor.builders, embed=embed, ensure_result=True)
    component_client.set_executor(message, executor)


@reference_group.with_command
@_with_index_command_options
@tanjun.as_slash_command("hikari", "Find the references for a hikari type in hikari")
def hikari_command(
    ctx: tanjun.abc.Context,
    path: str,
    absolute: bool,
    public: bool,
    component_client: yuyo.ComponentClient = tanjun.inject(type=yuyo.ComponentClient),
) -> collections.Awaitable[None]:
    return _index_command(ctx, component_client, hikari_index, path, absolute, public)


@reference_group.with_command
@_with_index_command_options
@tanjun.as_slash_command("tanjun", "Find the references for a Tanjun type in Tanjun")
def tanjun_command(
    ctx: tanjun.abc.Context,
    path: str,
    absolute: bool,
    public: bool,
    component_client: yuyo.ComponentClient = tanjun.inject(type=yuyo.ComponentClient),
) -> collections.Awaitable[None]:
    return _index_command(ctx, component_client, tanjun_index, path, absolute, public)


@reference_group.with_command
@_with_index_command_options
@tanjun.as_slash_command("yuyo", "Find the references for a Yuyo type in Yuyo")
def yuyo_command(
    ctx: tanjun.abc.Context,
    path: str,
    absolute: bool,
    public: bool,
    component_client: yuyo.ComponentClient = tanjun.inject(type=yuyo.ComponentClient),
) -> collections.Awaitable[None]:
    return _index_command(ctx, component_client, yuyo_index, path, absolute, public)


reference_loader = tanjun.Component(name="reference").load_from_scope().make_loader()
