from __future__ import annotations


from hikari.net import errors
from hikari.orm import models


from reinhard import command_client
from reinhard import sql
from reinhard import util

#  TODO: star status (e.g. deleted)
#  TODO: freeze stars when deleted?
#  TODO: handle sql errors?
#  TODO: starboard minimum count

UNICODE_STAR = "\N{WHITE MEDIUM STAR}"


class StarboardModule(command_client.CommandModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_scripts = sql.CachedScripts(pattern=".*star.*")

    async def on_message_reaction_add(self, reaction: models.reactions.Reaction, user: models.users.User):
        print(user.is_bot)
        print(reaction.emoji != UNICODE_STAR)
        if user.is_bot or reaction.emoji != UNICODE_STAR:
            return

        message_obj = self.command_client._fabric.state_registry.get_mandatory_message_by_id(
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
        async with self.command_client.sql_pool.acquire() as conn:
            star_event = await conn.fetchrow(self.sql_scripts.find_post_star_by_ids, message.id, reactor.id)
            if star_event is None:
                await conn.execute(
                    self.sql_scripts.create_post_star, message.id, message.channel.id, reactor.id,
                )
            return star_event is None

    async def consume_star_decrement(
        self, message: models.messages.MessageLikeT, reactor: models.users.BaseUser
    ) -> bool:
        async with self.command_client.sql_pool.acquire() as conn:
            original_star = await conn.fetchrow(self.sql_scripts.find_post_star_by_ids, int(message), reactor.id)
            if original_star is not None:
                await conn.execute(self.sql_scripts.delete_post_star, int(message), reactor.id)
            return original_star is not None

    @command_client.command(trigger="set starboard", aliases=["register starboard"])
    async def set_starboard(self, message: models.messages.Message, args: str) -> str:
        if args:
            channel_id = util.get_snowflake(args.split(" ", 1)[0])
        else:
            channel_id = message.channel_id

        channel = self.command_client._fabric.state_registry.get_mandatory_channel_by_id(channel_id)
        if not channel.is_resolved:
            with util.ReturnErrorStr((errors.NotFoundHTTPError, errors.BadRequestHTTPError),):
                channel = await channel
        # Should flag both DM channels and channels from other guilds.
        if getattr(channel, "guild_id", None) != message.guild_id:
            return "Unknown channel ID supplied."

        async with self.command_client.sql_pool.acquire() as conn:
            starboard_channel = await conn.fetchrow(self.sql_scripts.find_starboard_channel, message.guild_id)
            if starboard_channel is None:
                await conn.execute(self.sql_scripts.create_starboard_channel, message.guild_id, channel_id)
            elif starboard_channel["channel_id"] != channel_id:  # TODO: disable updating the posts on old ones.
                await conn.execute(self.sql_scripts.update_starboard_channel, message.guild_id, channel_id)

        return f"Set starboard channel to {channel.name}."

    @command_client.command
    @util.return_error_str((errors.NotFoundHTTPError, errors.BadRequestHTTPError),)
    async def star(self, message: models.messages.Message, args: str) -> str:
        target_message = await self.command_client._fabric.state_registry.get_mandatory_message_by_id(
            message_id=util.get_snowflake(args.split(" ", 1)[0]), channel_id=message.channel.id,
        )
        if not target_message.is_resolved:
            with util.ReturnErrorStr((errors.NotFoundHTTPError, errors.BadRequestHTTPError),):
                target_message = await target_message

        if target_message.author == message.author:
            return "You cannot star your own message."

        async with self.command_client.sql_pool.acquire() as conn:
            star_event = await conn.fetchrow(
                self.sql_scripts.find_post_star_by_ids, target_message.id, message.author.id
            )
            if star_event is None:
                await conn.execute(
                    self.sql_scripts.create_post_star, target_message.id, target_message.channel.id, message.author.id,
                )
                response = "Added star to message."
            else:
                response = "You've already stared that message."
        return response

    async def star_info(self, message: models.messages.Message, args: str) -> str:
        # star_event = await conn.fetchrow(
        #    self.sql_scripts.find_post_star_by_ids, target_message.id, message.author.id
        # )
        original_star["message_id"]
        original_star["channel_id"]








    async def generate_star_embed(self, message_id):
        ...
