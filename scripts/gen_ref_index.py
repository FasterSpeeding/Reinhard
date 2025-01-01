# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2025, Faster Speeding
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

import ast
import click

import importlib
import inspect
import logging
import json
import importlib.metadata
import pathlib
import re
import sys
import types
import typing
from collections import abc as collections


if typing.TYPE_CHECKING:
    from typing import Self

_LOGGER = logging.getLogger("hikari.reinhard.reference_index")


def _is_public(key: str) -> bool:
    return not key.startswith("_")


def _is_public_key(entry: tuple[str, typing.Any]) -> bool:
    return _is_public(entry[0])


_GENERIC_CAPTURE_PATTERN = re.compile(r"([\w\.]+)\[(.+)\]$", flags=re.ASCII)
_NAME_PATTERN = re.compile(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", flags=re.ASCII)
_BUILTIN_TYPES = set(filter(_is_public, dir(__builtins__)))
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


def _process_relative_import(import_link: str | None, current_module: str, depth: int) -> str:
    assert current_module.count(".") > (depth - 2), "This import is invalid, how'd you get this far?"
    parent = current_module.rsplit(".", depth)[0]
    if import_link is None:
        return parent

    return f"{parent}.{import_link}"


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


_TYPING_IMPORTS = {"t", "typing"}


# TODO: this could just be passed a list of how typing.TYPE_CHECKING is
# imported if i was real smart about it
def _process_if(ast_to_check: list[ast.stmt], statement: ast.If, /) -> None:
    if isinstance(statement.test, ast.Name) and statement.test.id == "TYPE_CHECKING":
        ast_to_check.extend(statement.body)
        return

    if not isinstance(statement.test, ast.Attribute) or not isinstance(statement.test.value, ast.Name):
        return

    if statement.test.value.id in _TYPING_IMPORTS and statement.test.attr == "TYPE_CHECKING":
        ast_to_check.extend(statement.body)


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
        "_version"
    )

    def __init__(self, *, track_builtins: bool = False, track_3rd_party: bool = False, version: str = "unknown") -> None:
        self._aliases: dict[str, str] = {}
        self._alias_search_tree: dict[str, typing.Any] = {}
        self._is_tracking_3rd_party = track_3rd_party
        self._is_tracking_builtins = track_builtins
        self._indexed_modules: dict[str, types.ModuleType] = {}
        self._module_imports: dict[str, dict[str, str]] = {}
        self._object_paths_to_uses: dict[str, list[str]] = {}
        self._object_search_tree: dict[str, typing.Any] = {}
        self._top_level_modules: set[str] = set()
        self._version = version

    def save(self, out: pathlib.Path, /) -> None:
        data = {
            "aliases": self._aliases,
            "alias_search_tree": self._alias_search_tree,
            "object_paths_to_uses": self._object_paths_to_uses,
            "object_search_tree": self._object_search_tree,
            "version": self._version,
        }
        with out.open("w+") as file:
            json.dump(data, file)

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
        # TODO: do we want to explicitly work out star imports?
        with pathlib.Path(module_path).open("r") as file:
            # TODO: chunk this?
            parsed_ast = ast.parse(file.read())

        ast_to_check: list[ast.stmt] = parsed_ast.body
        while ast_to_check:
            statement = ast_to_check.pop()
            if isinstance(statement, ast.Import):
                current = [(i.name, i.name, 0) for i in statement.names]

            elif isinstance(statement, ast.ImportFrom):
                current = [(statement.module, name.name, statement.level) for name in statement.names]

            elif isinstance(statement, ast.If):
                _process_if(ast_to_check, statement)
                current = []
                continue

            else:
                continue

            for imported_from, imported_name, depth in current:
                if depth:
                    imported_from = _process_relative_import(imported_from, module_name, depth)

                else:
                    assert imported_from is not None

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
        obj: (
            types.MethodType
            | types.FunctionType
            | type[typing.Any]
            | classmethod[typing.Any, typing.Any, typing.Any]
            | property
        ),
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
            # operator.attrgetter doesn't have __annotations__
            try:
                annotations = obj.fget.__annotations__

            except AttributeError:
                return False

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
        _LOGGER.info("Indexing %s", module.__name__)
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
        _LOGGER.info("Scanning %s", module.__name__)
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

@click.group()
def gen() -> None:
    ...


@click.option("--out-dir", "-o", default=pathlib.Path("./"), type=click.Path(dir_okay=True, path_type=pathlib.Path))
@gen.command("default")
def default(out_dir: pathlib.Path) -> None:
    out_dir.mkdir(exist_ok=True, parents=True)
    assert override.callback
    override.callback(out=out_dir / "hikari_index.json", index=["hikari"], scan=["hikari"], package="hikari")

    for lib, package in (("sake", "hikari-sake"), ("tanjun", "hikari-tanjun"), ("yuyo", "hikari-yuyo"), ("lightbulb", "hikari-lightbulb"), ("arc", "hikari-arc"), ("crescent", "hikari-crescent"), ("miru", "hikari-miru")):
        override.callback(out_dir / f"{lib}_index.json", index=[lib, "hikari"], scan=[lib], package=package)


@click.option("--package", default=None)
@click.option("--skip-3rd-party", default=False)
@click.option("--skip-builtins", default=False)
@click.option("--index", "-i", multiple=True, required=True)
@click.option("--scan", "-s", multiple=True, required=True)
@click.argument("out", type=click.Path(writable=True, path_type=pathlib.Path))
@gen.command("override")
def override(
    out: pathlib.Path,
    index: list[str],
    scan: list[str],
    skip_builtins: bool = False,
    skip_3rd_party: bool = False,
    package: str | None = None,
) -> None:
    if package is not None:
        version = importlib.metadata.version(package)

    else:
        version = "unknown"

    result = ReferenceIndex(track_builtins=not skip_builtins, track_3rd_party=not skip_3rd_party, version=version)
    for to_index in index:
        module = importlib.import_module(to_index)
        result.index_module(module, recursive=True)

    for to_scan in scan:
        module = importlib.import_module(to_scan)
        result.scan_module(module, recursive=True)

    result.save(out)


if __name__ == "__main__":
    gen()
