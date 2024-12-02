# BSD 3-Clause License
#
# Copyright (c) 2020-2025, Faster Speeding
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

__all__: list[str] = ["loader"]

import json
import typing

import hikari
import tanjun
from hikari import traits
from tanchan.components import buttons
from tanjun.annotations import Converted
from tanjun.annotations import Flag
from tanjun.annotations import Greedy
from tanjun.annotations import Positional
from tanjun.annotations import Str

from reinhard import utility

if typing.TYPE_CHECKING:
    import alluka

component = tanjun.Component(name="sudo", strict=True)


@tanjun.as_message_command("error")
async def error_message_command(_: tanjun.abc.Context) -> None:
    """Command used for testing the current error handling."""
    error_message = "This is an exception, get used to it."
    raise RuntimeError(error_message)


@tanjun.annotations.with_annotated_args
@tanjun.as_message_command("echo")
async def echo_command(
    ctx: tanjun.abc.Context,
    entity_factory: alluka.Injected[traits.EntityFactoryAware],
    # TODO: Greedy should implicitly mark arguments as positional.
    content: typing.Annotated[hikari.UndefinedOr[Str], Positional(), Greedy()] = hikari.UNDEFINED,
    raw_embed: typing.Annotated[
        hikari.UndefinedOr[typing.Any], Flag(aliases=["--embed", "-e"]), Converted(json.loads)
    ] = hikari.UNDEFINED,
) -> None:
    """Command used for getting the bot to mirror a response."""
    embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED
    if raw_embed is not hikari.UNDEFINED:
        try:
            embed = entity_factory.entity_factory.deserialize_embed(raw_embed)

            if embed.colour is None:
                embed.colour = utility.embed_colour()

        except (TypeError, ValueError) as exc:
            await ctx.respond(content=f"Invalid embed passed: {str(exc)[:1970]}")
            return

    if content or embed:
        await ctx.respond(content=content, embed=embed, component=buttons.delete_row(ctx))

    else:
        await ctx.respond(content="No content provided", component=buttons.delete_row(ctx))


loader = component.add_check(tanjun.checks.OwnerCheck()).load_from_scope().make_loader()
