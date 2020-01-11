from __future__ import annotations


from hikari.orm import models


from reinhard.command_client import CommandModule


class StarboardModule(CommandModule):
    async def on_message_reaction_add(
        self, reaction: models.reactions.Reaction, user: models.users.User
    ):
        if reaction.emoji == "\N{WHITE MEDIUM STAR}":
            ...

    async def on_message_reaction_remove(
        self, reaction: models.reactions.Reaction, user: models.users.User
    ):
        print(reaction.emoji == "\N{WHITE MEDIUM STAR}")
        if reaction.emoji == "\N{WHITE MEDIUM STAR}":
            ...
