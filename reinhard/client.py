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

import datetime
import pathlib
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


def _rukari(config: config_.FullConfig | None) -> tuple[hikari.Runnable, tanjun.Client] | None:
    try:
        import rukari  # type: ignore

    except ImportError:
        return None

    print("Initiating with Rukari")
    if config is None:
        config = config_.FullConfig.from_env()

    bot: hikari.ShardAware = rukari.Bot(config.tokens.bot, intents=config.intents)
    assert isinstance(bot, hikari.RESTAware)
    assert isinstance(bot, hikari.EventManagerAware)
    assert isinstance(bot, hikari.Runnable)

    import logging

    logging.basicConfig(level=config.log_level or logging.INFO)

    component_client = yuyo.ComponentClient(event_manager=bot.event_manager, event_managed=False).set_constant_id(
        utility.DELETE_CUSTOM_ID, utility.delete_button_callback, prefix_match=True
    )
    reaction_client = yuyo.ReactionClient(rest=bot.rest, event_manager=bot.event_manager, event_managed=False)
    return bot, _build(
        tanjun.Client(
            bot.rest,
            events=bot.event_manager,
            shards=bot,
            event_managed=True,
            mention_prefix=config.mention_prefix,
            declare_global_commands=False if config.hot_reload else config.declare_global_commands,
        )
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, component_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, component_client.close)
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, reaction_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, reaction_client.close)
        .set_type_dependency(yuyo.ReactionClient, reaction_client)
        .set_type_dependency(yuyo.ComponentClient, component_client),
        config,
    )


def build_gateway_bot(*, config: config_.FullConfig | None = None) -> tuple[hikari.Runnable, tanjun.Client]:
    """Build a gateway bot with a bound Reinhard client.

    Parameters
    ----------
    config
        The configuration to use.

    Returns
    -------
    tuple[hikari.impl.GatewayBot, tanjun.Client]
        The gateway bot and Reinhard client.
    """
    if config is None:
        config = config_.FullConfig.from_env()

    if result := _rukari(config):
        return result

    print("Initiating with standard Hikari impl")
    bot = hikari.GatewayBot(
        config.tokens.bot,
        logs=config.log_level,
        intents=config.intents,
        cache_settings=hikari.impl.CacheSettings(components=config.cache),
        # rest_url="https://canary.discord.com/api/v8"
        # rest_url="https://staging.discord.co/api/v8"
    )
    return bot, build_from_gateway_bot(bot, config=config)


def build_rest_bot(*, config: config_.FullConfig | None = None) -> tuple[hikari.impl.RESTBot, tanjun.Client]:
    """Build a REST bot with a bound Reinhard client.

    Parameters
    ----------
    config
        The configuration to use.

    Returns
    -------
    tuple[hikari.impl.RESTBot, tanjun.Client]
        The REST bot and Reinhard client.
    """
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
    )

    components_dir = pathlib.Path(".") / "reinhard" / "components"
    if config.hot_reload:
        guilds = (
            config.declare_global_commands if isinstance(config.declare_global_commands, hikari.Snowflake) else None
        )
        redeclare = None if config.declare_global_commands is False else datetime.timedelta(seconds=10)
        (
            tanjun.HotReloader(commands_guild=guilds, redeclare_cmds_after=redeclare)
            .add_directory(components_dir, namespace="reinhard.components")
            .add_to_client(client)
        )

    else:
        client.load_directory(components_dir, namespace="reinhard.components")

    assert isinstance(client.rest.http_settings, hikari.impl.HTTPSettings)
    assert isinstance(client.rest.proxy_settings, hikari.impl.ProxySettings)
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
    """Build a Reinhard client from a gateway bot.

    Parameters
    ----------
    bot
        The gateway bot to use.
    config
        The configuration to use.

    Returns
    -------
    tanjun.Client
        The Reinhard client.
    """
    if config is None:
        config = config_.FullConfig.from_env()

    component_client = yuyo.ComponentClient.from_gateway_bot(bot, event_managed=False).set_constant_id(
        utility.DELETE_CUSTOM_ID, utility.delete_button_callback, prefix_match=True
    )
    reaction_client = yuyo.ReactionClient.from_gateway_bot(bot, event_managed=False)
    return _build(
        tanjun.Client.from_gateway_bot(
            bot,
            mention_prefix=config.mention_prefix,
            declare_global_commands=False if config.hot_reload else config.declare_global_commands,
        )
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, component_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, component_client.close)
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, reaction_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, reaction_client.close)
        .set_type_dependency(yuyo.ReactionClient, reaction_client)
        .set_type_dependency(yuyo.ComponentClient, component_client),
        config,
    )


def build_from_rest_bot(
    bot: hikari_traits.RESTBotAware, /, *, config: config_.FullConfig | None = None
) -> tanjun.Client:
    """Build a Reinhard client from a REST bot.

    Parameters
    ----------
    bot
        The REST bot to use.
    config
        The configuration to use.

    Returns
    -------
    tanjun.Client
        The Reinhard client.
    """
    if config is None:
        config = config_.FullConfig.from_env()

    component_client = yuyo.ComponentClient.from_rest_bot(bot).set_constant_id(
        utility.DELETE_CUSTOM_ID, utility.delete_button_callback, prefix_match=True
    )
    return _build(
        tanjun.Client.from_rest_bot(
            bot,
            declare_global_commands=False if config.hot_reload else config.declare_global_commands,
            bot_managed=True,
        )
        .add_client_callback(tanjun.ClientCallbackNames.STARTING, component_client.open)
        .add_client_callback(tanjun.ClientCallbackNames.CLOSING, component_client.close)
        .set_type_dependency(yuyo.ComponentClient, component_client),
        config,
    )


def run_gateway_bot(*, config: config_.FullConfig | None = None) -> None:
    """Run a Reinhard gateway bot.

    Parameters
    ----------
    config
        The configuration to use.
    """
    bot, _ = build_gateway_bot(config=config)
    bot.run()


def run_rest_bot(*, config: config_.FullConfig | None = None) -> None:
    """Run a Reinhard RESTBot locally.

    Parameters
    ----------
    config
        The configuration to use.
    """
    bot, _ = build_rest_bot(config=config)
    bot.run(port=1800)


def make_asgi_app(*, config: config_.FullConfig | None = None) -> yuyo.AsgiBot:
    """Make an ASGI app for the bot.

    Parameters
    ----------
    config
        The configuration to use.

    Returns
    -------
    yuyo.AsgiBot
        The ASGI app which can be run using ASGI frameworks
        such as uvicorn (or as a FastAPI sub-app).
    """
    if config is None:
        config = config_.FullConfig.from_env()

    bot = yuyo.AsgiBot(config.tokens.bot, hikari.TokenType.BOT)
    build_from_rest_bot(bot, config=config)
    return bot
