from __future__ import annotations

import contextlib
import typing

from hikari import embeds
from hikari import errors as hikari_errors

from . import constants

if typing.TYPE_CHECKING:
    from tanjun import commands as _commands
    from tanjun import errors as _errors


async def error_hook(ctx: _commands.Context, exception: BaseException) -> None:
    with contextlib.suppress(hikari_errors.Forbidden, hikari_errors.NotFound):  # TODO: better permission checks
        await ctx.message.safe_reply(  # command_client.CommandPermissionError?
            embed=embeds.Embed(
                title=f"An unexpected {type(exception).__name__} occurred",
                color=constants.FAILED_COLOUR,
                description=f"```python\n{str(exception)[:1950].replace(ctx.components.config.token, 'REDACTED')}```",
            ),
        )


async def on_conversion_error(ctx: _commands.Context, exception: _errors.ConversionError) -> None:
    with contextlib.suppress(hikari_errors.Forbidden, hikari_errors.NotFound):
        message = str(exception)
        if exception.origins and (origin_message := str(exception.origins[0])) != message:
            message += f": {origin_message}"

        await ctx.message.safe_reply(content=message)
