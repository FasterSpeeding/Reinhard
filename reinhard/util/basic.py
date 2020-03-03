import functools
import re
import typing


from reinhard.util import command_client


from hikari.internal_utilities import aio
from hikari.internal_utilities import containers


class ReturnErrorStr:
    __slots__ = ("errors", "error_responses", "final_error")

    def __init__(
        self,
        errors: typing.Tuple[BaseException],
        errors_responses: typing.Optional[typing.MutableMapping[BaseException, str]] = None,
    ) -> None:
        #    if isinstance(errors, BaseException):
        #        errors = (errors, )
        self.errors: typing.Tuple[BaseException] = errors
        self.error_responses: typing.Optional[typing.MutableMapping[BaseException, str]] = errors_responses

    def __enter__(self) -> None:
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type in self.errors:
            raise command_client.CommandError(
                (self.error_responses or containers.EMPTY_DICT).get(exc_type)
                or str(getattr(exc_val, "message", exc_val))
            )  # f"{exc_type.__name__}: {exc_val}"


def return_error_str(
    errors: typing.Union[BaseException, typing.Tuple[BaseException]],
    errors_responses: typing.Optional[typing.MutableMapping[BaseException, str]] = None,
):
    def decorator(func: aio.CoroutineFunctionT):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> typing.Optional[str]:
            try:
                return await func(*args, **kwargs)
            except errors as exc:
                raise command_client.CommandError(
                    (errors_responses or containers.EMPTY_DICT).get(type(exc))
                    or str(getattr(exc, "message", None) or exc)
                )

        return wrapper

    return decorator
