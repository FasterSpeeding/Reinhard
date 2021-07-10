from __future__ import annotations

from . import client as client_module


def main() -> None:
    client_module.build_bot().run()


if __name__ == "__main__":
    main()
