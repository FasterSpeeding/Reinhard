from __future__ import annotations

__all__: typing.Sequence[str] = ["BasicComponent"]

import datetime
import platform
import time
import typing

import psutil
from hikari import __url__ as hikari_url
from hikari import __version__ as hikari_version
from hikari import embeds
from hikari import errors
from tanjun import components
from yuyo import backoff
from yuyo import paginaton

from reinhard.util import constants
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import messages
    from hikari import users
    from tanjun import traits as tanjun_traits


__exports__ = ["BasicComponent"]


class BasicComponent(components.Component):
    def __init__(self) -> None:
        super().__init__()
        self.current_user: typing.Optional[users.OwnUser] = None
        self.help_embeds: typing.Mapping[str, embeds.Embed] = {}
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None
        self.process = psutil.Process()

    def bind_client(self, client: tanjun_traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest, client.dispatch)

    @components.command("about")
    async def about(self, ctx: tanjun_traits.Context) -> None:
        """Get general information about this bot."""
        start_date = datetime.datetime.fromtimestamp(self.process.create_time())
        uptime = datetime.datetime.now() - start_date
        memory_usage = self.process.memory_full_info().uss / 1024 ** 2
        cpu_usage = self.process.cpu_percent() / psutil.cpu_count()
        memory_percent = self.process.memory_percent()

        embed = (
            embeds.Embed(description="An experimental pythonic Hikari bot.", color=constants.EMBED_COLOUR)
            .set_author(
                name=f"Reinhard: Shard {ctx.shard.id} of {ctx.client.shards.shard_count}",
                icon=self.current_user.avatar_url if self.current_user else None,
                url=hikari_url,
            )
            .add_field(name="Uptime", value=str(uptime), inline=True)
            .add_field(
                name="Process",
                value=f"{memory_usage:.2f} MiB ({memory_percent:.0f}%)\n{cpu_usage:.2f}% CPU",
                inline=True,
            )
            .set_footer(
                icon="http://i.imgur.com/5BFecvA.png",
                text=f"Made with Hikari v{hikari_version} (python {platform.python_version()})",
            )
        )

        retry = backoff.Backoff(max_retries=5)
        error_handler = rest_manager.HikariErrorManager(retry, break_on=(errors.NotFoundError, errors.ForbiddenError))

        async for _ in retry:
            with error_handler:
                await ctx.message.reply(embed=embed)
                break

    @components.command("ping")
    async def ping(self, ctx: tanjun_traits.Context) -> None:
        retry = backoff.Backoff(max_retries=5)
        error_handler = rest_manager.HikariErrorManager(retry, break_on=(errors.NotFoundError, errors.ForbiddenError))
        message: typing.Optional[messages.Message] = None
        start_time = 0.0
        async for _ in retry:
            with error_handler:
                start_time = time.perf_counter()
                message = await ctx.message.reply(content="Nyaa master!!!")
                break

        # Assume we can't access the channel anymore if this is still None.
        if message is None:
            return

        time_taken = (time.perf_counter() - start_time) * 1_000
        retry.reset()
        error_handler.clear_rules(break_on=(errors.NotFoundError, errors.ForbiddenError))
        async for _ in retry:
            with error_handler:
                await message.edit(
                    f"PONG\n - REST: {time_taken:.0f}\n - Gateway: {ctx.client.shards.heartbeat_latency * 1_000:.0f}"
                )
                break
