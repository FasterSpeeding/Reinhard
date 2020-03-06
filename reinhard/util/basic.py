import functools
import re
import typing


from reinhard.util import command_client


from hikari.internal_utilities import aio
from hikari.internal_utilities import containers
from hikari.orm.models import members as _members
from hikari.orm.models import permissions as _permissions


class CommandErrorRelay:
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


def command_error_relay(
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


async def get_permissions(ctx: command_client.Context) -> _permissions.Permission:
    if not (channel := ctx.message.channel):
        channel = await ctx.fabric.http_adapter.fetch_channel(ctx.message.channel_id)
    if not (guild := channel.guild):
        guild = await ctx.fabric.http_adapter.fetch_guild(ctx.message.guild)

    if channel.guild_id and ctx.message.author.id != guild.owner_id:
        permissions = ctx.message.guild.roles[ctx.message.guild_id].permissions

        if isinstance(ctx.message.author, _members.Member):
            author = ctx.message.author
        else:
            author = guild.members.get(ctx.message.author.id) or await ctx.fabric.http_adapter.fetch_member(
                ctx.message.author, guild
            )

        for role in author.roles:
            permissions += role.permissions

        if overwrite := channel.permission_overwrites[author.id]:
            permissions += overwrite.allow
            permissions -= overwrite.deny
    else:
        permissions = _permissions.Permission.ADMINISTRATOR
    return permissions
