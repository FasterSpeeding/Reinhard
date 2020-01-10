import os
import pathlib
import typing


from hikari.internal_utilities import assertions


def script_getter_factory(key: str):
    def script_getter(self) -> str:
        try:
            return self.scripts[key]
        except KeyError:
            raise AttributeError(f"Unable to get not loaded script '{key}'.") from None

    return property(script_getter)


class CachedScripts:
    scripts: typing.MutableMapping[str, str]

    def __init__(self, root_dir: str = ".") -> None:
        self.scripts = {}
        self.load_all_sql_files(root_dir)

    def load_sql_file(self, file_path: str) -> None:
        assertions.assert_that(
            file_path.lower().endswith(".sql"), "File must be of type 'sql'"
        )
        with open(file_path) as file:
            name = os.path.basename(file.name)[:-4]
            assertions.assert_that(
                name not in self.scripts, f"Script '{name}' already loaded."
            )  # TODO: allow overwriting?
            self.scripts[name] = file.read()

    def load_all_sql_files(
        self, root_dir: str = "."
    ) -> None:  # TODO: whitelist files instead of just taking the full load.
        root_dir = pathlib.Path(root_dir)
        for file in root_dir.rglob("*"):
            if file.is_file() and file.name.endswith(".sql"):
                self.load_sql_file(str(file.absolute()))

    schema = script_getter_factory("schema")
    get_stars = script_getter_factory("get_stars")
