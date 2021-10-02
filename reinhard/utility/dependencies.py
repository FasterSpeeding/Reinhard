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

__all__: list[str] = ["SessionManager"]

import asyncio
import logging
import typing

import aiohttp
import tanjun

if typing.TYPE_CHECKING:
    from hikari import config


_LOGGER = logging.getLogger("hikari.reinhard")


class SessionManager:
    __slots__ = ("http_settings", "proxy_settings", "_session", "user_agent")

    def __init__(
        self, http_settings: config.HTTPSettings, proxy_settings: config.ProxySettings, user_agent: str
    ) -> None:
        self.http_settings = http_settings
        self.proxy_settings = proxy_settings
        self._session: aiohttp.ClientSession | None = None
        self.user_agent = user_agent

    def __call__(self) -> aiohttp.ClientSession:
        if not self._session:
            raise RuntimeError("Session isn't active")

        return self._session

    def load_into_client(self, client: tanjun.Client) -> None:
        client.add_client_callback(tanjun.ClientCallbackNames.STARTING, self.open).add_client_callback(
            tanjun.ClientCallbackNames.CLOSED, self.close
        )

    # TODO: switch over to tanjun.InjectorClient
    def open(self, client: tanjun.Client = tanjun.injected(type=tanjun.Client)) -> None:
        if self._session:
            raise RuntimeError("Session already running")

        # Assert that this is only called within a live event loop
        asyncio.get_running_loop()
        self._session = aiohttp.ClientSession(
            headers={"User-Agent": self.user_agent},
            raise_for_status=False,
            timeout=aiohttp.ClientTimeout(
                connect=self.http_settings.timeouts.acquire_and_connect,
                sock_connect=self.http_settings.timeouts.request_socket_connect,
                sock_read=self.http_settings.timeouts.request_socket_read,
                total=self.http_settings.timeouts.total,
            ),
            trust_env=self.proxy_settings.trust_env,
        )
        client.set_type_dependency(aiohttp.ClientSession, self._session)
        _LOGGER.debug("acquired new aiohttp client session")

    async def close(self, client: tanjun.Client = tanjun.injected(type=tanjun.Client)) -> None:
        if not self._session:
            raise RuntimeError("Session not running")

        session = self._session
        self._session = None
        await session.close()
        client.remove_type_dependency(aiohttp.ClientSession)
