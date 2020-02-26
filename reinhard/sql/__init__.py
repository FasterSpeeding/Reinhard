import os
import re
import pathlib
import typing


from hikari.internal_utilities import assertions
import asyncpg


def script_getter_factory(key: str):  # Could just make this retrieve the file.
    """
    A script_getter factory that allows for pre-setting the script key/name. This is used to map out expected script
    using explicit properties and to handle errors for when the modules aren't loaded.
    """

    def script_getter(self) -> str:
        """Used to get a loaded script using it's key/name."""
        try:
            return self.scripts[key]
        except KeyError:
            raise AttributeError(f"Unable to get not loaded script '{key}'.") from None

    return property(script_getter)


class CachedScripts:
    """A module used for loading and calling sql scripts from a folder."""

    scripts: typing.MutableMapping[str, str]

    def __init__(self, root_dir: typing.Optional[str] = "./reinhard/sql", pattern: str = None) -> None:
        self.scripts = {}
        if root_dir is not None:
            self.load_all_sql_files(root_dir, pattern)

    def load_sql_file(self, file_path: str) -> None:
        """
        Load an sql script from it's path into `self.scripts`.

        Args:
            file_path:
                The string path of the module to load.
        """
        assertions.assert_that(file_path.lower().endswith(".sql"), "File must be of type 'sql'")
        with open(file_path, "r") as file:
            name = os.path.basename(file.name)[:-4]
            assertions.assert_that(
                name not in self.scripts, f"Script '{name}' already loaded."
            )  # TODO: allow overwriting?
            self.scripts[name] = file.read()

    def load_all_sql_files(self, root_dir: str = "./reinhard/sql", pattern: str = None) -> None:
        """
        Load all the sql files from location recursively.

        Args:
            root_dir:
                The string path of the root directory, defaults to reinhard's sql folder.
            pattern:
                The optional regex string to use for matching the names of files to load.
        """
        root_dir = pathlib.Path(root_dir)
        for file in root_dir.rglob("*"):
            if file.is_file() and file.name.endswith(".sql") and not pattern or re.match(pattern, file.name):
                self.load_sql_file(str(file.absolute()))

    # TODO: split up?
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
    except asyncpg.PostgresError as e:
        raise RuntimeError("Failed to initialise database.") from e
