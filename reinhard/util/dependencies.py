from __future__ import annotations

__all__: typing.Sequence[str] = ["SessionDependency", "PaginatorPoolDependency"]

import asyncio
import logging
import typing

import aiohttp
from hikari import traits
from tanjun import injector
from yuyo import paginaton

if typing.TYPE_CHECKING:
    from hikari import config

_LOGGER = logging.getLogger("hikari.reinhard")


class SessionDependency:  # TODO: add on_closing, closed, opening and opened handlers to Tanjun
    __slots__: typing.Sequence[str] = ("http_settings", "proxy_settings", "_session", "user_agent")

    def __init__(
        self, http_settings: config.HTTPSettings, proxy_settings: config.ProxySettings, user_agent: str
    ) -> None:
        self.http_settings = http_settings
        self.proxy_settings = proxy_settings
        self._session: typing.Optional[aiohttp.ClientSession] = None
        self.user_agent = user_agent

    def __call__(self) -> aiohttp.ClientSession:
        # Assert that this is only called within a live event loop
        asyncio.get_running_loop()
        if self._session is None:
            # Assert this is only called within an active event loop
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
            _LOGGER.debug("acquired new aiohttp client session")

        return self._session


class PaginatorPoolDependency:
    __slots__: typing.Sequence[str] = ("_paginator",)

    def __init__(self) -> None:
        self._paginator: typing.Optional[paginaton.PaginatorPool] = None

    def __call__(
        self,
        rest_client: traits.RESTAware = injector.injected(type=traits.RESTAware),  # type: ignore[misc]
        event_client: traits.EventManagerAware = injector.injected(type=traits.EventManagerAware),  # type: ignore[misc]
    ) -> paginaton.PaginatorPool:
        if not self._paginator or self._paginator.is_closed:
            self._paginator = paginaton.PaginatorPool(rest_client, event_client)
            asyncio.create_task(self._paginator.open())

        return self._paginator
