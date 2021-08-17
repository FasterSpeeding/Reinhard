from __future__ import annotations

__all__: list[str] = ["SessionDependency", "ReactionClientDependency", "ComponentClientDependency"]

import asyncio
import logging
import typing

import aiohttp
import yuyo
from hikari import traits
from tanjun import injecting

if typing.TYPE_CHECKING:
    from hikari import config

_LOGGER = logging.getLogger("hikari.reinhard")


class SessionDependency:  # TODO: add on_closing, closed, opening and opened handlers to Tanjun
    __slots__ = ("http_settings", "proxy_settings", "_session", "user_agent")

    def __init__(
        self, http_settings: config.HTTPSettings, proxy_settings: config.ProxySettings, user_agent: str
    ) -> None:
        self.http_settings = http_settings
        self.proxy_settings = proxy_settings
        self._session: aiohttp.ClientSession | None = None
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


class ReactionClientDependency:
    __slots__ = ("_client",)

    def __init__(self) -> None:
        self._client: yuyo.ReactionClient | None = None

    def __call__(
        self,
        rest_client: traits.RESTAware = injecting.injected(type=traits.RESTAware),
        event_client: traits.EventManagerAware = injecting.injected(type=traits.EventManagerAware),
    ) -> yuyo.ReactionClient:
        if not self._client or self._client.is_closed:
            self._client = yuyo.ReactionClient(rest=rest_client.rest, event_manager=event_client.event_manager)
            asyncio.create_task(self._client.open())

        return self._client


class ComponentClientDependency:
    __slots__ = ("_client",)

    def __init__(self) -> None:
        self._client: yuyo.ComponentClient | None = None

    def __call__(
        self,
        event_client: traits.EventManagerAware = injecting.injected(type=traits.EventManagerAware),
        # interaction_client: traits.InteractionServerAware  # TODO: needs defaults for this to work
    ) -> yuyo.ComponentClient:
        if not self._client:
            self._client = yuyo.ComponentClient(event_manager=event_client.event_manager)
            self._client.open()

        return self._client
