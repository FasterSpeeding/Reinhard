from __future__ import annotations

import typing

import attr
from hikari import errors as hikari_errors

if typing.TYPE_CHECKING:
    from hikari import permissions

    from reinhard.util import command_client


class CommandClientError(hikari_errors.HikariError):
    """A base for all command client errors."""


class CommandPermissionError(CommandClientError):  # TODO: better name and implement
    __slots__ = ("missing_permissions",)

    missing_permissions: permissions.Permission

    def __init__(
        self, required_permissions: permissions.Permission, actual_permissions: permissions.Permission
    ) -> None:
        pass
        # self.missing_permissions =
        # for permission in m


@attr.attrs(init=True, slots=True)
class CommandError(CommandClientError):

    response: str = attr.attrib()
    """The string response that the client should send in chat if it has send messages permission."""

    def __str__(self) -> str:
        return self.response


@attr.attrs(init=True, slots=True)
class FailedCheck(CommandClientError):
    checks: typing.Sequence[typing.Tuple[command_client.CheckLikeT, typing.Optional[BaseException]]] = attr.attrib()


@attr.attrs(init=True, repr=True, slots=True)
class ConversionError(CommandClientError):
    msg: str = attr.attrib()
    origins: typing.Sequence[BaseException] = attr.attrib(factory=list)

    def __str__(self) -> str:
        return self.msg
