from __future__ import annotations

import enum
import functools
import typing

from tanjun import errors

if typing.TYPE_CHECKING:
    import datetime
    import types


def pretify_date(date: datetime.datetime) -> str:
    return date.strftime("%a %d %b %Y %H:%M:%S %Z")


class _ErrorRaiserT(typing.Protocol):
    def __call__(self, arg: typing.Any = None, /) -> typing.NoReturn:
        raise NotImplementedError


def raise_error(
    message: typing.Optional[str], /, error_type: typing.Type[BaseException] = errors.CommandError
) -> _ErrorRaiserT:  # TODO: better typing for the callable return
    def raise_command_error_(_: typing.Any = None) -> typing.NoReturn:
        if message:
            raise error_type(message) from None

        raise error_type from None

    return raise_command_error_


class CommandErrorRelay:
    __slots__ = ("errors", "error_responses", "final_error")

    def __init__(
        self,
        _errors: typing.Tuple[typing.Type[BaseException], ...],
        errors_responses: typing.Optional[typing.MutableMapping[typing.Type[BaseException], str]] = None,
    ) -> None:
        # if isinstance(errors, BaseException):
        #    errors = [errors]
        self.errors: typing.Tuple[typing.Type[BaseException], ...] = _errors
        self.error_responses: typing.Optional[typing.MutableMapping[typing.Type[BaseException], str]] = errors_responses

    def __enter__(self) -> None:
        ...

    def __exit__(
        self,
        exc_type: typing.Optional[typing.Type[BaseException]],
        exc_val: typing.Optional[BaseException],
        exc_tb: typing.Optional[types.TracebackType],
    ) -> None:
        if exc_type in self.errors:
            response: typing.Optional[str] = None
            if self.error_responses:
                response = self.error_responses.get(exc_type)

            raise errors.CommandError(
                response or str(getattr(exc_val, "message", exc_val))
            ) from None  # f"{exc_type.__name__}: {exc_val}"


# TODO: fix typing
def command_error_relay(
    errors_: typing.Union[BaseException, typing.Tuple[typing.Type[BaseException], ...]],
    errors_responses: typing.Optional[typing.MutableMapping[typing.Type[BaseException], str]] = None,
) -> typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, typing.Any]]:
    def decorator(func: typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, typing.Any]]):
        @functools.wraps(func)
        async def wrapper(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
            try:
                return await func(*args, **kwargs)
            except errors_ as exc:
                raise errors.CommandError((errors_responses or {}).get(type(exc)) or str(getattr(exc, "message", exc)))

        return wrapper

    return decorator


def basic_name_grid(flags: enum.IntFlag) -> str:  # TODO: actually deal with max len lol
    names = [name for name, flag in type(flags).__members__.items() if flag != 0 and (flag & flags) == flag]
    names.sort()
    if not names:
        return ""

    name_grid = []
    line = ""
    for name in names:
        if line:
            name_grid.append(f"`{line}`, `{name}`,")
            line = ""
        else:
            line = name

    if line:
        name_grid.append(f"`{line}`")

    name_grid[-1] = name_grid[-1].strip(",")
    return "\n".join(name_grid)
