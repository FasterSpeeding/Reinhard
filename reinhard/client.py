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
