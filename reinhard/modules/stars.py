from __future__ import annotations

import typing

import asyncpg
from hikari import channels as _channels
from hikari import errors
from hikari import messages as _messages
from hikari import embeds

import reinhard.util.errors
from reinhard.util import command_client
from reinhard.util import basic as util
from reinhard import sql


if typing.TYPE_CHECKING:
    from hikari import bases as _bases
    from hikari import users as _users


#  TODO: star status (e.g. deleted)
#  TODO: freeze stars when deleted?
#  TODO: handle sql errors?
#  TODO: starboard minimum count
#  TODO: state


exports = ["StarboardCluster"]

UNICODE_STAR = "\N{WHITE MEDIUM STAR}"


class StarboardCluster(command_client.CommandCluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sql_scripts = sql.CachedScripts(pattern=".*star.*")
        self.add_cluster_event(command_client.CommandEvents.ERROR, self.client.on_error)

    @staticmethod
    async def get_starboard_channel(
        guild: _bases.Snowflake, conn: asyncpg.connection
    ) -> typing.Optional[asyncpg.Record]:
        return await conn.fetchrow("SELECT * FROM StarboardChannels WHERE guild_id = $1;", guild)

    @staticmethod
    async def get_starboard_entry(
        message: _messages.MessageLikeT, conn: asyncpg.connection
    ) -> typing.Optional[asyncpg.Record]:
        return await conn.fetchrow("SELECT * From StarboardEntries WHERE message_id = $1", int(message))

    @staticmethod
    async def get_star_count(message: _messages.MessageLikeT, conn: asyncpg.connection) -> int:
        result = await conn.fetchrow("SELECT COUNT(*) FROM PostStars WHERE message_id = $1", int(message))
        return result["count"]

    async def on_message_reaction_add(self, reaction: _messages.Reaction, user: _users.User) -> None:
        if user.is_bot or reaction.emoji != UNICODE_STAR:
            return

        message_obj = self.components.rest.fetch_message(message_id=reaction.message_id, channel_id=reaction.channel_id)
        # This shouldn't ever fail.
        message_obj = await message_obj if not message_obj.is_resolved else message_obj

        if user != message_obj.author:
            await self.consume_star_increment(message_obj, user)

    async def on_message_reaction_remove(self, reaction: _messages.Reaction, user: _users.User):
        # Could check to see if this is the message's author but we'll take this at the
        if user.is_bot or reaction.emoji != UNICODE_STAR:
            return

        await self.consume_star_decrement(reaction.message_id, user)

    async def consume_star_increment(self, message: _messages.Message, reactor: _users.BaseUser) -> bool:
        async with self.client.sql_pool.acquire() as conn:
            if await self.get_starboard_entry(message, conn) is None:
                await conn.execute(
                    self.sql_scripts.create_starboard_entry, message.id, message.channel.id, reactor.id, 0
                )
            post_star = await conn.fetchrow(
                "SELECT * FROM PostStars WHERE message_id = $1 and starer_id = $2;", message.id, reactor.id,
            )
            if post_star is None:
                await conn.execute(
                    self.sql_scripts.create_post_star, message.id, message.channel.id, reactor.id,
                )
            return post_star is None

    async def consume_star_decrement(self, message: _messages.MessageLikeT, reactor: _users.BaseUser) -> bool:
        async with self.client.sql_pool.acquire() as conn:
            original_star = await conn.fetchrow(
                "SELECT * FROM PostStars WHERE message_id = $1 and starer_id = $2;", int(message), reactor.id,
            )
            if original_star is not None:
                await conn.execute(
                    "DELETE FROM poststars WHERE message_id = $1 and starer_id = $2", int(message), reactor.id,
                )
                if await self.get_star_count(message, conn) == 0:
                    await conn.execute("DELETE from StarboardEntries WHERE message_id = $1", int(message))
                return True
            return False

    @command_client.command(trigger="set starboard", aliases=["register starboard"])
    @util.command_error_relay((errors.NotFound, errors.BadRequest, errors.Forbidden))
    async def set_starboard(
        self, ctx: command_client.Context, target_channel: typing.Optional[_channels.Channel] = None
    ) -> None:
        if not (target_channel := target_channel or ctx.message.channel).is_resolved:
            target_channel = await target_channel

        if target_channel.id != ctx.message.channel.id:  # TODO: probably need the ids right now
            if not (channel := ctx.message.channel).is_resolved:
                channel = await channel

            # Should flag both DM channels and channels from other guilds.
            if getattr(target_channel, "guild_id", None) != channel.guild_id:
                raise reinhard.util.errors.CommandError("Unknown channel ID supplied.")

        async with self.client.sql_pool.acquire() as conn:
            if (
                starboard_channel := await self.get_starboard_channel(target_channel.guild.id, conn)
            ) is None:  # TODO? .id
                await conn.execute(
                    self.sql_scripts.create_starboard_channel, target_channel.guild_id, target_channel.id
                )
            elif starboard_channel["channel_id"] != target_channel.id:  # TODO: disable updating the posts on old ones.
                await conn.execute(
                    "UPDATE StarboardChannels SET channel_id = $2 WHERE guild_id = $1;",
                    target_channel.guild_id,
                    target_channel.id,
                )
        await ctx.reply(content=f"Set starboard channel to {target_channel.name}.")

    @command_client.command
    async def star(self, ctx: command_client.Context, target_message: _messages.Message) -> None:
        if not target_message.is_resolved:
            with util.CommandErrorRelay((errors.NotFound, errors.BadRequest)):
                target_message = await target_message

        if target_message.author.id == ctx.message.author.id:  # TODO: hikari bug?
            raise reinhard.util.errors.CommandError("You cannot star your own message.")

        if await self.consume_star_increment(target_message, ctx.message.author):
            response = "Added star to message."
        else:
            await self.consume_star_decrement(target_message, ctx.message.author)
            response = "Removed star from message."
        await ctx.reply(content=response)

    @command_client.command
    @util.command_error_relay((asyncpg.exceptions.DataError,))
    async def star_info(self, ctx: command_client.Context, target_message: _messages.Message) -> None:
        # TODO: guild check.
        async with self.client.sql_pool.acquire() as conn:
            if embed := await self.generate_star_embed(target_message, conn):
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(content="Starboard entry not found.")

    async def generate_star_embed(self, message: _messages.MessageLikeT, conn: asyncpg.connection) -> embeds.Embed:
        if star_count := await self.get_star_count(message, conn):
            return embeds.Embed()
