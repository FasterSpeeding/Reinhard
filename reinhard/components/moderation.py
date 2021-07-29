from __future__ import annotations

__all__: list[str] = ["moderation_component", "load_component"]

import datetime
from collections import abc as collections

import hikari
import tanjun
from yuyo import backoff

from ..util import help as help_util
from ..util import rest_manager

MAX_MESSAGE_BULK_DELETE = datetime.timedelta(weeks=2)


moderation_component = tanjun.Component(strict=True)
help_util.with_docs(moderation_component, "Moderation commands", "Moderation oriented commands.")


@moderation_component.with_message_command
@tanjun.with_own_permission_check(
    hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)
@tanjun.with_author_permission_check(
    hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)
@tanjun.with_option("suppress", "-s", "--suppress", converters=bool, default=False, empty_value=True)
@tanjun.with_option("after", "--after", converters=hikari.Snowflake, default=None)
@tanjun.with_option("before", "--before", converters=hikari.Snowflake, default=None)
@tanjun.with_option("bot_only", "--bot", converters=bool, default=False, empty_value=True)
@tanjun.with_option("human_only", "--human", converters=bool, default=False, empty_value=True)
@tanjun.with_multi_option("users", "--user", converters=hikari.Snowflake, default=())
@tanjun.with_argument("count", converters=int, default=None)
@tanjun.with_parser
@tanjun.as_message_command("clear")
async def clear_command(
    ctx: tanjun.traits.MessageContext,
    count: int | None,
    after: hikari.Snowflake | None,
    before: hikari.Snowflake | None,
    bot_only: bool,
    human_only: bool,
    users: collections.Sequence[hikari.Snowflake],
    suppress: bool,
) -> None:
    """Clear new messages from chat.

    !!! note
        This can only be used on messages under 14 days old.

    Arguments:
        * count: The amount of messages to delete.

    Options:
        * users (--user): Mentions and/or IDs of the users to delete messages from.
        * human only (--human): Whether this should only delete messages sent by actual users.
            This defaults to false and will be set to true if provided without a value.
        * bot only (--bot): Whether this should only delete messages sent by bots and webhooks.
        * before  (--before): ID of a message to delete messages which were sent before.
        * after (--after): ID of a message to delete messages which were sent after.
        * suppress (-s, --suppress): Provided without a value to stop the bot from sending a message once the
            command's finished.
    """
    if human_only and bot_only:
        raise tanjun.CommandError("Can only specify one of `--human` or `--user`")

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    after_too_old = after and now - after.created_at >= MAX_MESSAGE_BULK_DELETE
    before_too_old = before and now - before.created_at >= MAX_MESSAGE_BULK_DELETE

    if after_too_old or before_too_old:
        raise tanjun.CommandError("Cannot delete messages that are over 14 days old")

    if count is None and after is not None:
        raise tanjun.CommandError("Must specify `count` when `after` is not specified")

    elif count is not None and count <= 0:
        raise tanjun.CommandError("Count must be greater than 0.")

    if before is None and after is None:
        before = ctx.message.id

    iterator = ctx.rest.fetch_messages(
        ctx.channel_id,
        before=hikari.UNDEFINED if before is None else before,
        after=(hikari.UNDEFINED if after is None else after) if before is None else hikari.UNDEFINED,
    ).filter(lambda message: now - message.created_at < MAX_MESSAGE_BULK_DELETE)

    if before and after:
        iterator = iterator.filter(lambda message: message.id > after)  # type: ignore[operator]

    if human_only:
        iterator = iterator.filter(lambda message: not message.author.is_bot)

    elif bot_only:
        iterator = iterator.filter(lambda message: message.author.is_bot)

    if users:
        iterator = iterator.filter(lambda message: message.author.id in users)

    # TODO: Should we limit count or at least default it to something other than no limit?
    if count:
        iterator = iterator.limit(count)

    iterator = iterator.map(lambda x: x.id).chunk(100)
    retry = backoff.Backoff(max_retries=5)
    error_manager = rest_manager.HikariErrorManager(retry, break_on=(hikari.NotFoundError, hikari.ForbiddenError))

    with error_manager:
        async for messages in iterator:
            retry.reset()
            async for _ in retry:
                await ctx.rest.delete_messages(ctx.channel_id, *messages)
                break

    if not suppress:
        await error_manager.try_respond(ctx, content="Cleared messages.")


@tanjun.as_loader
def load_component(cli: tanjun.traits.Client, /) -> None:
    cli.add_component(moderation_component.copy())
