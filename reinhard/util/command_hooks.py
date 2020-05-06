from __future__ import annotations

import contextlib

from hikari import embeds

from reinhard.util import command_client


async def error_hook(ctx: command_client.Context, excception: BaseException) -> None:
    with contextlib.suppress(command_client.HikariPermissionError):  # TODO: better permission checks
        await ctx.message.reply(
            embed=embeds.Embed(
                title=f"An unexpected {type(excception).__name__} occurred",
                color=15746887,
                description=f"```python\n{str(excception)[:1950]}```",
            ),
        )
