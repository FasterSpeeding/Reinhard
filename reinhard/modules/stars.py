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

    async def on_message_reaction_add(self, reaction: models.reactions.Reaction, user: models.users.User):
        if reaction.emoji != "\N{WHITE MEDIUM STAR}" or reaction.message.author == user:
            return

        async with self.command_client.sql_pool.acquire() as conn:
            star_event = await conn.fetchrow(self.sql_scripts.find_post_star_by_ids, reaction.message.id, user.id)
            if star_event is None:
                await conn.execute(
                    self.sql_scripts.create_post_star, reaction.message.id, reaction.message.channel_id, user.id
                )

    async def on_message_reaction_remove(self, reaction: models.reactions.Reaction, user: models.users.User):
        if reaction.emoji != "\N{WHITE MEDIUM STAR}" or reaction.message.author == user:
            return

        async with self.command_client.sql_pool.acquire() as conn:
            await conn.execute(self.sql_scripts.delete_post_star, reaction.message.id, user.id)

    @command_client.Command(trigger="set starboard", aliases=["register starboard"])
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

    @command_client.Command
    @util.return_error_str_factory(
        (errors.NotFoundError, errors.BadRequest), {errors.BadRequest: "Invalid ID provided."}
    )
    async def star(self, message: models.messages.Message, args: str) -> str:
        target_message = await self.command_client._fabric.http_api.get_channel_message(
            message_id=str(util.get_snowflake(args.split(" ", 1)[0])), channel_id=str(message.channel.id)
        )

        if int(target_message["author"]["id"]) == message.author.id:
            return "You cannot star your own message."

        async with self.command_client.sql_pool.acquire() as conn:
            star_event = await conn.fetchrow(
                self.sql_scripts.find_post_star_by_ids, int(target_message["id"]), message.author.id
            )
            if star_event is None:
                await conn.execute(
                    self.sql_scripts.create_post_star,
                    int(target_message["id"]),
                    int(target_message["channel_id"]),
                    message.author.id,
                )
                response = "Added star to message."
            else:
                response = "You've already stared that message."
        return response

    async def star_show(self, message: models.messages.Message, args: str) -> str:
        ...

    async def get_star_embed(self, message_id):
        ...