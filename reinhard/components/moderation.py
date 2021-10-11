# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__: list[str] = ["moderation_component", "load_moderation"]

import asyncio
import datetime
import re
from collections import abc as collections

import hikari
import tanjun

MAX_MESSAGE_BULK_DELETE = datetime.timedelta(weeks=2)


moderation_component = tanjun.Component(name="moderation", strict=True)


def iter_messages(
    ctx: tanjun.abc.Context,
    count: int | None,
    after: hikari.Snowflake | None,
    before: hikari.Snowflake | None,
    bot_only: bool,
    human_only: bool,
    has_attachments: bool,
    has_embeds: bool,
    regex: re.Pattern[str] | None,
    users: collections.Collection[hikari.Snowflake] | None,
) -> hikari.LazyIterator[hikari.Message]:
    if count is None and after is not None:
        raise tanjun.CommandError("Must specify `count` when `after` is not specified")

    elif count is not None and count <= 0:
        raise tanjun.CommandError("Count must be greater than 0.")

    if before is None and after is None:
        before = hikari.Snowflake.from_datetime(ctx.created_at)

    iterator = ctx.rest.fetch_messages(
        ctx.channel_id,
        before=hikari.UNDEFINED if before is None else before,
        after=(hikari.UNDEFINED if after is None else after) if before is None else hikari.UNDEFINED,
    )

    if before and after:
        iterator = iterator.filter(lambda message: message.id > after)

    if human_only:
        iterator = iterator.filter(lambda message: not message.author.is_bot)

    elif bot_only:
        iterator = iterator.filter(lambda message: message.author.is_bot)

    if has_attachments:
        iterator = iterator.filter(lambda message: bool(message.attachments))

    if has_embeds:
        iterator = iterator.filter(lambda message: bool(message.embeds))

    if regex:
        iterator = iterator.filter(lambda message: bool(message.content and regex.match(message.content)))

    if users is not None:
        if not users:
            raise tanjun.CommandError("Must specify at least one user.")

        iterator = iterator.filter(lambda message: message.author.id in users)

    # TODO: Should we limit count or at least default it to something other than no limit?
    if count:
        iterator = iterator.limit(count)

    return iterator


@moderation_component.with_slash_command
@tanjun.with_own_permission_check(
    hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)
@tanjun.with_author_permission_check(
    hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)
@tanjun.with_str_slash_option(
    "after", "ID of a message to delete messages which were sent after.", converters=tanjun.to_snowflake, default=None
)
@tanjun.with_str_slash_option(
    "before", "ID of a message to delete messages which were sent before.", converters=tanjun.to_snowflake, default=None
)
@tanjun.with_bool_slash_option(
    "bot_only", "Whether this should only delete messages sent by bots and webhooks.", default=False
)
@tanjun.with_bool_slash_option(
    "human_only", "Whether this should only delete messages sent by actual users.", default=False
)
@tanjun.with_bool_slash_option(
    "has_attachments", "Whether this should only delete messages which have attachments.", default=False
)
@tanjun.with_bool_slash_option(
    "has_embeds", "Whether this should only delete messages which have embeds.", default=False
)
@tanjun.with_str_slash_option(
    "regex", "A regular expression to match against the message content.", converters=re.compile, default=None
)
@tanjun.with_str_slash_option(
    "users",
    "Users to delete messages for",
    converters=lambda value: map(tanjun.conversion.parse_user_id, value.split()),
    default=None,
)
@tanjun.with_int_slash_option("count", "The amount of messages to delete.", default=None)
@tanjun.as_slash_command("clear", "Clear new messages from chat as a moderator.")
async def clear_command(
    ctx: tanjun.abc.Context,
    count: int | None,
    after: hikari.Snowflake | None,
    before: hikari.Snowflake | None,
    bot_only: bool,
    human_only: bool,
    has_attachments: bool,
    has_embeds: bool,
    regex: re.Pattern[str] | None,
    users: collections.Collection[hikari.Snowflake] | None,
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

    iterator = (
        iter_messages(ctx, count, after, before, bot_only, human_only, has_attachments, has_embeds, regex, users)
        .filter(lambda message: now - message.created_at < MAX_MESSAGE_BULK_DELETE)
        .map(lambda x: x.id)
        .chunk(100)
    )

    async for messages in iterator:
        await ctx.rest.delete_messages(ctx.channel_id, *messages)
        break

    await ctx.respond(content="Cleared messages.")
    await asyncio.sleep(2)
    try:
        await ctx.delete_last_response()
    except hikari.NotFoundError:
        pass


@tanjun.as_loader
def load_moderation(cli: tanjun.abc.Client, /) -> None:
    cli.add_component(moderation_component.copy())
