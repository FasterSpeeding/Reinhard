# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
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

import typing

import aiohttp
import tanjun
import yuyo
from hikari import config as hikari_config

from . import config as config_
from .util import command_hooks
from .util import dependencies

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits


def build_bot(*, config: config_.FullConfig | None = None) -> hikari_traits.GatewayBotAware:
    from hikari.impl import bot as bot_module

    if config is None:
        config = config_.load_config()

    bot = bot_module.GatewayBot(
        config.tokens.bot,
        logs=config.log_level,
        intents=config.intents,
        cache_settings=hikari_config.CacheSettings(components=config.cache),
        # rest_url="https://ptb.discord.com/api/v8"
        # rest_url="https://staging.discord.co/api/v8"
    )
    build(bot, config=config)
    return bot


def build(bot: hikari_traits.GatewayBotAware, /, *, config: config_.FullConfig | None = None) -> tanjun.Client:
    if config is None:
        config = config_.load_config()

    client = (
        tanjun.Client.from_gateway_bot(
            bot, mention_prefix=config.mention_prefix, set_global_commands=config.set_global_commands
        )
        .set_hooks(
            tanjun.AnyHooks().set_on_parser_error(command_hooks.on_parser_error).set_on_error(command_hooks.on_error)
        )
        .add_prefix(config.prefixes)
        .add_type_dependency(
            aiohttp.ClientSession,
            dependencies.SessionDependency(bot.http_settings, bot.proxy_settings, "Reinhard discord bot"),
        )
        .add_type_dependency(config_.FullConfig, lambda: typing.cast(config_.FullConfig, config))
        .add_type_dependency(config_.Tokens, lambda: typing.cast(config_.FullConfig, config).tokens)
        .add_type_dependency(yuyo.ReactionClient, dependencies.ReactionClientDependency())
        .add_type_dependency(yuyo.ComponentClient, dependencies.ComponentClientDependency())
        .load_modules("reinhard.components.basic")
        .load_modules("reinhard.components.external")
        .load_modules("reinhard.components.moderation")
        .load_modules("reinhard.components.sudo")
        .load_modules("reinhard.components.util")
    )

    if config.ptf:
        ptf = config.ptf
        client.add_type_dependency(config_.PTFConfig, lambda: ptf)

    if config.owner_only:
        client.add_check(tanjun.checks.ApplicationOwnerCheck())

    return client
