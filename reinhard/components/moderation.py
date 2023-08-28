# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2023, Faster Speeding
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

__all__: list[str] = ["load_moderation"]

import asyncio
import dataclasses
import datetime
import re
import typing
from collections import abc as collections
from typing import Annotated

import hikari
import tanjun
import typing_extensions
from tanchan import doc_parse
from tanjun.annotations import Bool
from tanjun.annotations import Converted
from tanjun.annotations import Flag
from tanjun.annotations import Int
from tanjun.annotations import Ranged
from tanjun.annotations import Snowflake
from tanchan.components import buttons

if typing.TYPE_CHECKING:
    from typing_extensions import Self

MAX_MESSAGE_BULK_DELETE = datetime.timedelta(weeks=2) - datetime.timedelta(minutes=2)


def iter_messages(
    ctx: tanjun.abc.Context,
    count: int | None = None,
    after: hikari.Snowflake | None = None,
    before: hikari.Snowflake | None = None,
    bot_only: bool = False,
    human_only: bool = False,
    has_attachments: bool = False,
    has_embeds: bool = False,
    regex: re.Pattern[str] | None = None,
    users: collections.Collection[hikari.Snowflake] | None = None,
) -> hikari.LazyIterator[hikari.Message]:
    if human_only and bot_only:
        raise tanjun.CommandError(
            "Can only specify one of `human_only` or `user_only`", component=buttons.delete_row(ctx)
        )

    if count is None and after is None:
        raise tanjun.CommandError(
            "Must specify `count` when `after` is not specified", component=buttons.delete_row(ctx)
        )

    elif count is not None and count <= 0:
        raise tanjun.CommandError("Count must be greater than 0.", component=buttons.delete_row(ctx))

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
            raise tanjun.CommandError("Must specify at least one user.", component=buttons.delete_row(ctx))

        iterator = iterator.filter(lambda message: message.author.id in users)

    # TODO: Should we limit count or at least default it to something other than no limit?
    if count:
        iterator = iterator.limit(count)

    return iterator


class _IterMessageOptions(typing.TypedDict, total=False):
    """Options used for iterating over messages.

    Parameters
    ----------
    count
        The amount of entities to target.
    regex
        A regular expression to match against message contents.
    has_embeds
        Whether this should only target messages which have embeds.
    has_attachments
        Whether this should only delete messages which have attachments.
    human_only
        Whether this should only target messages sent by actual users.
    bot_only
        Whether this should only target messages sent by bots and webhooks.
    before
        Target messages sent before this message.
    after
        Target messages sent after this message.
    """

    count: Annotated[Int, Flag(aliases=["-c"])]
    regex: Annotated[re.Pattern[str], Converted(re.compile), Flag(aliases=["-r"])]
    has_embeds: Bool
    has_attachments: Bool
    human_only: Bool
    bot_only: Bool
    before: Snowflake
    after: Snowflake


def _now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


_CLEAR_PERMS = (
    hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
)


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.with_own_permission_check(_CLEAR_PERMS, follow_wrapped=True)
@tanjun.with_author_permission_check(_CLEAR_PERMS, follow_wrapped=True)
@tanjun.with_multi_option("users", "--user", "-u", converters=tanjun.conversion.parse_user_id, default=())
@tanjun.as_message_command("clear")
@tanjun.with_str_slash_option(
    "users",
    "Users to delete messages for",
    converters=lambda value: list(map(tanjun.conversion.parse_user_id, value.split())),
    default=None,
)
@doc_parse.as_slash_command(default_member_permissions=_CLEAR_PERMS, dm_enabled=False)
async def clear(
    ctx: tanjun.abc.Context,
    users: collections.Collection[hikari.Snowflake] | None,
    **kwargs: typing_extensions.Unpack[_IterMessageOptions],
) -> None:
    """Clear new messages from chat as a moderator.

    !!! note
        This can only be used on messages under 14 days old.
    """
    now = _now()
    after_too_old = (after := kwargs.get("after")) and now - after.created_at >= MAX_MESSAGE_BULK_DELETE
    before_too_old = (before := kwargs.get("before")) and now - before.created_at >= MAX_MESSAGE_BULK_DELETE

    if after_too_old or before_too_old:
        raise tanjun.CommandError("Cannot delete messages that are over 14 days old", component=buttons.delete_row(ctx))

    iterator = (
        iter_messages(ctx, **kwargs, users=users)
        .take_while(lambda message: _now() - message.created_at < MAX_MESSAGE_BULK_DELETE)
        .map(lambda x: x.id)
        .chunk(100)
    )

    await ctx.respond("Starting message deletes", component=buttons.delete_row(ctx))
    async for messages in iterator:
        await ctx.rest.delete_messages(ctx.channel_id, *messages)
        break

    try:
        await ctx.edit_last_response(content="Cleared messages.", component=buttons.delete_row(ctx), delete_after=2)
    except hikari.NotFoundError:
        await ctx.respond(content="Cleared messages.", component=buttons.delete_row(ctx), delete_after=2)


ban_group = (
    doc_parse.slash_command_group(
        "ban", "Ban commands", default_member_permissions=hikari.Permissions.BAN_MEMBERS, dm_enabled=False
    )
    .add_check(tanjun.checks.GuildCheck())
    .add_check(tanjun.checks.AuthorPermissionCheck(hikari.Permissions.BAN_MEMBERS))
    .add_check(tanjun.checks.OwnPermissionCheck(hikari.Permissions.BAN_MEMBERS))
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
    # joined_after:
    members_only: bool
    roles: collections.Mapping[hikari.Snowflake, hikari.Role]
    passed: set[hikari.Snowflake] = dataclasses.field(default_factory=set)
    failed: dict[hikari.Snowflake, str] = dataclasses.field(default_factory=dict)

    @classmethod
    async def build(cls, ctx: tanjun.abc.Context, reason: str, delete_message_days: int, members_only: bool) -> Self:
        assert ctx.member is not None

        guild = ctx.get_guild() or await ctx.fetch_guild()
        assert guild is not None
        is_owner = ctx.member.id == guild.owner_id

        if not ctx.member.role_ids and not is_owner:
            # If they have no role and aren't the guild owner then the role
            # hierarchy would never let them ban anyone.
            raise tanjun.CommandError("You cannot ban any of these members", component=buttons.delete_row(ctx))

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
            await self.guild.ban(
                target, reason=self.reason, delete_message_seconds=datetime.timedelta(days=self.delete_message_days)
            )

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


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_author_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_own_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_multi_argument("users", converters=tanjun.conversion.parse_user_id)
@tanjun.as_message_command("ban members")
@tanjun.with_str_slash_option(
    "users",
    "Space separated sequence of users to ban",
    converters=lambda value: set(map(tanjun.conversion.parse_user_id, value.split())),
)
@ban_group.as_sub_command("members")
async def multi_ban_command(
    ctx: tanjun.abc.SlashContext | tanjun.abc.MessageContext,
    users: collections.Collection[hikari.Snowflake],
    clear_message_days: Annotated[Int, Ranged(0, 7), Flag(aliases=["--clear", "-c"])] = 0,
    members_only: Annotated[Bool, Flag(empty_value=True, aliases=["-m"])] = False,
) -> None:
    """Ban one or more members.

    Parameters
    ----------
    clear_message_days
        Number of days to clear their recent messages for.
    members_only
        Only ban users who are currently in the guild.
    """
    banner = await _MultiBanner.build(
        ctx,
        reason=f"Bulk ban triggered by {ctx.author.username}#{ctx.author.discriminator} ({ctx.author.id})",
        delete_message_days=clear_message_days,
        members_only=members_only,
    )
    await ctx.respond("Starting bans \N{THUMBS UP SIGN}", component=buttons.delete_row(ctx), delete_after=2)
    await asyncio.gather(*(banner.try_ban(target=user) for user in users))
    content, attachment = banner.make_response()
    await ctx.respond(content, attachment=attachment, component=buttons.delete_row(ctx))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_author_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_own_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.as_message_command("ban authors")
@ban_group.as_sub_command("authors")
async def ban_authors_command(
    ctx: tanjun.abc.Context,
    clear_message_days: Annotated[Int, Ranged(0, 7), Flag(aliases=["-c"])] = 0,
    members_only: Annotated[Bool, Flag(empty_value=True, aliases=["-m"])] = False,
    **kwargs: typing_extensions.Unpack[_IterMessageOptions],
) -> None:
    """Ban the authors of recent messages.

    Parameters
    ----------
    clear_message_days
        Number of days to clear their recent messages for.
    members_only
        Only ban users who are currently in the guild.
    """
    found_authors = set[hikari.Snowflake]()
    banner = await _MultiBanner.build(
        ctx,
        reason=f"Bulk ban triggered by {ctx.author.username}#{ctx.author.discriminator} ({ctx.author.id})",
        delete_message_days=clear_message_days,
        members_only=members_only,
    )
    authors = (
        iter_messages(ctx, **kwargs, users=None)
        .map(lambda message: message.author.id)
        .filter(lambda author: author not in found_authors)
    )

    await ctx.respond("Starting bans \N{THUMBS UP SIGN}", component=buttons.delete_row(ctx), delete_after=2)
    async for author in authors:
        found_authors.add(author)
        await banner.try_ban(author)

    content, attachment = banner.make_response()
    await ctx.respond(content, attachment=attachment, component=buttons.delete_row(ctx))


load_moderation = (
    tanjun.Component(name="moderation")
    .set_dms_enabled_for_app_cmds(False)
    .set_default_app_command_permissions(hikari.Permissions.ADMINISTRATOR)
    .load_from_scope()
    .make_loader()
)
