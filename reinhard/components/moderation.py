from __future__ import annotations

__all__: typing.Sequence[str] = ["ModerationComponent"]

import datetime
import typing

from hikari import errors as hikari_errors
from hikari import permissions
from hikari import snowflakes
from hikari import undefined
from tanjun import checks as checks_
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import parsing
from yuyo import backoff

from ..util import rest_manager

if typing.TYPE_CHECKING:
    from tanjun import traits as tanjun_traits

MAX_MESSAGE_BULK_DELETE = datetime.timedelta(weeks=2)


class ModerationComponent(components.Component):
    __slots__: typing.Sequence[str] = ()

    @checks_.with_own_permission_check(
        permissions.Permissions.MANAGE_MESSAGES
        | permissions.Permissions.VIEW_CHANNEL
        | permissions.Permissions.READ_MESSAGE_HISTORY
    )
    @checks_.with_author_permission_check(
        permissions.Permissions.MANAGE_MESSAGES
        | permissions.Permissions.VIEW_CHANNEL
        | permissions.Permissions.READ_MESSAGE_HISTORY
    )
    @parsing.with_option("suppress", "-s", "--suppress", converters=bool, default=False, empty_value=True)
    @parsing.with_option("after", "--after", converters=snowflakes.Snowflake, default=None)
    @parsing.with_option("before", "--before", converters=snowflakes.Snowflake, default=None)
    @parsing.with_option("bot_only", "--bot", converters=bool, default=False, empty_value=True)
    @parsing.with_option("human_only", "--human", converters=bool, default=False, empty_value=True)
    @parsing.with_multi_option("users", "--user", converters=snowflakes.Snowflake, default=())
    @parsing.with_argument("count", converters=int, default=None)
    @parsing.with_parser
    @components.as_command("clear")
    async def clear(
        self,
        ctx: tanjun_traits.Context,
        count: typing.Optional[int],
        after: typing.Optional[snowflakes.Snowflake],
        before: typing.Optional[snowflakes.Snowflake],
        bot_only: bool,
        human_only: bool,
        users: typing.Sequence[snowflakes.Snowflake],
        suppress: bool,
    ) -> None:
        if human_only and bot_only:
            raise tanjun_errors.CommandError("Can only specify one of `--human` or `--user`")

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        after_too_old = after and now - after.created_at >= MAX_MESSAGE_BULK_DELETE
        before_too_old = before and now - before.created_at >= MAX_MESSAGE_BULK_DELETE

        if after_too_old or before_too_old:
            raise tanjun_errors.CommandError("Cannot delete messages that are over 14 days old")

        if count is None and not after:
            raise tanjun_errors.CommandError("Must specify `count` when `after` is not specified")

        elif count and count <= 0:
            raise tanjun_errors.CommandError("Count must be greater than 0.")

        if not before and not after:
            before = ctx.message.id

        iterator = ctx.rest_service.rest.fetch_messages(
            ctx.message.channel_id,
            before=before or undefined.UNDEFINED,
            after=(after or undefined.UNDEFINED) if before is None else undefined.UNDEFINED,
        ).filter(lambda message: now - message.created_at < MAX_MESSAGE_BULK_DELETE)

        if before and after:
            iterator = iterator.filter(lambda message: message.id > after)

        if human_only:
            iterator = iterator.filter(lambda message: not message.author.is_bot)

        elif bot_only:
            iterator = iterator.filter(lambda message: message.author.is_bot)

        if users:
            iterator = iterator.filter(lambda message: message.author.id in users)

        # TODO: Should we limit count for after pagination?
        if count:
            iterator = iterator.limit(count)

        iterator = iterator.map(lambda x: x.id)
        iterator = iterator.chunk(100)

        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
        )

        with error_manager:
            async for messages in iterator:
                retry.reset()
                async for _ in retry:
                    await ctx.rest_service.rest.delete_messages(ctx.message.channel_id, *messages)
                    break

        if not suppress:
            await error_manager.try_respond(ctx, content="Cleared messages.")
