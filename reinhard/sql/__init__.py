# -*- coding: utf-8 -*-
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
from __future__ import annotations

import pathlib
import re

import asyncpg  # pyright: reportMissingTypeStubs=warning


def script_getter_factory(key: str) -> property:  # Could just make this retrieve the file.
    """
    A script_getter factory that allows for pre-setting the script key/name. This is used to map out expected script
    using explicit properties and to handle errors for when the modules aren't loaded.
    """

    def get_script(self: CachedScripts) -> str:
        """Used to get a loaded script using it's key/name."""
        try:
            return self.scripts[key]
        except KeyError:
            raise AttributeError(f"Unable to get unloaded script '{key}'.") from None

    return property(get_script)


class CachedScripts:
    """A class used for loading and calling sql scripts from a folder."""

    scripts: dict[str, str]

    def __init__(self, root_dir: str | None = "./reinhard/sql", pattern: str = ".") -> None:
        self.scripts = {}
        if root_dir is not None:
            self.load_all_sql_files(root_dir, pattern)

    def load_sql_file(self, file_path: pathlib.Path, /) -> None:
        """Load an sql script from it's path into `self.scripts`.

        Parameters
        ----------
        file_path
            The string path of the file to load.
        """
        if not file_path.name.endswith(".sql"):
            raise ValueError("File must be of type 'sql'")

        with file_path.open("r") as file:
            name = file_path.name[:-4]

            if name in self.scripts:
                raise RuntimeError(f"Script {name!r} already loaded.")  # TODO: allow overwriting?

            self.scripts[name] = file.read()

    def load_all_sql_files(self, root_dir: str = "./reinhard/sql", pattern: str = ".") -> None:
        """Load all the sql files from location recursively.

        Parameters
        ----------
        root_dir
            The string path of the root directory, defaults to reinhard's sql folder.
        pattern
            The optional regex string to use for matching the names of files to load.
        """
        root_dir_path = pathlib.Path(root_dir)
        for path in root_dir_path.rglob("*"):
            if path.is_file() and path.name.endswith(".sql") and re.match(pattern, path.name):
                self.load_sql_file(path)

    create_post_star = script_getter_factory("create_post_star")
    create_starboard_channel = script_getter_factory("create_starboard_channel")
    create_starboard_entry = script_getter_factory("create_starboard_entry")
    find_guild_prefix = script_getter_factory("find_guild_prefix")
    schema = script_getter_factory("schema")


async def initialise_schema(sql_scripts: CachedScripts, conn: asyncpg.Connection) -> None:
    """Initialise the database schema if not already present.

    Parameters
    ----------
    sql_scripts
        An instance of `CachedScripts` where schema has been loaded.
    conn
        An active `asyncpg.Connection`.
    """
    try:
        await conn.execute(sql_scripts.schema)
    except asyncpg.PostgresError as exc:  # pyright: reportUnknownVariableType=warning
        raise RuntimeError("Failed to initialise database.") from exc
