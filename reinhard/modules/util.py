from __future__ import annotations

from hikari import colors
from hikari import embeds

from reinhard.util import command_client
from reinhard.util import command_hooks


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

    @command_client.command(aliases=("color",), greedy="color")
    async def color(self, ctx: command_client.Context, color: colors.Color):
        await ctx.message.reply(
            embed=embeds.Embed(color=color)
            .add_field(name="RGB", value=str(color.rgb))
            .add_field(name="HEX", value=str(color.hex_code))
        )
