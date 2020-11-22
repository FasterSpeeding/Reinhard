from __future__ import annotations

import typing

from hikari import embeds
from hikari import errors as hikari_errors
from yuyo import backoff

from reinhard.util import constants
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from tanjun import context
    from tanjun import errors as tanjun_errors


async def error_hook(ctx: context.Context, exception: BaseException) -> None:
    retry = backoff.Backoff(max_retries=5)
    # TODO: better permission checks
    error_manager = rest_manager.HikariErrorManager(
        retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
    )
    embed = embeds.Embed(
        title=f"An unexpected {type(exception).__name__} occurred",
        color=constants.FAILED_COLOUR,
        description=f"```python\n{str(exception)[:1950]}```",
    )

    async for _ in retry:
        with error_manager:
            await ctx.message.reply(embed=embed,)
            break


async def on_conversion_error(ctx: context.Context, exception: tanjun_errors.ConversionError) -> None:
    retry = backoff.Backoff(max_retries=5)
    # TODO: better permission checks
    error_manager = rest_manager.HikariErrorManager(
        retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
    )

    async for _ in retry:
        with error_manager:
            await ctx.message.reply(content=str(exception))
            break
