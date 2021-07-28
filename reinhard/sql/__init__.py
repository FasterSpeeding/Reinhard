from __future__ import annotations

import os
import pathlib
import re

import asyncpg  # type: ignore[import]


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

    def load_sql_file(self, file_path: str) -> None:
        """
        Load an sql script from it's path into `self.scripts`.

        Args:
            file_path:
                The string path of the file to load.
        """
        if not file_path.lower().endswith(".sql"):
            raise ValueError("File must be of type 'sql'")

        with open(file_path, "r") as file:
            name = os.path.basename(file.name)[:-4]

            if name in self.scripts:
                raise RuntimeError(f"Script {name!r} already loaded.")  # TODO: allow overwriting?

            self.scripts[name] = file.read()

    def load_all_sql_files(self, root_dir: str = "./reinhard/sql", pattern: str = ".") -> None:
        """
        Load all the sql files from location recursively.

        Args:
            root_dir:
                The string path of the root directory, defaults to reinhard's sql folder.
            pattern:
                The optional regex string to use for matching the names of files to load.
        """
        root_dir_path = pathlib.Path(root_dir)
        for file in root_dir_path.rglob("*"):
            if file.is_file() and file.name.endswith(".sql") and re.match(pattern, file.name):
                self.load_sql_file(str(file.absolute()))

    create_post_star = script_getter_factory("create_post_star")
    create_starboard_channel = script_getter_factory("create_starboard_channel")
    create_starboard_entry = script_getter_factory("create_starboard_entry")
    find_guild_prefix = script_getter_factory("find_guild_prefix")
    schema = script_getter_factory("schema")


async def initialise_schema(sql_scripts: CachedScripts, conn: asyncpg.Connection) -> None:
    """
    Initialise the database schema if not already present.

    Args:
        sql_scripts:
            An instance of :class:`CachedScripts` where schema has been loaded.
        conn:
            An active :class:`asyncpg.Connection`.
    """
    try:
        await conn.execute(sql_scripts.schema)
    except asyncpg.PostgresError as exc:
        raise RuntimeError("Failed to initialise database.") from exc
