from __future__ import annotations


from hikari.orm import models
from hikari import errors


from reinhard import command_client
from reinhard import sql
from reinhard import util


class StarboardModule(command_client.CommandModule):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_scripts = sql.CachedScripts(pattern=".*star.*")

    # , reaction: models.reactions.Reaction, user: models.users.User
    async def on_raw_message_reaction_add(self, payload):
        message_obj = await self.command_client._fabric.state_registry.get_mandatory_message_by_id(
            message_id=payload.message_id, channel_id=payload.channel_id
        )
        if payload.emoji.name != "\N{WHITE MEDIUM STAR}" or payload.user_id == message_obj.author_id:
            return

        async with self.command_client.sql_pool.acquire() as conn:
            star_event = await conn.fetchrow(
                self.sql_scripts.find_post_star_by_ids, int(payload.message_id), int(payload.user_id)
            )
            if star_event is None:
                await conn.execute(
                    self.sql_scripts.create_post_star,
                    int(payload.message_id),
                    int(payload.channel_id),
                    int(payload.user_id),
                )

    #  reaction: models.reactions.Reaction, user: models.users.User
    async def on_raw_message_reaction_remove(self, payload):
        # Could check to see if this is the message's author but we'll take this at the
        if payload.emoji.name != "\N{WHITE MEDIUM STAR}":
            return

        async with self.command_client.sql_pool.acquire() as conn:
            amount_of_stars = len(conn.fetch(self.sql_scripts.find_post_stars_by_id, int(payload.message_id)))
            await conn.execute(self.sql_scripts.delete_post_star, int(payload.message_id), int(payload.user_id))
            post_stars = conn.fetch(self.sql_scripts.find_post_stars_by_id, int(payload.message_id))
            if amount_of_stars == len(post_stars):
                return

    async def consume_star_increment(self, message):
        async with self.command_client.sql_pool.acquire() as conn:
            ...


    @command_client.command(trigger="set starboard", aliases=["register starboard"])
    async def set_starboard(self, message: models.messages.Message, args: str) -> str:
        if args:
            channel_id = util.get_snowflake(args.split(" ", 1)[0])
        else:
            channel_id = message.channel_id

        channel = self.command_client._fabric.state_registry.get_mandatory_channel_by_id(channel_id)
        # This will both flag if it's an Unavailable object or a channel from a different guild.
        if getattr(channel, "guild_id", None) != message.guild_id:
            return "Invalid channel ID supplied."

        async with self.command_client.sql_pool.acquire() as conn:
            starboard_channel = await conn.fetchrow(self.sql_scripts.find_starboard_channel, message.guild_id)
            if starboard_channel is None:
                await conn.execute(self.sql_scripts.create_starboard_channel, message.guild_id, channel_id)
            elif starboard_channel["channel_id"] != channel_id:  # TODO: disable updating the posts on old ones.
                await conn.execute(self.sql_scripts.update_starboard_channel, message.guild_id, channel_id)

        return f"Set starboard channel to {channel.name}."

    @command_client.command
    @util.return_error_str((errors.NotFoundError, errors.BadRequest), {errors.BadRequest: "Invalid ID provided."})
    async def star(self, message: models.messages.Message, args: str) -> str:
        target_message = await self.command_client._fabric.http_adapter.get_channel_message(
            message=util.get_snowflake(args.split(" ", 1)[0]), channel=message.channel,
        )

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

    async def star_show(self, message: models.messages.Message, args: str) -> str:
        ...

    async def get_star_embed(self, message_id):
        ...
