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

__all__: list[str] = ["AIOHTTPStatusHandler", "ClientCredentialsOauth2", "FetchedResource", "HikariErrorManager"]

import logging
import time
import typing
from collections import abc as collections

import aiohttp
import hikari
import tanjun
from yuyo import backoff

_ValueT = typing.TypeVar("_ValueT")
_LOGGER = logging.getLogger("hikari.reinhard.rest_utility")


class HikariErrorManager(backoff.ErrorManager):
    __slots__ = ("_backoff_handler",)

    def __init__(
        self,
        backoff_handler: backoff.Backoff | None = None,
        /,
        *,
        break_on: collections.Iterable[type[BaseException]] = (),
    ) -> None:
        if backoff_handler is None:
            backoff_handler = backoff.Backoff(max_retries=5)
        self._backoff_handler = backoff_handler
        super().__init__()
        self.clear_rules(break_on=break_on)

    def _on_break_on(self, _: BaseException) -> bool:
        self._backoff_handler.finish()
        return False

    @staticmethod
    def _on_internal_server_error(_: hikari.InternalServerError) -> bool:
        return False

    def _on_rate_limited_error(self, exception: hikari.RateLimitedError) -> bool:
        if exception.retry_after > 10:
            return True

        self._backoff_handler.set_next_backoff(exception.retry_after)
        return False

    def clear_rules(self, *, break_on: collections.Iterable[type[BaseException]] = ()) -> None:
        super().clear_rules()
        self.with_rule((hikari.InternalServerError,), self._on_internal_server_error)
        self.with_rule((hikari.RateLimitedError,), self._on_rate_limited_error)

        if break_on := tuple(break_on):
            self.with_rule(break_on, self._on_break_on)

    async def try_respond(
        self,
        ctx: tanjun.abc.Context,
        *,
        content: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
    ) -> None:
        self._backoff_handler.reset()

        async for _ in self._backoff_handler:
            with self:
                await ctx.respond(content=content, embed=embed)
                break


class AIOHTTPStatusHandler(backoff.ErrorManager):
    __slots__ = ("_backoff_handler", "_break_on", "_on_404")

    def __init__(
        self,
        backoff_handler: backoff.Backoff,
        /,
        *,
        break_on: collections.Iterable[int] = (),
        on_404: str | collections.Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._backoff_handler = backoff_handler
        self._break_on: collections.Set[int] = set()
        self._on_404: str | collections.Callable[[], None] | None = None
        self.clear_rules(break_on=break_on, on_404=on_404)

    def _on_client_response_error(self, exception: aiohttp.ClientResponseError) -> bool:
        if exception.status in self._break_on:
            self._backoff_handler.finish()
            return False

        if exception.status >= 500:
            return False

        if exception.status == 429:
            raw_retry_after: str | None = exception.headers.get("Retry-After") if exception.headers else None
            if raw_retry_after is not None:
                retry_after = float(raw_retry_after)

                if retry_after <= 10:
                    self._backoff_handler.set_next_backoff(retry_after)

            return False

        if self._on_404 is not None and exception.status == 404:
            if isinstance(self._on_404, str):
                raise tanjun.CommandError(self._on_404) from None

            else:
                self._on_404()

        return True

    def clear_rules(
        self, *, break_on: collections.Iterable[int] = (), on_404: str | collections.Callable[[], None] | None = None
    ) -> None:
        super().clear_rules()
        self.with_rule((aiohttp.ClientResponseError,), self._on_client_response_error)
        self._break_on = set(break_on)
        self._on_404 = on_404


class FetchedResource(typing.Generic[_ValueT]):
    __slots__ = ("_authorization", "_headers", "_parse_data", "_path")

    def __init__(
        self,
        path: str,
        parse_data: collections.Callable[[bytes], _ValueT],
        *,
        authorization: aiohttp.BasicAuth | None = None,
        headers: dict[str, typing.Any] | None = None,
    ) -> None:
        self._authorization = authorization
        self._headers = headers
        self._parse_data = parse_data
        self._path = path

    async def __call__(self, session: aiohttp.ClientSession = tanjun.inject(type=aiohttp.ClientSession)) -> _ValueT:
        response = await session.get(self._path)
        # TODO: better handling
        response.raise_for_status()
        return self._parse_data(await response.read())


class ClientCredentialsOauth2:
    __slots__ = ("_authorization", "_expire_at", "_path", "_prefix", "_token")

    def __init__(self, path: str, client_id: str, client_secret: str, *, prefix: str = "Bearer ") -> None:
        self._authorization = aiohttp.BasicAuth(client_id, client_secret)
        self._expire_at = 0
        self._path = path
        self._prefix = prefix
        self._token: str | None = None

    @property
    def _expired(self) -> bool:
        return time.time() >= self._expire_at

    async def acquire_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and not self._expired:
            return self._token

        response = await session.post(self._path, data={"grant_type": "client_credentials"}, auth=self._authorization)

        if 200 <= response.status < 300:
            try:
                data = await response.json()
                expire = round(time.time()) + data["expires_in"] - 120
                token = data["access_token"]

            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError, KeyError, TypeError) as exc:
                _LOGGER.exception(
                    "Couldn't decode or handle client credentials response received from %s: %r",
                    self._path,
                    await response.text(),
                    exc_info=exc,
                )

            else:
                self._expire_at = expire
                self._token = f"{self._prefix} {token}"
                return self._token

        else:
            _LOGGER.warning(
                "Received %r from %s while trying to authenticate as client credentials",
                response.status,
                self._path,
            )
        raise tanjun.CommandError("Couldn't authenticate")
