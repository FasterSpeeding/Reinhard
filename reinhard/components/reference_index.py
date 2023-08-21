# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2023, Faster Speeding
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
import importlib.metadata
import inspect
import logging
import pathlib
import re
import sys
import types
import typing
from collections import abc as collections

import alluka
import hikari
import hikari.events
import hikari.interactions
import lightbulb
import sake
import tanjun
import yuyo

from .. import utility

if typing.TYPE_CHECKING:
    from typing_extensions import Self

_MessageCommandT = typing.TypeVar("_MessageCommandT", bound=tanjun.MessageCommand[typing.Any])
_SlashCommandT = typing.TypeVar("_SlashCommandT", bound=tanjun.SlashCommand[typing.Any])
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


def _add_search_entry(index: dict[str, typing.Any], path: str) -> None:
    for char in path.rsplit(".", 1)[-1].lower():
        if sub_index := index.get(char):
            index = sub_index

        else:
            index[char] = index = {}

    if links := index.get(_END_KEY):
        if path not in links:
            links.append(path)

    else:
        index[_END_KEY] = [path]


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


def _combine_imports(part_1: str, part_2: str) -> str:
    # If this is a relative import then adding a dot in would break it.
    if part_1.endswith("."):
        return f"{part_1}{part_2}"

    return f"{part_1}.{part_2}"


def _process_relative_import(import_link: str, current_module: str) -> str:
    dots = _RELATIVE_IMPORT_DOT_PATTERN.match(import_link)
    assert dots, "We already know this starts with dots so this'll always pass"
    dot_count = len(dots.group())
    assert current_module.count(".") > (dot_count - 2), "This import is invalid, how'd you get this far?"
    return current_module.rsplit(".", dot_count)[0] + import_link[dot_count - 1 :]


def _split_by_tl_commas(string: str) -> collections.Iterator[str]:
    depth = 0
    last_comma = 0
    for index, char in enumerate(string):
        if char == "," and depth == 0:
            yield string[last_comma:index].strip()
            last_comma = index + 1

        elif char == "[":
            depth += 1

        elif char == "]":
            depth -= 1

    else:
        yield string[last_comma:].strip()


class ReferenceIndex:
    """Index used for tracking references to types in specified modules.

    Parameters
    ----------
    track_3rd_party
        Whether to track references to types in 3rd party (non-indexed) modules.
    track_builtins
        Whether to track references to types in the builtin module.
    """

    __slots__ = (
        "_aliases",
        "_alias_search_tree",
        "_is_tracking_3rd_party",
        "_is_tracking_builtins",
        "_indexed_modules",
        "_module_imports",
        "_object_paths_to_uses",
        "_object_search_tree",
        "_top_level_modules",
    )

    def __init__(self, *, track_builtins: bool = False, track_3rd_party: bool = False) -> None:
        self._aliases: dict[str, str] = {}
        self._alias_search_tree: dict[str, typing.Any] = {}
        self._is_tracking_3rd_party = track_3rd_party
        self._is_tracking_builtins = track_builtins
        self._indexed_modules: dict[str, types.ModuleType] = {}
        self._module_imports: dict[str, dict[str, str]] = {}
        self._object_paths_to_uses: dict[str, list[str]] = {}
        self._object_search_tree: dict[str, typing.Any] = {}
        self._top_level_modules: set[str] = set()

    def _add_alias(self, alias: str, target: str) -> bool:
        # If the resolved target is private then we shouldn't use it.
        if alias == target or not all(map(_is_public, target.split("."))):
            return False

        # typing and collection std generic types will never link back to where
        # the type variable was defined. To avoid accidentally linking to the
        # wrong module when targeting a type variable, we only resolve links if
        # the value was defined within an "indexed" module or the current module.
        library = target.split(".", 1)[0]
        if library in self._top_level_modules or (self._is_tracking_3rd_party and alias.startswith(library)):
            if alias not in self._aliases:
                _add_search_entry(self._alias_search_tree, alias)

            self._aliases[alias] = target
            return True

        return False

    def _add_use(self, path: str, use: str) -> None:
        if uses := self._object_paths_to_uses.get(path):
            if use not in uses:
                uses.append(use)

        else:
            self._object_paths_to_uses[path] = [use]
            _add_search_entry(self._object_search_tree, path)

    def _get_or_parse_module_imports(self, module_name: str) -> dict[str, str]:
        imports: dict[str, str] | None
        if (imports := self._module_imports.get(module_name)) is not None:
            return imports

        imports = {}
        module_path = sys.modules[module_name].__file__
        assert (
            module_path is not None
        ), "These modules were all imported using the normal import system so this should never be None"
        # TODO: parse as ast instead to support fancy stuff like multi-line imports.
        # TODO: do we want to explicitly work out star imports?
        with pathlib.Path(module_path).open("r") as file:
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

            for value in _split_by_tl_commas(inner):
                # For Callables we'll get a list of types as the generic's first argument.
                if value.startswith("[") and value.endswith("]"):
                    value = value.removeprefix("[").removesuffix("]")
                    # ... is a wildcard type and cannot be resolved in this context.
                    if value != "...":
                        for sub_annotation in _split_by_tl_commas(value):
                            self._handle_annotation(module_name, path, sub_annotation)

                else:
                    self._handle_annotation(module_name, path, value)

            return True

        return False

    def _try_find_path_source(self, path_to: str) -> str:
        """Try to normalize paths to a library's type.

        This is used to avoid cases where some references will be pointing
        towards `hikari.api.RESTClient` while others will be pointing
        towards `hikari.api.rest.RESTClient` leads to the same type having
        multiple separate reference tracking entries.
        """
        for splice in (path_to.rsplit(".", count) for count in range(path_to.count(".") + 1)):
            if splice[0] in sys.modules:
                break

        else:
            return path_to

        value: typing.Any = sys.modules[splice[0]]
        try:
            for attribute in splice[1:]:
                value = getattr(value, attribute)

        except AttributeError:
            return path_to

        if isinstance(value, (types.MethodType, types.FunctionType, type, classmethod)):
            resolved_path = f"{value.__module__}.{value.__qualname__}"

        elif isinstance(value, property) and value.fget:
            resolved_path = f"{value.fget.__module__}.{value.fget.__qualname__}"

        else:
            # For the most part this ignores typing generics as these will always link back to typing
            # regardless of where the type-variable was defined.
            return path_to

        # add_alias returns a bool which tells us whether the alias was valid or not.
        if self._add_alias(path_to, resolved_path):
            return resolved_path

        # TODO: can we special case generic types here to capture their inner-values?
        return path_to

    def _handle_annotation(self, module_name: str, path: str, annotation: type[typing.Any] | str) -> None:
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
                    self._add_use(self._try_find_path_source(import_path + without_key), path)
                    return

            # If we hit this statement then this indicates that the annotation
            # refers to a 3rd party type and that we aren't tracking 3rd party
            # types so this can be safely ignored.
            else:
                _LOGGER.debug("Ignoring %r annotation from out-of-scope library at %r", annotation, path)

        else:
            # If we got this far then it is either located in the current
            # module being imported by a star import.

            # _try_find_path_source will resolve star imports if the module
            # and import are both within scope.
            self._add_use(self._try_find_path_source(f"{module_name}.{annotation}"), path)

    def _recurse_module(
        self,
        obj: types.MethodType
        | types.FunctionType
        | type[typing.Any]
        | classmethod[typing.Any, typing.Any, typing.Any]
        | property,
        /,
        *,
        path: str | None = None,
    ) -> bool:
        if isinstance(obj, (types.MethodType, types.FunctionType, classmethod)):
            if return_type := obj.__annotations__.get("return"):
                path = f"{path}()" if path else f"{obj.__module__}.{obj.__qualname__}()"
                self._handle_annotation(obj.__module__, path, return_type)
                return True

        elif isinstance(obj, property) and obj.fget:
            if return_type := obj.fget.__annotations__.get("return"):
                path = path or f"{obj.fget.__module__}.{obj.fget.__qualname__}"
                self._handle_annotation(obj.fget.__module__, path, return_type)
                return True

        elif isinstance(obj, type):
            path = path or f"{obj.__module__}.{obj.__qualname__}"
            # Used to track attributes which'd been overwritten through inheritance.
            found_attributes: set[str] = set()

            for name, attribute in filter(_is_public_key, inspect.getmembers(obj)):
                if self._recurse_module(attribute, path=f"{path}.{name}"):
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

    def index_module(self, module: types.ModuleType, /, *, recursive: bool = False) -> Self:
        """Add a module to the internal index of in-scope modules.

        Any types declared in these modules will have their uses tracked.

        Parameters
        ----------
        module
            The module to index.
        """
        self._indexed_modules[module.__name__] = module
        self._top_level_modules.add(module.__name__.split(".", 1)[0])

        if recursive:
            return self.index_sub_modules(module)

        return self

    def _walk_sub_modules(
        self,
        start_point: str,
        found_modules: set[str],
        callback: collections.Callable[[types.ModuleType], typing.Any],
        module: types.ModuleType,
        /,
        *,
        check: collections.Callable[[types.ModuleType], bool] | None,
        children_only: bool,
        recursive: bool,
    ) -> Self:
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
        self,
        module: types.ModuleType,
        /,
        *,
        check: collections.Callable[[types.ModuleType], bool] | None = None,
        children_only: bool = True,
        recursive: bool = True,
    ) -> Self:
        """Add a module's sub-modules to the internal index of in-scope modules.

        Any types declared in these modules will have their uses tracked.

        Parameters
        ----------
        module
            The module to index the sub-modules in.
        check
            If provided, a callback which will decide which sub-modules should be indexed.
            If `None` then all sub-modules will be indexed.
        children_only
            Whether found modules which aren't direct children of the passed
            module should be ignored.

            Defaults to `True`.
        recursive
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

    def scan_indexed_modules(self) -> Self:
        """Scan the indexed modules for type references."""
        for module in self._indexed_modules.values():
            self.scan_module(module)

        return self

    def scan_module(self, module: types.ModuleType, /, *, recursive: bool = False) -> Self:
        """Scan a module for type references.

        Parameters
        ----------
        module
            The module to scan for type references.
        """
        module_members = dict[str, typing.Any](filter(_is_public_key, inspect.getmembers(module)))
        for name, obj in module_members.items():
            if isinstance(obj, (types.FunctionType, types.MethodType, type, classmethod)):
                self._add_alias(f"{module.__name__}.{name}", f"{obj.__module__}.{obj.__qualname__}")
                self._recurse_module(obj)

            elif isinstance(obj, property) and obj.fget:
                self._add_alias(f"{module.__name__}.{name}", f"{obj.fget.__module__}.{obj.fget.__qualname__}")
                self._recurse_module(obj)

        if recursive:
            self.scan_sub_modules(module)

        return self

    def scan_sub_modules(
        self,
        module: types.ModuleType,
        /,
        *,
        check: collections.Callable[[types.ModuleType], bool] | None = None,
        children_only: bool = True,
        recursive: bool = True,
    ) -> Self:
        """Scan sub-modules for type references.

        Parameters
        ----------
        module
            The module to scan sub-modules in.
        check
            If provided, a callback which will decide which sub-modules should be scanned.
            If `None` then all sub-modules will be scanned.
        children_only
            Whether found modules which aren't direct children of the passed
            module should be ignored.

            Defaults to `True`.
        recursive
            If `True` then this will recursively scan sub-modules instead of just
            scanning modules directly on the provided module.

            Defaults to `True`.
        """
        return self._walk_sub_modules(
            module.__name__,
            set(),
            self.scan_module,
            module,
            check=check,
            children_only=children_only,
            recursive=recursive,
        )

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
                    f"No references found for the absolute path `{path}`", component=utility.delete_row(ctx)
                )

            full_path = path
            uses = result

        else:
            if not (result := self.index.search(path)):
                raise tanjun.CommandError(f"No references found for `{path}`", component=utility.delete_row(ctx))

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


hikari_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_module(hikari, recursive=True)
    .scan_indexed_modules()
)
hikari_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(hikari_index, "Hikari v" + importlib.metadata.version("hikari")),
            "hikari",
            "Find the references for types in hikari",
        ),
        hikari_index,
    )
)
hikari_command = _with_index_message_options(tanjun.MessageCommand(hikari_command.callback, "references hikari"))


lightbulb_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_module(lightbulb, recursive=True)
    .index_module(hikari, recursive=True)
    .scan_module(lightbulb, recursive=True)
)
lightbulb_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(lightbulb_index, "Lightbulb v" + importlib.metadata.version("hikari-lightbulb")),
            "lightbulb",
            "Find the references for types in lightbulb",
        ),
        lightbulb_index,
    )
)
lightbulb_command = _with_index_message_options(
    tanjun.MessageCommand(lightbulb_command.callback, "references lightbulb")
)

sake_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_module(sake, recursive=True)
    .index_module(hikari, recursive=True)
    .scan_module(sake, recursive=True)
)
sake_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(sake_index, "Sake v" + importlib.metadata.version("hikari-sake")),
            "sake",
            "Find the references for types in Sake",
        ),
        sake_index,
    )
)
sake_command = _with_index_message_options(tanjun.MessageCommand(sake_command.callback, "references sake"))


tanjun_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_module(tanjun, recursive=True)
    .index_module(hikari, recursive=True)
    .scan_module(tanjun, recursive=True)
)
tanjun_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(tanjun_index, "Tanjun v" + importlib.metadata.version("hikari-tanjun")),
            "tanjun",
            "Find the references for types in Tanjun",
        ),
        tanjun_index,
    )
)
tanjun_command = _with_index_message_options(tanjun.MessageCommand(tanjun_command.callback, "references tanjun"))


yuyo_index = (
    ReferenceIndex(track_builtins=True, track_3rd_party=True)
    .index_module(yuyo, recursive=True)
    .index_module(hikari, recursive=True)
    .scan_module(yuyo, recursive=True)
)
yuyo_command = reference_group.with_command(
    _with_index_slash_options(
        tanjun.SlashCommand(
            _IndexCommand(yuyo_index, "Yuyo v" + importlib.metadata.version("hikari-yuyo")),
            "yuyo",
            "Find the references for a Yuyo type in Yuyo",
        ),
        yuyo_index,
    )
)
yuyo_command = _with_index_message_options(tanjun.MessageCommand(yuyo_command.callback, "references yuyo"))


load_reference = tanjun.Component(name="reference").load_from_scope().make_loader()
