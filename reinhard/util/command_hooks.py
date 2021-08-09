from __future__ import annotations

import hikari
import tanjun
from yuyo import backoff

from ..util import constants
from ..util import rest_manager


async def on_error(ctx: tanjun.abc.Context, exception: BaseException) -> None:
    retry = backoff.Backoff(max_retries=5)
    # TODO: better permission checks
    error_manager = rest_manager.HikariErrorManager(retry, break_on=(hikari.ForbiddenError, hikari.NotFoundError))
    embed = hikari.Embed(
        title=f"An unexpected {type(exception).__name__} occurred",
        colour=constants.FAILED_COLOUR,
        description=f"```python\n{str(exception)[:1950]}```",
    )

    async for _ in retry:
        with error_manager:
            await ctx.respond(embed=embed)
            break


async def on_parser_error(ctx: tanjun.abc.Context, exception: tanjun.ParserError) -> None:
    retry = backoff.Backoff(max_retries=5)
    # TODO: better permission checks
    error_manager = rest_manager.HikariErrorManager(retry, break_on=(hikari.ForbiddenError, hikari.NotFoundError))

    message = str(exception)

    if isinstance(exception, tanjun.ConversionError) and exception.errors:
        if len(exception.errors) > 1:
            message += ":\n* " + "\n* ".join(map("`{}`".format, exception.errors))

        else:
            message = f"{message}: `{exception.errors[0]}`"

    async for _ in retry:
        with error_manager:
            await ctx.respond(content=message)
            break
