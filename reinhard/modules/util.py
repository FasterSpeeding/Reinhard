from __future__ import annotations

import typing

from hikari import bases
from hikari import colors
from hikari import embeds
from hikari import errors as hikari_errors

from reinhard.util import command_client
from reinhard.util import command_hooks
from reinhard.util import errors


exports = ["UtilCluster"]


class UtilCluster(command_client.CommandCluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            *args,
            **kwargs,
            hooks=command_client.CommandHooks(
                on_error=command_hooks.error_hook, on_conversion_error=command_hooks.on_conversion_error
            ),
        )

    @command_client.command(aliases=("colour",), greedy="color_or_role")
    async def color(self, ctx: command_client.Context, color_or_role: typing.Union[colors.Color, bases.Snowflake]):
        color = color_or_role
        if isinstance(color_or_role, bases.Snowflake):
            if not ctx.message.guild_id:
                raise errors.CommandError("Cannot get a role's colour in a DM channel.")

            try:
                role = (await ctx.components.rest.fetch_roles(ctx.message.guild_id))[color_or_role]
            except (KeyError, hikari_errors.Forbidden, hikari_errors.NotFound):
                raise errors.CommandError("Failed to find role.")
            color = role.color

        await ctx.message.reply(
            embed=embeds.Embed(color=color)
            .add_field(name="RGB", value=str(color.rgb))
            .add_field(name="HEX", value=str(color.hex_code))
        )
