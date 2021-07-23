from __future__ import annotations

__all__: typing.Sequence[str] = ["AIOHTTPStatusHandler", "HikariErrorManager"]

import typing

import aiohttp
from hikari import errors as hikari_errors
from hikari import undefined
from tanjun import errors as tanjun_errors
from yuyo import backoff

if typing.TYPE_CHECKING:
    from hikari import embeds
    from tanjun import traits as tanjun_traits


class HikariErrorManager(backoff.ErrorManager):
    __slots__: typing.Sequence[str] = ("_backoff_handler",)

    def __init__(
        self,
        backoff_handler: typing.Optional[backoff.Backoff] = None,
        /,
        *,
        break_on: typing.Iterable[typing.Type[BaseException]] = (),
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
    def _on_internal_server_error(_: hikari_errors.InternalServerError) -> bool:
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

    async def try_respond(
        self,
        ctx: tanjun_traits.MessageContext,
        *,
        content: undefined.UndefinedOr[str] = undefined.UNDEFINED,
        embed: undefined.UndefinedOr[embeds.Embed] = undefined.UNDEFINED,
    ) -> None:
        self._backoff_handler.reset()

        async for _ in self._backoff_handler:
            with self:
                await ctx.message.respond(content=content, embed=embed)
                break


class AIOHTTPStatusHandler(backoff.ErrorManager):
    __slots__: typing.Sequence[str] = ("_backoff_handler", "_break_on", "_on_404")

    def __init__(
        self,
        backoff_handler: backoff.Backoff,
        /,
        *,
        break_on: typing.Iterable[int] = (),
        on_404: typing.Union[str, typing.Callable[[], None], None] = None,
    ) -> None:
        super().__init__()
        self._backoff_handler = backoff_handler
        self._break_on: typing.AbstractSet[int] = set()
        self._on_404: typing.Union[str, typing.Callable[[], None], None] = None
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
            if isinstance(self._on_404, str):
                raise tanjun_errors.CommandError(self._on_404) from None

            else:
                self._on_404()

        return True

    def clear_rules(
        self, *, break_on: typing.Iterable[int] = (), on_404: typing.Union[str, typing.Callable[[], None], None] = None
    ) -> None:
        super().clear_rules()
        self.with_rule((aiohttp.ClientResponseError,), self._on_client_response_error)
        self._break_on = set(break_on)
        self._on_404 = on_404
