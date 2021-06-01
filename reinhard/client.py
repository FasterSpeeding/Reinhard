from __future__ import annotations

import typing

import asyncpg  # type: ignore[import]
from hikari import config as hikari_config
from tanjun import checks
from tanjun import clients
from tanjun import hooks

from . import config as config_
from . import sql
from .components import basic
from .components import external
from .components import moderation
from .components import sudo
from .components import util
from .util import command_hooks

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits
    from tanjun import traits as tanjun_traits


class Client(clients.Client):
    __slots__: typing.Sequence[str] = ("_password", "_host", "_user", "_database", "_port", "sql_pool", "sql_scripts")

    def __init__(
        self,
        events: hikari_traits.EventManagerAware,
        rest: typing.Optional[hikari_traits.RESTAware] = None,
        shard: typing.Optional[hikari_traits.ShardAware] = None,
        cache: typing.Optional[hikari_traits.CacheAware] = None,
        /,
        *,
        password: str,
        host: str,
        user: str,
        database: str,
        port: int,
        prefixes: typing.Optional[typing.Iterable[str]] = None,
        mention_prefix: bool = True,
    ) -> None:
        super().__init__(
            events,
            rest,
            shard,
            cache,
            hooks=hooks.Hooks(parser_error=command_hooks.on_parser_error, on_error=command_hooks.on_error),
            prefixes=prefixes,
            mention_prefix=mention_prefix,
        )
        self._password = password
        self._host = host
        self._user = user
        self._database = database
        self._port = port
        self.sql_pool: typing.Optional[asyncpg.pool.Pool] = None
        self.sql_scripts = sql.CachedScripts(pattern=r"[.*schema.sql]|[*prefix.sql]")

    async def open(self, *, register_listener: bool = True) -> None:
        self.sql_pool = await asyncpg.create_pool(
            password=self._password, host=self._host, user=self._user, database=self._database, port=self._port
        )
        async with self.sql_pool.acquire() as conn:
            await sql.initialise_schema(self.sql_scripts, conn)

        await super().open()


def add_components(client: tanjun_traits.Client, /, *, config: typing.Optional[config_.FullConfig] = None) -> None:
    if config is None:
        config = config_.load_config()

    # TODO: add more hikari config to reinhard config
    http_settings = hikari_config.HTTPSettings()
    proxy_settings = hikari_config.ProxySettings()

    client.add_component(basic.BasicComponent())
    client.add_component(external.ExternalComponent(http_settings, proxy_settings, config.tokens))
    client.add_component(moderation.ModerationComponent())
    client.add_component(sudo.SudoComponent(emoji_guild=config.emoji_guild))
    client.add_component(util.UtilComponent())


def build(*args: typing.Any) -> hikari_traits.BotAware:
    from hikari import intents as intents_  # TODO: handle intents in config
    from hikari.impl import bot as bot_module

    config = config_.load_config()
    bot = bot_module.BotApp(
        config.tokens.bot,
        logs=config.log_level,
        intents=intents_.Intents.ALL,
        cache_settings=hikari_config.CacheSettings(components=config.cache)
        # rest_url="https://staging.discord.co/api/v8"
    )
    client = Client(
        bot,
        password=config.database.password,
        host=config.database.host,
        user=config.database.user,
        database=config.database.database,
        port=config.database.port,
        prefixes=config.prefixes,
        mention_prefix=False,
    )

    if config.owner_only:
        client.add_check(checks.ApplicationOwnerCheck())

    client.metadata["args"] = args
    add_components(client, config=config)
    return bot
