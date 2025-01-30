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

import datetime
import logging
import pathlib
import typing

import hikari
import tanchan.components.config
import tanjun
import yuyo
import yuyo.asgi
import yuyo.modals

from . import config as config_
from . import utility

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits

    class _GatewayBotProto(
        hikari.EventManagerAware, hikari.RESTAware, hikari.ShardAware, hikari.Runnable, typing.Protocol
    ):
        """Protocol of a cacheless Hikari Gateway bot."""


def _rukari(config: config_.FullConfig | None) -> _GatewayBotProto | None:
    try:
        import rukari  # type: ignore  # noqa: PGH003

    except ImportError:
        return None

    print("Initiating with Rukari")  # noqa: T201
    if config is None:
        config = config_.FullConfig.from_env()

    bot: hikari.ShardAware = rukari.Bot(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        config.tokens.bot, intents=config.intents
    )
    assert isinstance(bot, hikari.EventManagerAware)
    assert isinstance(bot, hikari.RESTAware)
    assert isinstance(bot, hikari.ShardAware)
    assert isinstance(bot, hikari.Runnable)

    logging.basicConfig(level=config.log_level or logging.INFO)
    return bot


def build_gateway_bot(*, config: config_.FullConfig | None = None) -> tuple[_GatewayBotProto, tanjun.Client]:
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

    bot = _rukari(config)

    if not bot:
        print("Initiating with standard Hikari impl")  # noqa: T201
        bot = hikari.GatewayBot(
            config.tokens.bot,
            logs=config.log_level,
            intents=config.intents,
            cache_settings=hikari.impl.CacheSettings(components=config.cache),
            # Staging url = https://staging.discord.co/api/v8
        )

    client = _build(
        tanjun.Client.from_gateway_bot(
            bot,
            mention_prefix=config.mention_prefix,
            declare_global_commands=False if config.hot_reload else config.declare_global_commands,
        ),
        config,
    )
    return bot, client


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
    return bot, _build_from_rest_bot(config, bot)


# Backwards compat with delete buttons from before the logic was moved out to
# Tanchan since this changed the custom ID.
_OLD_DELETE_BUTTON = yuyo.components.SingleExecutor(
    "AUTHOR_DELETE_BUTTON", tanchan.components.buttons.on_delete_button.execute
)


def _build(client: tanjun.Client, config: config_.FullConfig) -> tanjun.Client:
    (
        client.set_hooks(tanjun.AnyHooks().set_on_parser_error(utility.on_parser_error).set_on_error(utility.on_error))
        .add_prefix(config.prefixes)
        .set_type_dependency(config_.FullConfig, config)
        .set_type_dependency(config_.Tokens, config.tokens)
    )

    tanchan.components.config.Config(enable_slash_command=True, eval_guild_ids=config.eval_guilds).add_to_client(client)
    yuyo.ComponentClient.from_tanjun(client).register_executor(_OLD_DELETE_BUTTON)
    yuyo.ModalClient.from_tanjun(client)
    # TODO: support passing raw modules here?
    client.load_modules("tanchan.components")
    assert isinstance(client.rest.http_settings, hikari.impl.HTTPSettings)
    assert isinstance(client.rest.proxy_settings, hikari.impl.ProxySettings)
    utility.SessionManager(
        client.rest.http_settings, client.rest.proxy_settings, "Reinhard discord bot"
    ).load_into_client(client)

    if config.ptf:
        ptf = config.ptf
        client.set_type_dependency(config_.PTFConfig, ptf)

    if config.owner_only:
        client.add_check(tanjun.checks.OwnerCheck(halt_execution=True))

    if client.shards:
        yuyo.ReactionClient.from_tanjun(client)

    components_dir = pathlib.Path() / "reinhard" / "components"
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

    return client


def _build_from_rest_bot(config: config_.FullConfig, bot: hikari_traits.RESTBotAware, /) -> tanjun.Client:
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
    return _build(
        tanjun.Client.from_rest_bot(
            bot,
            declare_global_commands=False if config.hot_reload else config.declare_global_commands,
            bot_managed=True,
        ),
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
    _build_from_rest_bot(config, bot)
    return bot
