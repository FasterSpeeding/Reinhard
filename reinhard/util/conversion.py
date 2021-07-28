from __future__ import annotations

__all__: list[str] = [
    "RESTFulMemberConverter",
    "RESTFulRoleConverter",
    "RESTFulUserConverter",
    # tanjun.conversion
    "ChannelConverter",
    "ColorConverter",
    "EmojiConverter",
    "GuildConverter",
    "InviteConverter",
    "MemberConverter",
    "PresenceConverter",
    "RoleConverter",
    "SnowflakeConverter",
    "UserConverter",
    "VoiceStateConverter",
]

import hikari
import tanjun
from tanjun.conversion import *
from yuyo import backoff

from ..util import basic
from ..util import rest_manager


class RESTFulMemberConverter(MemberConverter):
    __slots__ = ()

    @property
    def cache_bound(self) -> bool:
        return False

    async def convert(self, ctx: tanjun.traits.Context, argument: str, /) -> hikari.Member:
        if ctx.guild_id is None:
            raise ValueError("Cannot get a member from a DM channel")

        try:
            # Always try the cache first.
            return await super().convert(ctx, argument)
        except ValueError:
            pass

        member_id: hikari.Snowflake | None = None
        try:
            member_id = tanjun.conversion.parse_user_id(argument)
        except ValueError:
            pass

        retry = backoff.Backoff(max_retries=5)
        error_manager = (
            rest_manager.HikariErrorManager(retry).with_rule(
                # We catch a IndexError for search_members where a dynamic length list is returned.
                (hikari.BadRequestError, hikari.NotFoundError, IndexError),
                basic.raise_error("Couldn't find member.", error_type=ValueError),
            )
            # If this is the case then we can't access the guild this was triggered in anymore and should stop the
            # command from trying to execute without replying.
            .with_rule((hikari.ForbiddenError,), basic.raise_error(None))
        )

        async for _ in retry:
            with error_manager:
                # Get by ID if we were provided a valid ID.
                if member_id is not None:
                    return await ctx.rest.fetch_member(ctx.guild_id, member_id)

                # Else get by username/nickname.
                else:
                    return (await ctx.rest.search_members(ctx.guild_id, argument))[0]

        else:
            raise ValueError("Couldn't get member in time") from None


class RESTFulRoleConverter(RoleConverter):
    __slots__ = ()

    @property
    def cache_bound(self) -> bool:
        return False

    async def convert(self, ctx: tanjun.traits.Context, argument: str, /) -> hikari.Role:
        # This is more strict than RoleConverter but having it consistently reject DM channels is preferable over it
        # rejecting DM channels once it fails to find anything in the cache.
        if ctx.guild_id is None:
            raise ValueError("Cannot get a role from a DM channel")

        try:
            # Always try the cache first.
            return await super().convert(ctx, argument)
        except ValueError:
            pass

        # Match by ID if we were provided a valid ID.
        try:
            role_id = tanjun.conversion.parse_role_id(argument)

            def predicate(role: hikari.Role) -> bool:
                return role.id == role_id

        # Else match by name.
        except ValueError:
            argument = argument.casefold()

            def predicate(role: hikari.Role) -> bool:
                return role.name.casefold() == argument

        retry = backoff.Backoff(max_retries=5)
        error_manager = (
            rest_manager.HikariErrorManager(retry).with_rule(
                # next(...) will raise StopIteration if the iterator feed to it doesn't yield anything.
                (hikari.BadRequestError, hikari.NotFoundError, StopIteration),
                basic.raise_error("Couldn't find role.", error_type=ValueError),
            )
            # If this is the case then we can't access the guild this was triggered in anymore and should stop the
            # command from trying to execute without replying.
            .with_rule((hikari.ForbiddenError,), basic.raise_error(None))
        )

        async for _ in retry:
            with error_manager:
                roles = await ctx.rest.fetch_roles(ctx.guild_id)
                return next(filter(predicate, iter(roles)))

        else:
            raise ValueError("Couldn't fetch user in time.")


class RESTFulUserConverter(UserConverter):
    __slots__ = ()

    @property
    def cache_bound(self) -> bool:
        return False

    async def convert(self, ctx: tanjun.traits.Context, argument: str, /) -> hikari.User:
        try:
            # Always try the cache first.
            return await super().convert(ctx, argument)
        except ValueError:
            pass

        user_id = tanjun.conversion.parse_user_id(argument, message="No valid user mention or ID found")

        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(retry).with_rule(
            (hikari.BadRequestError, hikari.NotFoundError),
            basic.raise_error("Couldn't find user.", error_type=ValueError),
        )

        async for _ in retry:
            with error_manager:
                return await ctx.rest.fetch_user(user_id)

        else:
            raise ValueError("Couldn't fetch user in time.")
