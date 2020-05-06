from __future__ import annotations

import functools
import typing

from reinhard.util import command_client

from hikari.internal import more_collections


class CommandErrorRelay:
    __slots__ = ("errors", "error_responses", "final_error")

    def __init__(
        self,
        errors: typing.Tuple[typing.Type[BaseException], ...],
        errors_responses: typing.Optional[typing.MutableMapping[typing.Type[BaseException], str]] = None,
    ) -> None:
        # if isinstance(errors, BaseException):
        #    errors = [errors]
        self.errors: typing.Tuple[typing.Type[BaseException], ...] = errors
        self.error_responses: typing.Optional[typing.MutableMapping[typing.Type[BaseException], str]] = errors_responses

    def __enter__(self) -> None:
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type in self.errors:
            raise command_client.CommandError(
                (self.error_responses or more_collections.EMPTY_DICT).get(exc_type)
                or str(getattr(exc_val, "message", exc_val))
            )  # f"{exc_type.__name__}: {exc_val}"


def command_error_relay(
    errors: typing.Union[BaseException, typing.Tuple[typing.Type[BaseException], ...]],
    errors_responses: typing.Optional[typing.MutableMapping[typing.Type[BaseException], str]] = None,
):
    @typing.no_type_check
    def decorator(func: typing.Callable[[...], typing.Coroutine[typing.Any, typing.Any, typing.Any]]):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except errors as exc:
                raise command_client.CommandError(
                    (errors_responses or more_collections.EMPTY_DICT).get(type(exc))
                    or str(getattr(exc, "message", exc))
                )

        return wrapper

    return decorator
