from __future__ import annotations
import typing


import asyncpg
from hikari.net import errors
from hikari.orm.models import embeds as _embeds


from reinhard.util import command_client
from reinhard.util import basic as util
from reinhard import sql


if typing.TYPE_CHECKING:
    from hikari.orm import models


#  TODO: star status (e.g. deleted)
#  TODO: freeze stars when deleted?
#  TODO: handle sql errors?
#  TODO: starboard minimum count

UNICODE_STAR = "\N{WHITE MEDIUM STAR}"


class StarboardModule(command_client.CommandModule):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sql_scripts = sql.CachedScripts(pattern=".*star.*")
        self.add_event(command_client.CommandEvents.ERROR, self.client.on_error)

    @staticmethod
    async def get_starboard_channel(
        guild: models.guilds.GuildLikeT, conn: asyncpg.connection
    ) -> typing.Optional[asyncpg.Record]:
        return await conn.fetchrow("SELECT * FROM StarboardChannels WHERE guild_id = $1;", int(guild))

    @staticmethod
    async def get_starboard_entry(
        message: models.messages.MessageLikeT, conn: asyncpg.connection
    ) -> typing.Optional[asyncpg.Record]:
        return await conn.fetchrow("SELECT * From StarboardEntries WHERE message_id = $1", int(message))

    @staticmethod
    async def get_star_count(message: models.messages.MessageLikeT, conn: asyncpg.connection) -> int:
        result = await conn.fetchrow("SELECT COUNT(*) FROM PostStars WHERE message_id = $1", int(message))
        return result["count"]

    async def on_message_reaction_add(self, reaction: models.reactions.Reaction, user: models.users.User) -> None:
        if user.is_bot or reaction.emoji != UNICODE_STAR:
            return

        message_obj = self._fabric.state_registry.get_mandatory_message_by_id(
            message_id=reaction.message_id, channel_id=reaction.channel_id
        )
        # This shouldn't ever fail.
        message_obj = await message_obj if not message_obj.is_resolved else message_obj

        if user != message_obj.author:
            await self.consume_star_increment(message_obj, user)

    async def on_message_reaction_remove(self, reaction: models.reactions.Reaction, user: models.users.User):
        # Could check to see if this is the message's author but we'll take this at the
        if user.is_bot or reaction.emoji != UNICODE_STAR:
            return

        await self.consume_star_decrement(reaction.message_id, user)

    async def consume_star_increment(self, message: models.messages.Message, reactor: models.users.BaseUser) -> bool:
        async with self.client.sql_pool.acquire() as conn:
            starboard_entry = await self.get_starboard_entry(message, conn)
            if starboard_entry is None:
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

    async def consume_star_decrement(
        self, message: models.messages.MessageLikeT, reactor: models.users.BaseUser
    ) -> bool:
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
    async def set_starboard(self, ctx: command_client.Context, args: str) -> None:
        target_channel = ctx.fabric.state_registry.get_mandatory_channel_by_id(
            util.get_snowflake(args[0]) or ctx.message.channel_id
        )
        if not target_channel.is_resolved:
            with util.ReturnErrorStr((errors.NotFoundHTTPError, errors.BadRequestHTTPError)):
                target_channel = await target_channel

        channel = ctx.message.channel
        if not channel:
            with util.ReturnErrorStr((errors.NotFoundHTTPError,)):
                channel = await channel

        # Should flag both DM channels and channels from other guilds.
        if getattr(target_channel, "guild_id", None) != channel.guild_id:
            raise command_client.CommandError("Unknown channel ID supplied.")

        async with self.client.sql_pool.acquire() as conn:
            starboard_channel = await self.get_starboard_channel(target_channel.guild, conn)
            if starboard_channel is None:
                await conn.execute(self.sql_scripts.create_starboard_channel, channel.guild_id, target_channel.id)
            elif starboard_channel["channel_id"] != target_channel.id:  # TODO: disable updating the posts on old ones.
                await conn.execute(
                    "UPDATE StarboardChannels SET channel_id = $2 WHERE guild_id = $1;",
                    channel.guild_id,
                    target_channel.id,
                )
        # TODO: edge case unresolved error
        await ctx.reply(content=f"Set starboard channel to {target_channel.name}.")

    @command_client.command
    async def star(self, ctx: command_client.Context, args: str) -> None:
        target_message = ctx.fabric.state_registry.get_mandatory_message_by_id(
            message_id=util.get_snowflake(args[0]), channel_id=ctx.message.channel_id,
        )
        if not target_message.is_resolved:
            with util.ReturnErrorStr((errors.NotFoundHTTPError, errors.BadRequestHTTPError)):
                target_message = await target_message

        if target_message.author == ctx.message.author:
            raise command_client.CommandError("You cannot star your own message.")

        if await self.consume_star_increment(target_message, ctx.message.author):
            response = "Added star to message."
        else:
            await self.consume_star_decrement(target_message, ctx.message.author)
            response = "Removed star from message."
        # TODO: edge case unresolved error
        await ctx.reply(content=response)

    @command_client.command
    @util.return_error_str((asyncpg.exceptions.DataError,))
    async def star_info(self, ctx: command_client.Context, args: str) -> None:
        if not args:
            raise command_client.CommandError("Message ID required.")
        message_id = util.get_snowflake(args[0])
        async with self.client.sql_pool.acquire() as conn:
            starboard_entry = await conn.fetchrow("SELECT * FROM StarboardEntries WHERE message_id = $1;", message_id)
            if starboard_entry is None:
                await ctx.reply(content="Starboard entry not found.")
            else:
                await ctx.reply(embed=await self.generate_star_embed(ctx.message, conn))

    async def generate_star_embed(
        self, message: models.messages.MessageLikeT, conn: asyncpg.connection
    ) -> models.embeds.Embed:
        star_count = await self.get_star_count(message, conn)
        return _embeds.Embed()
