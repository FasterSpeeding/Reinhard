# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
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

__all__: list[str] = ["YoutubeDownloader"]

import asyncio
import concurrent.futures
import logging
import pathlib
import threading
import typing

import youtube_dl  # pyright: reportMissingTypeStubs=warning

_CLIENT_ATTRIBUTE = "REINHARD_YTDL_CLIENT"
_OUT_DIR = str(pathlib.Path("videos/%(title)s-%(id)s.%(ext)s").absolute())


def _download(url: str, /) -> tuple[pathlib.Path, dict[str, typing.Any]]:
    thread_local = threading.local()
    client = thread_local.__dict__.get(_CLIENT_ATTRIBUTE)

    if not client or not isinstance(client, youtube_dl.YoutubeDL):
        client = youtube_dl.YoutubeDL(  # type: ignore
            # TODO: noplaylist isn't actually respected
            # not sure quiet is respected either
            {
                "logger": logging.getLogger("hikari.reinhard.ytdl"),
                "noplaylist": True,
                "outtmpl": _OUT_DIR,
                "quiet": True,
            }
        )
        thread_local.__dict__[_CLIENT_ATTRIBUTE] = client

    data: dict[str, typing.Any] = client.extract_info(url)
    return pathlib.Path(client.prepare_filename(data)), data


class YoutubeDownloader:
    __slots__ = ("_threads",)

    def __init__(self) -> None:
        self._threads: concurrent.futures.Executor | None = None

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

    async def download(self, url: str, /) -> tuple[pathlib.Path, dict[str, typing.Any]]:
        if not self._threads:
            raise ValueError("Client is inactive")

        return await asyncio.get_running_loop().run_in_executor(self._threads, _download, url)
