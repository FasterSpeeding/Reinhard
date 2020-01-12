from __future__ import annotations


from hikari.orm import models


from reinhard import command_client
from reinhard import util


class StarboardModule(command_client.CommandModule):
    async def on_message_reaction_add(
        self, reaction: models.reactions.Reaction, user: models.users.User
    ):
        if reaction.emoji != "\N{WHITE MEDIUM STAR}":
            return

    async def on_message_reaction_remove(
        self, reaction: models.reactions.Reaction, user: models.users.User
    ):
        if reaction.emoji != "\N{WHITE MEDIUM STAR}":
            return

    @command_client.Command
    async def star(self, message: models.messages.Message, args: str) -> str:
        star_id = util.get_snowflake(args.split(" ", 1)[0])
