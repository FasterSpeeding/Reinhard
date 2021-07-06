from __future__ import annotations

import typing

import aiohttp
from hikari import config as hikari_config
from tanjun import checks
from tanjun import clients
from tanjun import hooks
from yuyo import paginaton

from . import config as config_
from .components import basic
from .components import external
from .components import moderation
from .components import sudo
from .components import util
from .util import command_hooks
from .util import dependencies

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits
    from tanjun import traits as tanjun_traits


def add_components(client: tanjun_traits.Client, /) -> None:
    client.add_component(basic.BasicComponent())
    client.add_component(external.ExternalComponent())
    client.add_component(moderation.ModerationComponent())
    client.add_component(sudo.SudoComponent())
    client.add_component(util.UtilComponent())


def build(*args: typing.Any) -> hikari_traits.BotAware:
    from hikari.impl import bot as bot_module

    config = config_.load_config()
    bot = bot_module.BotApp(
        config.tokens.bot,
        logs=config.log_level,
        intents=config.intents,
        cache_settings=hikari_config.CacheSettings(components=config.cache),
        # rest_url="https://staging.discord.co/api/v8"
    )
    client = (
        clients.Client(
            bot,
            mention_prefix=config.mention_prefix,
        )
        .set_hooks(hooks.Hooks(on_parser_error=command_hooks.on_parser_error, on_error=command_hooks.on_error))
        .add_prefix(config.prefixes)
        .add_type_dependency(
            aiohttp.ClientSession,
            dependencies.SessionDependency(bot.http_settings, bot.proxy_settings, "Reinhard discord bot"),
        )
        .add_type_dependency(config_.FullConfig, lambda: config)
        .add_type_dependency(config_.Tokens, lambda: config.tokens)
        .add_type_dependency(paginaton.PaginatorPool, dependencies.PaginatorPoolDependency())
    )

    if config.ptf:
        ptf = config.ptf
        client.add_type_dependency(config_.PTFConfig, lambda: ptf)

    if config.owner_only:
        client.add_check(checks.ApplicationOwnerCheck())

    client.metadata["args"] = args
    add_components(client)
    return bot
