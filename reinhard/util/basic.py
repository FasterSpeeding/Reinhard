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


def raise_command_error(message: str, /) -> typing.Callable[[typing.Any], typing.NoReturn]:
    def raise_command_error_(_: typing.Any) -> typing.NoReturn:
        raise errors.CommandError(message) from None

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
            raise errors.CommandError(
                (self.error_responses or {}).get(exc_type) or str(getattr(exc_val, "message", exc_val))
            )  # f"{exc_type.__name__}: {exc_val}"


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


def grid_permissions(permissions: enum.IntFlag) -> str:
    max_lens = [-1, -1]
    rows = []
    colomn = []
    for index, name in enumerate(permissions):
        colomn.append(name)
        if index % 2 != 0:
            rows.append(colomn)
        if len(name) > max_lens[index % 2]:
            max_lens[index % 2] = len(name)
    if colomn:
        colomn.append("")
        rows.append(colomn)

    for index in range(len(max_lens)):
        max_lens[index] += 2

    return "\n".join(
        f"{first.ljust(max_lens[0])} | {second.ljust(max_lens[1])}" for first in rows[0] for second in rows[1]
    )


def basic_name_grid(flags: enum.IntFlag) -> str:
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
