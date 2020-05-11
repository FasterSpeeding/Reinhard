from __future__ import annotations

import contextlib
import typing

from hikari import embeds
from hikari import errors as hikari_errors

from reinhard.util import constants

if typing.TYPE_CHECKING:
    from reinhard.util import command_client
    from reinhard.util import errors


async def error_hook(ctx: command_client.Context, exception: BaseException) -> None:
    with contextlib.suppress(hikari_errors.Forbidden, hikari_errors.NotFound):  # TODO: better permission checks
        await ctx.message.reply(  # command_client.CommandPermissionError?
            embed=embeds.Embed(
                title=f"An unexpected {type(exception).__name__} occurred",
                color=constants.FAILED_COLOUR,
                description=f"```python\n{str(exception)[:1950].replace(ctx.components.config.token, 'REDACTED')}```",
            ),
        )


async def on_conversion_error(ctx: command_client.Context, exception: errors.ConversionError) -> None:
    with contextlib.suppress(hikari_errors.Forbidden, hikari_errors.NotFound):
        await ctx.message.reply(content=f"{exception}: {exception.origins[0]}" if exception.origins else str(exception))
