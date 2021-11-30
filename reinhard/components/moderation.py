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

__all__: list[str] = ["moderation_loader"]

import asyncio
import dataclasses
import datetime
import re
import typing
from collections import abc as collections

import hikari
import tanjun

from .. import utility

MAX_MESSAGE_BULK_DELETE = datetime.timedelta(weeks=2) - datetime.timedelta(minutes=2)
_MessageCommandT = typing.TypeVar("_MessageCommandT", bound=tanjun.MessageCommand[typing.Any])
_SlashCommandT = typing.TypeVar("_SlashCommandT", bound=tanjun.SlashCommand[typing.Any])


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
    if human_only and bot_only:
        # TODO: delete row
        raise tanjun.CommandError("Can only specify one of `human_only` or `user_only`")

    if count is None and after is None:
        # TODO: delete row
        raise tanjun.CommandError("Must specify `count` when `after` is not specified")

    elif count is not None and count <= 0:
        # TODO: delete row
        raise tanjun.CommandError("Count must be greater than 0.")

    if before is None and after is None:
        before = hikari.Snowflake.from_datetime(ctx.created_at)

    if before is not None and after is not None:
        iterator = ctx.rest.fetch_messages(ctx.channel_id, before=before).take_while(lambda message: message.id > after)

    else:
        iterator = ctx.rest.fetch_messages(
            ctx.channel_id,
            before=hikari.UNDEFINED if before is None else before,
            after=hikari.UNDEFINED if after is None else after,
        )

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
            # TODO: delete row
            raise tanjun.CommandError("Must specify at least one user.")

        iterator = iterator.filter(lambda message: message.author.id in users)

    # TODO: Should we limit count or at least default it to something other than no limit?
    if count:
        iterator = iterator.limit(count)

    return iterator


def _with_filter_slash_options(command: _SlashCommandT, /) -> _SlashCommandT:
    return (
        command.add_int_option("count", "The amount of entities to target.", default=None)  # TODO: max, min
        .add_str_option(
            "regex", "A regular expression to match against message contents.", converters=re.compile, default=None
        )
        .add_bool_option("has_embeds", "Whether this should only target messages which have embeds.", default=False)
        .add_bool_option(
            "has_attachments", "Whether this should only delete messages which have attachments.", default=False
        )
        .add_bool_option("human_only", "Whether this should only target messages sent by actual users.", default=False)
        .add_bool_option(
            "bot_only", "Whether this should only target messages sent by bots and webhooks.", default=False
        )
        .add_str_option(
            "before", "Target messages sent before this message.", converters=tanjun.to_snowflake, default=None
        )
        .add_str_option(
            "after", "Target messages sent after this message.", converters=tanjun.to_snowflake, default=None
        )
    )


def _with_filter_message_options(command: _MessageCommandT, /) -> _MessageCommandT:
    return command.set_parser(
        tanjun.ShlexParser()
        .add_option("count", "-c", "--count", converters=int, default=None)
        .add_option("regex", "-r", "--regex", converters=re.compile, default=None)
        .add_option("has_embeds", "-e", "--has-embeds", default=False, converters=tanjun.to_bool, empty_value=True)
        .add_option(
            "has_attachments", "-a", "--has-attachments", default=False, converters=tanjun.to_bool, empty_value=True
        )
        .add_option("human_only", "-u", "--human-only", default=False, converters=tanjun.to_bool, empty_value=True)
        .add_option("bot_only", "-b", "--bot-only", default=False, converters=tanjun.to_bool, empty_value=True)
        .add_option("before", "-B", "--before", converters=tanjun.to_snowflake, default=None)
        .add_option("after", "-A", "--after", converters=tanjun.to_snowflake, default=None)
    )


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


_CLEAR_PERMS = (
    hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)


@tanjun.with_own_permission_check(_CLEAR_PERMS)
@tanjun.with_author_permission_check(_CLEAR_PERMS)
@tanjun.with_multi_option("users", "--user", "-u", converters=tanjun.parse_user_id, default=())
@_with_filter_message_options
@tanjun.as_message_command("clear")
@tanjun.with_own_permission_check(_CLEAR_PERMS)
@tanjun.with_author_permission_check(_CLEAR_PERMS)
@tanjun.with_str_slash_option(
    "users",
    "Users to delete messages for",
    converters=lambda value: list(map(tanjun.conversion.parse_user_id, value.split())),
    default=None,
)
@_with_filter_slash_options
@tanjun.as_slash_command("clear", "Clear new messages from chat as a moderator.")
async def clear_command(
    ctx: tanjun.abc.Context, after: hikari.Snowflake | None, before: hikari.Snowflake | None, **kwargs: typing.Any
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
    now = _now()
    after_too_old = after and now - after.created_at >= MAX_MESSAGE_BULK_DELETE
    before_too_old = before and now - before.created_at >= MAX_MESSAGE_BULK_DELETE

    if after_too_old or before_too_old:
        # TODO: delete row
        raise tanjun.CommandError("Cannot delete messages that are over 14 days old")

    iterator = (
        iter_messages(ctx, after=after, before=before, **kwargs)
        .take_while(lambda message: _now() - message.created_at < MAX_MESSAGE_BULK_DELETE)
        .map(lambda x: x.id)
        .chunk(100)
    )

    await ctx.respond("Starting message deletes", component=utility.delete_row(ctx))
    async for messages in iterator:
        await ctx.rest.delete_messages(ctx.channel_id, *messages)
        break

    try:
        await ctx.edit_last_response(content="Cleared messages.", component=utility.delete_row(ctx), delete_after=2)
    except hikari.NotFoundError:
        await ctx.respond(content="Cleared messages.", component=utility.delete_row(ctx), delete_after=2)


ban_group = (
    tanjun.slash_command_group("ban", "Ban commands")
    .add_check(tanjun.GuildCheck())
    .add_check(tanjun.AuthorPermissionCheck(hikari.Permissions.BAN_MEMBERS))
    .add_check(tanjun.OwnPermissionCheck(hikari.Permissions.BAN_MEMBERS))
)


def get_top_role(
    role_ids: collections.Sequence[hikari.Snowflake], roles: collections.Mapping[hikari.Snowflake, hikari.Role]
) -> hikari.Role | None:
    try:
        next(iter(sorted(((role.position, role) for role in map(roles.get, role_ids) if role), reverse=True)))[1]

    except StopIteration:
        return None


@dataclasses.dataclass(slots=True)
class _MultiBanner:
    ctx: tanjun.abc.Context
    reason: str
    author_role_position: int
    author_is_guild_owner: bool
    guild: hikari.Guild
    delete_message_days: int
    members_only: bool
    roles: collections.Mapping[hikari.Snowflake, hikari.Role]
    passed: set[hikari.Snowflake] = dataclasses.field(default_factory=set)
    failed: dict[hikari.Snowflake, str] = dataclasses.field(default_factory=dict)

    @classmethod
    async def build(
        cls, ctx: tanjun.abc.Context, reason: str, delete_message_days: int, members_only: bool
    ) -> _MultiBanner:
        assert ctx.member is not None

        guild = ctx.get_guild() or await ctx.fetch_guild()
        assert guild is not None
        is_owner = ctx.member.id == guild.owner_id

        if not ctx.member.role_ids and not is_owner:
            # If they have no role and aren't the guild owner then the role
            # hierarchy would never let them ban anyone.
            # TODO: delete row
            raise tanjun.CommandError("You cannot ban any of these members")

        if is_owner:
            # If the author is the owner then we don't actually check the role
            # hierarchy so dummy data can be safely used here.
            top_role_position = 999999
            roles: collections.Mapping[hikari.Snowflake, hikari.Role] = {}

        elif isinstance(guild, hikari.RESTGuild):
            roles = guild.roles
            top_role = get_top_role(ctx.member.role_ids, roles)
            top_role_position = top_role.position if top_role else 0

        else:
            roles = guild.get_roles() or {r.id: r for r in await guild.fetch_roles()}
            top_role = get_top_role(ctx.member.role_ids, roles)
            top_role_position = top_role.position if top_role else 0

        return cls(
            ctx=ctx,
            reason=reason,
            author_role_position=top_role_position,
            author_is_guild_owner=is_owner,
            guild=guild,
            delete_message_days=delete_message_days,
            members_only=members_only,
            roles=roles,
        )

    async def try_ban(self, target: hikari.Snowflake) -> None:
        if target == self.guild.owner_id:
            self.failed[target] = "Cannot ban the guild owner."
            return

        if target == self.ctx.author:
            self.failed[target] = "You cannot ban yourself."
            return

        # TODO: do we want to explicitly check to see if the bot can target them?

        # If this command was called by the guild owner and we aren't only banning
        # current members then we can avoid getting the target member's object
        # altogether.
        if not self.author_is_guild_owner or self.members_only:
            try:
                member = self.guild.get_member(target) or await self.ctx.rest.fetch_member(self.guild, target)

            except hikari.NotFoundError:
                member = None

            except Exception as exc:
                self.failed[target] = str(exc)
                return

            else:
                top_role = get_top_role(member.role_ids, self.roles)

                if not top_role or top_role.position >= self.author_role_position:
                    self.failed[target] = "User is higher than or equal to author's top role"
                    return

            if self.members_only and not member:
                self.failed[target] = "User is not a member of the guild"
                return

        try:
            await self.guild.ban(target, reason=self.reason, delete_message_days=self.delete_message_days)

        except Exception as exc:
            self.failed[target] = str(exc)

        else:
            self.passed.add(target)

    def make_response(self) -> tuple[str, hikari.UndefinedOr[hikari.Bytes]]:
        if self.failed and self.passed:
            page = "Failed bans:\n" + "\n".join(f"* {user_id}: {exc}" for user_id, exc in self.failed.items())
            return (
                f"Successfully banned {len(self.passed)} member(s) but failed to ban {len(self.failed)} member(s)",
                hikari.Bytes(page.encode(), "failed_bans.md", mimetype="text/markdown;charset=UTF-8"),
            )

        elif self.failed:
            page = "Failed bans:\n" + "\n".join(f"* {user_id}: {exc}" for user_id, exc in self.failed.items())
            return (
                f"Failed to ban {len(self.failed)} member(s)",
                hikari.Bytes(page.encode(), "failed_bans.md", mimetype="text/markdown;charset=UTF-8"),
            )

        elif self.passed:
            return f"Successfully banned {len(self.passed)} member(s)", hikari.UNDEFINED

        else:
            return "No members were banned", hikari.UNDEFINED


@tanjun.with_author_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_own_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_option("members_only", "--members-only", "-m", converters=tanjun.to_bool, default=False, empty_value=True)
@tanjun.with_option("clear_message_days", "--clear", "-c", converters=int, default=0)
@tanjun.with_multi_argument("members", converters=tanjun.parse_user_id)
@tanjun.as_message_command("ban members")
@ban_group.with_command
@tanjun.with_bool_slash_option("members_only", "Only ban users who are currently in the guild.", default=False)
# TODO: max, min
@tanjun.with_int_slash_option("clear_message_days", "Number of days to clear their recent messages for.", default=0)
@tanjun.with_str_slash_option(
    "users",
    "Space separated sequence of users to ban",
    converters=lambda value: set(map(tanjun.conversion.parse_user_id, value.split())),
)
@tanjun.as_slash_command("members", "Ban one or more members")
async def multi_ban_command(
    ctx: tanjun.abc.SlashContext, users: set[hikari.Snowflake], clear_message_days: int, members_only: bool
) -> None:
    """Ban multiple users from using the bot.

    Arguments:
        * users: Mentions and IDs of the users to ban.
    """
    banner = await _MultiBanner.build(
        ctx,
        reason=f"Bulk ban triggered by {ctx.author.username} ({ctx.author.id})",
        delete_message_days=clear_message_days,
        members_only=members_only,
    )
    await ctx.respond("Starting bans \N{THUMBS UP SIGN}", component=utility.delete_row(ctx), delete_after=2)
    await asyncio.gather(*(banner.try_ban(target=user) for user in users))
    content, attachment = banner.make_response()
    await ctx.create_followup(content, attachment=attachment, component=utility.delete_row(ctx))


@tanjun.with_author_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_own_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_option("members_only", "--members-only", "-m", converters=tanjun.to_bool, default=False, empty_value=True)
@tanjun.with_option("clear_message_days", "--clear", "-c", converters=int, default=0)
@_with_filter_message_options
@tanjun.as_message_command("ban authors")
@ban_group.with_command
@tanjun.with_bool_slash_option("members_only", "Only ban users who are currently in the guild.", default=False)
@tanjun.with_int_slash_option("clear_message_days", "Number of days to clear their recent messages for.", default=0)
@_with_filter_slash_options
@tanjun.as_slash_command("authors", "Ban the authors of recent messages.")
async def ban_authors_command(
    ctx: tanjun.abc.SlashContext, clear_message_days: int, members_only: bool, **kwargs: typing.Any
) -> None:
    found_authors = set[hikari.Snowflake]()
    banner = await _MultiBanner.build(
        ctx,
        reason=f"Bulk ban triggered by {ctx.author.username} ({ctx.author.id})",
        delete_message_days=clear_message_days,
        members_only=members_only,
    )
    authors = (
        iter_messages(ctx, **kwargs, users=None)
        .map(lambda message: message.author.id)
        .filter(lambda author: author not in found_authors)
    )

    await ctx.respond("Starting bans \N{THUMBS UP SIGN}", component=utility.delete_row(ctx), delete_after=2)
    async for author in authors:
        found_authors.add(author)
        await banner.try_ban(author)

    content, attachment = banner.make_response()
    await ctx.create_followup(content, attachment=attachment, component=utility.delete_row(ctx))


moderation_loader = tanjun.Component(name="moderation", strict=True).load_from_scope().make_loader()
