from __future__ import annotations

__all__: typing.Sequence[str] = ["AIOHTTPStatusHandler", "HikariErrorManager"]

import logging
import typing

import aiohttp
from hikari import errors as hikari_errors
from tanjun import errors as tanjun_errors
from yuyo import backoff

_LOGGER = logging.getLogger("hikari.reinhard.rest_manager")


class HikariErrorManager(backoff.ErrorManager):
    __slots__: typing.Sequence[str] = ("_backoff_handler")

    def __init__(
        self, backoff_handler: backoff.Backoff, /, *, break_on: typing.Iterable[typing.Type[BaseException]] = ()
    ) -> None:
        self._backoff_handler = backoff_handler
        super().__init__()
        self.clear_rules(break_on=break_on)

    def _on_break_on(self, _: BaseException) -> bool:
        self._backoff_handler.finish()
        return False

    def _on_internal_server_error(self, _: hikari_errors.InternalServerError) -> bool:
        return False

    def _on_rate_limited_error(self, exception: hikari_errors.RateLimitedError) -> bool:
        if exception.retry_after > 10:
            return True

        self._backoff_handler.set_next_backoff(exception.retry_after)
        return False

    def clear_rules(self, *, break_on: typing.Iterable[typing.Type[BaseException]] = ()) -> None:
        super().clear_rules()
        self.with_rule((hikari_errors.InternalServerError,), self._on_internal_server_error)
        self.with_rule((hikari_errors.RateLimitedError,), self._on_rate_limited_error)

        if break_on := tuple(break_on):
            self.with_rule(break_on, self._on_break_on)


class AIOHTTPStatusHandler(backoff.ErrorManager):
    __slots__: typing.Sequence[str] = ("_backoff_handler", "_break_on", "_on_404")

    def __init__(
        self,
        backoff_handler: backoff.Backoff,
        /,
        *,
        break_on: typing.Iterable[int] = (),
        on_404: typing.Optional[str] = None,
    ) -> None:
        super().__init__()
        self._backoff_handler = backoff_handler
        self._break_on: typing.AbstractSet[int] = set()
        self._on_404: typing.Optional[str] = None
        self.clear_rules(break_on=break_on, on_404=on_404)

    def _on_client_response_error(self, exception: aiohttp.ClientResponseError) -> bool:
        if exception.status in self._break_on:
            self._backoff_handler.finish()
            return False

        if exception.status >= 500:
            return False

        if exception.status == 429:
            raw_retry_after = exception.headers.get("Retry-After") if exception.headers else None
            if raw_retry_after is not None:
                retry_after = float(raw_retry_after)

                if retry_after <= 10:
                    self._backoff_handler.set_next_backoff(retry_after)

            return False

        if self._on_404 is not None and exception.status == 404:
            raise tanjun_errors.CommandError(self._on_404) from None

        return True

    def clear_rules(self, *, break_on: typing.Iterable[int] = (), on_404: typing.Optional[str] = None) -> None:
        super().clear_rules()
        self.with_rule((aiohttp.ClientResponseError,), self._on_client_response_error)
        self._break_on = set(break_on)
        self._on_404 = on_404
