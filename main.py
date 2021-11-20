from __future__ import annotations

if __name__ == "__main__":
    try:
        import pyjion  # type: ignore

        pyjion.enable()  # type: ignore
        pyjion.config(threshold=30, pgc=True, level=2, debug=False, graph=False)  # type: ignore
        print("Running with pyjion")

    except ImportError:
        print("Running without pyjion")
        pass

    try:
        import uvloop  # type: ignore

        print("Running with uvloop")
        uvloop.install()  # type: ignore

    except ImportError:
        print("Running with standard asyncio loop")

    import reinhard.cli
    reinhard.cli.main()
