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

import asyncio
import typing

import hikari
import tanjun
import yuyo
import yuyo.asgi

# from . import sql
from . import config as config_
from . import utility

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits


def build_gateway_bot(*, config: config_.FullConfig | None = None) -> tuple[hikari.impl.GatewayBot, tanjun.Client]:
    if config is None:
        config = config_.FullConfig.from_env()

    bot = hikari.GatewayBot(
        config.tokens.bot,
        logs=config.log_level,
        intents=config.intents,
        cache_settings=hikari.CacheSettings(components=config.cache),
        rest_url="https://canary.discord.com/api/v8"
        # rest_url="https://staging.discord.co/api/v8"
    )
    return bot, build_from_gateway_bot(bot, config=config)


def build_rest_bot(*, config: config_.FullConfig | None = None) -> tuple[hikari.impl.RESTBot, tanjun.Client]:
    if config is None:
        config = config_.FullConfig.from_env()

    bot = hikari.impl.RESTBot(config.tokens.bot, hikari.TokenType.BOT)
    return bot, build_from_rest_bot(bot, config=config)


def _build(client: tanjun.Client, config: config_.FullConfig) -> tanjun.Client:
    (
        client.set_hooks(tanjun.AnyHooks().set_on_parser_error(utility.on_parser_error).set_on_error(utility.on_error))
        .add_prefix(config.prefixes)
        .set_type_dependency(config_.FullConfig, config)
        .set_type_dependency(config_.Tokens, config.tokens)
        .load_modules("reinhard.components")
    )
    utility.SessionManager(
        client.rest.http_settings, client.rest.proxy_settings, "Reinhard discord bot"
    ).load_into_client(client)

    if config.ptf:
        ptf = config.ptf
        client.set_type_dependency(config_.PTFConfig, ptf)

    if config.owner_only:
        client.add_check(tanjun.checks.OwnerCheck())

    return client


def build_from_gateway_bot(
    bot: hikari_traits.GatewayBotAware, /, *, config: config_.FullConfig | None = None
) -> tanjun.Client:
    if config is None:
        config = config_.FullConfig.from_env()

    component_client = yuyo.ComponentClient.from_gateway_bot(bot, event_managed=False).set_constant_id(
        utility.DELETE_CUSTOM_ID, utility.DeleteMessageButton(bot.rest, cache=bot.cache)
    )
    reaction_client = yuyo.ReactionClient.from_gateway_bot(bot, event_managed=False)
    client = _build(
        tanjun.Client.from_gateway_bot(
            bot, mention_prefix=config.mention_prefix, declare_global_commands=config.declare_global_commands
        )
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, component_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, component_client.close)
        .set_type_dependency(yuyo.ReactionClient, reaction_client)
        .set_type_dependency(yuyo.ComponentClient, component_client),
        config,
    )

    return client


def build_from_rest_bot(
    bot: hikari_traits.RESTBotAware, /, *, config: config_.FullConfig | None = None
) -> tanjun.Client:
    if config is None:
        config = config_.FullConfig.from_env()

    component_client = yuyo.ComponentClient.from_rest_bot(bot).set_constant_id(
        utility.DELETE_CUSTOM_ID, utility.DeleteMessageButton(bot.rest)
    )
    client = _build(
        tanjun.Client.from_rest_bot(bot, declare_global_commands=config.declare_global_commands)
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, component_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, component_client.close)
        .set_type_dependency(yuyo.ComponentClient, component_client),
        config,
    )
    return client


def run_gateway_bot(*, config: config_.FullConfig | None = None) -> None:
    bot, _ = build_gateway_bot(config=config)
    bot.run()


async def _run_rest(*, config: config_.FullConfig | None = None) -> None:
    bot, client = build_rest_bot(config=config)

    await bot.start(port=1800)
    async with client:
        await bot.join()


def run_rest_bot(*, config: config_.FullConfig | None = None) -> None:
    asyncio.run(_run_rest(config=config))


def make_asgi_app(*, config: config_.FullConfig | None = None) -> yuyo.asgi.AsgiAdapter:
    if config is None:
        config = config_.FullConfig.from_env()

    rest = hikari.impl.RESTApp().acquire(config.tokens.bot, "Bot")
    interaction_server = hikari.impl.InteractionServer(entity_factory=rest.entity_factory, rest_client=rest)
    component_client = yuyo.ComponentClient(server=interaction_server).set_constant_id(
        utility.DELETE_CUSTOM_ID, utility.DeleteMessageButton(rest)
    )
    client = _build(
        tanjun.Client(rest, server=interaction_server, declare_global_commands=config.declare_global_commands)
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, component_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, component_client.close)
        .set_type_dependency(yuyo.ComponentClient, component_client),
        config,
    )

    return (
        yuyo.asgi.AsgiAdapter(interaction_server)
        .add_startup_callback(rest.start)
        .add_shutdown_callback(rest.close)
        .add_startup_callback(client.open)
        .add_shutdown_callback(client.close)
    )
