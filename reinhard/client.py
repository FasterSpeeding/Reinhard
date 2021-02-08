from __future__ import annotations

import typing

import asyncpg
from hikari import config as hikari_config
from tanjun import clients
from tanjun import hooks

from reinhard import config as config_
from reinhard import sql
from reinhard.components import basic
from reinhard.components import external
from reinhard.components import sudo
from reinhard.components import util
from reinhard.util import command_hooks

if typing.TYPE_CHECKING:
    from hikari import traits as hikari_traits
    from tanjun import traits as tanjun_traits


class Client(clients.Client):
    __slots__: typing.Sequence[str] = ("_password", "_host", "_user", "_database", "_port", "sql_pool", "sql_scripts")

    def __init__(
        self,
        dispatch: hikari_traits.DispatcherAware,
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
    ) -> None:
        super().__init__(
            dispatch,
            rest,
            shard,
            cache,
            hooks=hooks.Hooks(parser_error=command_hooks.on_parser_error, on_error=command_hooks.on_error),
            prefixes=prefixes,
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
            password=self._password, host=self._host, user=self._user, database=self._database, port=self._port,
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
    client.add_component(sudo.SudoComponent(emoji_guild=config.emoji_guild))
    client.add_component(util.UtilComponent())
