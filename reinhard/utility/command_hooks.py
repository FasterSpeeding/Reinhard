# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2022, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__ = ["on_error", "on_parser_error"]

import hikari
import tanjun

from . import basic
from . import constants


async def on_error(ctx: tanjun.abc.Context, exception: BaseException) -> None:
    """Handle an unexpected error during command execution.

    This is the default error handler for all commands.

    Parameters
    ----------
    ctx
        The context of the command.
    exception
        The exception that was raised.
    """
    # TODO: better permission checks
    embed = hikari.Embed(
        title=f"An unexpected {type(exception).__name__} occurred",
        colour=constants.FAILED_COLOUR,
        description=f"```python\n{str(exception)[:1950]}```",
    )
    await ctx.respond(embed=embed, component=basic.delete_row(ctx))


async def on_parser_error(ctx: tanjun.abc.Context, exception: tanjun.ParserError) -> None:
    """Handle a parser error.

    Parameters
    ----------
    ctx
        The context of the command.
    exception
        The exception that was raised.
    """
    # TODO: better permission checks
    message = str(exception)

    if isinstance(exception, tanjun.ConversionError) and exception.errors:
        if len(exception.errors) > 1:
            message += ":\n* " + "\n* ".join(map("`{}`".format, exception.errors))

        else:
            message = f"{message}: `{exception.errors[0]}`"

    await ctx.respond(content=message, component=basic.delete_row(ctx))
