from __future__ import annotations

__slots__: typing.Sequence[str] = ["YoutubeDownloader"]

import asyncio
import concurrent.futures
import logging
import pathlib
import threading
import typing

import youtube_dl  # type: ignore[import]

_CLIENT_ATTRIBUTE = "REINHARD_YTDL_CLIENT"
_OUT_DIR = str(pathlib.Path("videos/%(title)s-%(id)s.%(ext)s").absolute())


def _download(url: str, /) -> typing.Tuple[pathlib.Path, typing.Dict[str, typing.Any]]:
    data = threading.local()
    client = data.__dict__.get(_CLIENT_ATTRIBUTE)

    if not client or not isinstance(client, youtube_dl.YoutubeDL):
        client = youtube_dl.YoutubeDL(
            # TODO: noplaylist isn't actually respected
            # not sure quiet is respected either
            {
                "logger": logging.getLogger("hikari.reinhard.ytdl"),
                "noplaylist": True,
                "outtmpl": _OUT_DIR,
                "quiet": True,
            }
        )
        data.__dict__[_CLIENT_ATTRIBUTE] = client

    data = client.extract_info(url)
    return pathlib.Path(client.prepare_filename(data)), data


class YoutubeDownloader:
    __slots__: typing.Sequence[str] = ("_threads",)

    def __init__(self) -> None:
        self._threads: typing.Optional[concurrent.futures.Executor] = None

    def close(self) -> None:
        if not self._threads:
            raise ValueError("Client already closed")

        self._threads.shutdown()
        self._threads = None

    @classmethod
    def spawn(cls) -> YoutubeDownloader:
        result = cls()
        result.start()
        return result

    def start(self) -> None:
        if self._threads:
            raise ValueError("Client already running")

        self._threads = concurrent.futures.ThreadPoolExecutor()

    async def download(self, url: str, /) -> typing.Tuple[pathlib.Path, typing.Dict[str, typing.Any]]:
        if not self._threads:
            raise ValueError("Client is inactive")

        return await asyncio.get_running_loop().run_in_executor(self._threads, _download, url)
