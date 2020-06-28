from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import textwrap
import time
import traceback
import typing

from hikari import bases
from hikari import embeds
from hikari import errors
from hikari import files
from tanjun import clusters
from tanjun import commands
from tanjun import decorators
from tanjun import parser

from .util import command_hooks
from .util import constants
from .util import paginators

if typing.TYPE_CHECKING:
    from hikari import applications as _applications
    from hikari import guilds as _guilds
    from hikari import messages as _messages
    from tanjun import client


exports = ["SudoCluster"]


class SudoCluster(clusters.Cluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            *args,
            **kwargs,
            hooks=commands.Hooks(
                on_error=command_hooks.error_hook, on_conversion_error=command_hooks.on_conversion_error
            ),
        )
        self.application: typing.Optional[_applications.Application] = None
        self.application_task = None  # todo: annotation?
        for command in self.commands:
            command.register_check(self.owner_check)
        self.paginator_pool = paginators.PaginatorPool(self.components)

    async def load(self) -> None:
        self.application = await self.components.rest.fetch_my_application_info()
        self.application_task = asyncio.create_task(self.update_application())
        await super().load()

    async def update_application(self) -> None:
        while True:
            await asyncio.sleep(1800)
            try:
                self.application = await self.components.rest.fetch_my_application_info()
            except errors.HTTPErrorResponse as exc:
                self.logger.warning("Failed to fetch application object:\n - %r", exc)

    @decorators.command
    async def error(self, ctx: commands.Context) -> None:
        raise Exception("This is an exception, get used to it.")

    def owner_check(self, ctx: commands.Context) -> bool:
        if self.application.team:
            return any(ctx.message.author.id == member_id for member_id in self.application.team.members.keys())
        return ctx.message.author.id == self.application.owner.id

    @decorators.command(greedy="content")
    async def echo(self, ctx: commands.Context, content: str, embed: str = ...) -> None:
        if embed is not ...:
            try:
                embed = embeds.Embed.deserialize(json.loads(embed))
            except (TypeError, ValueError) as exc:
                await ctx.message.safe_reply(content=f"Invalid embed passed: {exc}")
                return

        if content or embed:
            await ctx.message.reply(content=content, embed=embed)  # TODO: enforce greedy isn't empty resource

    @staticmethod
    def _yields_results(stdout: io.StringIO, stderr: io.StringIO):
        yield "- /dev/stdout:"
        while lines := stdout.readlines(25):
            yield from lines
        yield "- /dev/stderr:"
        while lines := stderr.readlines(25):
            yield from lines

    async def eval_python_code(self, ctx: commands.Context, code: str) -> typing.Tuple[typing.Iterable[str], int, bool]:
        globals_ = {"ctx": ctx, "client": self}
        stdout = io.StringIO()
        stderr = io.StringIO()
        # contextlib.redirect_xxxxx doesn't work properly with contextlib.ExitStack
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                start_time = time.perf_counter()
                try:
                    exec(f"async def __callable__(ctx):\n{textwrap.indent(code, '   ')}", globals_)
                    result = await globals_["__callable__"](ctx)
                    if asyncio.iscoroutine(result):
                        await result
                    failed = False
                except Exception:
                    traceback.print_exc()
                    failed = True
                finally:
                    exec_time = round((time.perf_counter() - start_time) * 1000)

        stdout.seek(0)
        stderr.seek(0)
        return self._yields_results(stdout, stderr), exec_time, failed

    @decorators.command(aliases=["exec", "sudo"])
    @parser.parameter(
        converters=(bool,),
        default=False,
        empty_default=True,
        key="suppress_response",
        names=("--suppress-response", "-s"),
    )
    async def eval(self, ctx: commands.Context, suppress_response: bool = False) -> None:
        code = re.findall(r"```(?:[\w]*\n?)([\s\S(^\\`{3})]*?)\n*```", ctx.message.content)
        if not code:
            await ctx.message.reply(content="Expected a python code block.")
            return

        result, exec_time, failed = await self.eval_python_code(ctx, code[0])
        color = constants.FAILED_COLOUR if failed else constants.PASS_COLOUR
        if suppress_response:
            return

        embed_generator = (
            (
                "",
                embeds.Embed(color=color, description=text, title=f"Eval page {page}").set_footer(
                    text=f"Time taken: {exec_time} ms"
                ),
            )
            for text, page in paginators.string_paginator(result, wrapper="```python\n{}\n```", char_limit=2034)
        )
        first_page = next(embed_generator)
        message = await ctx.message.reply(embed=first_page[1])
        await self.paginator_pool.register_message(
            message,
            paginator=paginators.ResponsePaginator(
                generator=embed_generator, first_entry=first_page, authors=[ctx.message.author.id]
            ),
        )

    @decorators.command()
    async def steal(self, ctx: commands.Context, target: bases.Snowflake, *args: str):
        """Used to steal emojis from messages content or reactions.

        Pass "r" as the last argument to steal from the message reactions.
        Pass "u" or "c" or "s" to steal from a user custom status.
        """
        if not self.components.config.emoji_guild:
            await ctx.message.reply(content="The target emoji guild not set for this bot.")
            return
        channel = None
        user = None
        # if False and args and args.split(" ")[-1].lower() in ("c", "u", "s"):  # TODO: state
        #    Get the target user for their custom status.
        #    user = self.state.users.get(target)
        #    if not user:
        #        raise CommandError("Couldn't find target user.")

        # Get the target channel.
        channel_target = re.match(r"\d+", args.split(" ", 1)[0])
        if channel_target:
            channel = int(channel_target.string)
        else:
            channel = ctx.message.channel_id
        if not channel:
            await ctx.message.reply(content="Channel not found.")
            return

        try:
            message = await ctx.components.rest.fetch_message(channel, target)
        except (errors.Forbidden, errors.NotFound) as exc:
            await ctx.message.reply(content=str(exc))
            return

        def get_info_from_string(emojis_objs: typing.Sequence[str]) -> typing.Tuple[str, str]:
            for emoji in emojis_objs:
                animated, emoji_name, emoji_id = re.search(r"(?:<)(a?)(?::)(\w+)(?::)(\d+)(?:>)", emoji).groups()
                yield emoji_name, f"{emoji_id}.{'gif' if animated else 'png'}"

        def attributed_with_emoji(
            objs: typing.Sequence[typing.Union[_messages.Reaction, _guilds.PresenceActivity]]
        ) -> typing.Tuple[str, str]:
            for obj in objs:
                if not obj.emoji or not obj.emoji.id:
                    continue
                yield obj.emoji.name, f"{obj.emoji.id}.{'gif' if obj.emoji.animated else 'png'}"

        if args and args.split(" ")[-1].lower() == "r":
            # Form a generator of the emojis from the message's reactions.
            results = attributed_with_emoji(message.reactions)
        elif user:
            if not user.presence:
                await ctx.message.reply(content="Target user is currently invisible.")
                return
            # Form a generator of the user's activities for stealing emoji.
            results = attributed_with_emoji(user.presence.activities)
        else:
            # Extract emojis from message contents.
            emojis = re.findall(r"<a?:\w+:\d+>", message.content)
            if not emojis:
                await ctx.message.reply(content="No emojis found in message.")
                return

            results = get_info_from_string(emojis)

        exceptions = []
        count = 0
        reason = "Stolen from "
        if channel:
            reason += f"msg {channel}:"
        else:
            reason += "custom status "
        reason += str(target)

        for name, path in results:
            url = f"https://cdn.discordapp.com/emojis/{path}?v=1"
            try:
                await self.components.rest.create_guild_emoji(
                    guild=self.components.config.emoji_guild,
                    reason=reason,
                    name=name,
                    image=files.WebResourceStream("", url),
                )
            except (errors.Forbidden, errors.BadRequest) as exc:
                exceptions.append(f"{name}|{url}: {exc}")
            finally:
                count += 1

        if exceptions:
            await ctx.message.reply(
                content=f"{len(exceptions)} out of {count} emoji(s) failed: ```python\n{exceptions}```"
            )
        else:
            await ctx.message.reply(content=f":thumbsup: ({count})")


def setup(bot: client.Client):
    bot.register_cluster(SudoCluster)
