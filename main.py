from __future__ import annotations

import reinhard.cli

if __name__ == "__main__":
    try:
        import uvloop  # type: ignore

        uvloop.install()  # type: ignore

    except ImportError:
        pass

    reinhard.cli.main()
