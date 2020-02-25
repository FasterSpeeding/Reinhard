import functools
import re
import typing


from reinhard import command_client


from hikari.internal_utilities import aio
from hikari.internal_utilities import containers


def get_snowflake(content: str) -> int:  # TODO: neko said a better way to do this lol
    if re.fullmatch(r"<?[@#]?!?\d+>?", content):
        result = ""
        for char in content:
            if char in ("<", "@", "#", "!", ">"):
                continue
            result += char
        return int(result)
    raise command_client.CommandError("Invalid mention or ID supplied.")


class ReturnErrorStr:
    __slots__ = ("errors", "error_responses", "final_error")

    def __init__(
        self,
        errors: typing.Sequence[BaseException],
        errors_responses: typing.Optional[typing.MutableMapping[BaseException, str]] = None,
    ) -> None:
        #    if isinstance(errors, BaseException):
        #        errors = (errors, )
        self.errors: typing.Sequence[BaseException] = errors
        self.error_responses: typing.Optional[typing.MutableMapping[BaseException, str]] = errors_responses

    def __enter__(self):
        ...

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type in self.errors:
            raise command_client.CommandError(
                (self.error_responses or containers.EMPTY_DICT).get(exc_type)
                or str(getattr(exc_val, "message", exc_val))
            )  # f"{exc_type.__name__}: {exc_val}"


def return_error_str(
    errors: typing.Union[BaseException, typing.Sequence[BaseException]],
    errors_responses: typing.Optional[typing.MutableMapping[BaseException, str]] = None,
):
    def decorator(func: aio.CoroutineFunctionT):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> typing.Optional[str]:
            try:
                return await func(*args, **kwargs)
            except errors as exc:
                raise command_client.CommandError(
                    (errors_responses or containers.EMPTY_DICT).get(type(exc)) or str(getattr(exc, "message", exc))
                )

        return wrapper

    return decorator
