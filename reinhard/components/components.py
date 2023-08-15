# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2023, Faster Speeding
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

__all__: list[str] = ["load_components", "unload_components"]

import hikari
import tanjun
import yuyo

from .. import utility


@yuyo.components.as_single_executor(utility.DELETE_CUSTOM_ID)
async def on_delete_button(ctx: yuyo.ComponentContext, /) -> None:
    """Constant callback used by delete buttons.

    Parameters
    ----------
    ctx
        The context that triggered this delete.
    """
    # Filter is needed as "".split(",") will give [""] which is not a valid snowflake.
    author_ids = set(map(hikari.Snowflake, filter(None, ctx.id_metadata.split(","))))
    if (
        not author_ids  # no IDs == public
        or ctx.interaction.user.id in author_ids
        or ctx.interaction.member
        and author_ids.intersection(ctx.interaction.member.role_ids)
    ):
        await ctx.defer(defer_type=hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        await ctx.delete_initial_response()

    else:
        await ctx.create_initial_response(
            "You do not own this message",
            response_type=hikari.ResponseType.MESSAGE_CREATE,
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@tanjun.as_loader
def load_components(client: tanjun.abc.Client) -> None:
    component_client = client.injector.get_type_dependency(yuyo.ComponentClient)
    assert component_client
    component_client.register_executor(on_delete_button, timeout=None)


@tanjun.as_unloader
def unload_components(client: tanjun.abc.Client) -> None:
    component_client = client.injector.get_type_dependency(yuyo.ComponentClient)
    assert component_client
    component_client.deregister_executor(on_delete_button)
