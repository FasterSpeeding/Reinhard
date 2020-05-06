from __future__ import annotations

import asyncio
import contextlib
import io
import re
import textwrap
import time
import traceback
import typing

from hikari import bases
from hikari import embeds
from hikari import errors
from hikari import files

from reinhard.util import command_client
from reinhard.util import command_hooks
from reinhard.util import embed_paginator

if typing.TYPE_CHECKING:
    from hikari import applications as _applications
    from hikari import guilds as _guilds
    from hikari import messages as _messages


exports = ["SudoCluster"]


class SudoCluster(command_client.CommandCluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, hooks=command_client.CommandHooks(on_error=command_hooks.error_hook))
        self.application: typing.Optional[_applications.Application] = None
        self.application_task = None  # todo: annotation?
        for command in self.commands:
            command.register_check(self.owner_check)
        self.paginator_pool = embed_paginator.PaginatorPool(self._components)

    async def load(self) -> None:
        await super().load()
        self.application = await self._components.rest.fetch_my_application_info()
        self.application_task = asyncio.create_task(self.update_application())

    async def update_application(self) -> None:
        while True:
            await asyncio.sleep(1800)
            try:
                self.application = await self._components.rest.fetch_my_application_info()
            except errors.HTTPErrorResponse as exc:
                self.logger.warning("Failed to fetch application object:\n  - %s", exc)

    @command_client.command
    async def error(self, ctx: command_client.Context) -> None:
        raise Exception("This is an exception, get used to it.")

    def owner_check(self, ctx: command_client.Context) -> bool:
        if self.application.team:
            return any(ctx.message.author.id == member_id for member_id in self.application.team.members.keys())
        return ctx.message.author.id == self.application.owner.id

    @command_client.command(greedy=True)  # level=5
    async def echo(self, ctx: command_client.Context, args: str) -> None:
        await ctx.message.reply(content=args)

    async def eval_python_code(
        self, ctx: command_client.Context, code: str
    ) -> typing.Tuple[typing.Sequence[str], int, bool]:
        sub_ctx = {"ctx": ctx, "client": self}
        stdout = io.StringIO()
        stderr = io.StringIO()
        # contextlib.redirect_xxxxx doesn't work properly with contextlib.ExitStack
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                start_time = time.perf_counter()
                try:
                    exec(f"async def __callable__(ctx):\n{textwrap.indent(code, '   ')}", sub_ctx)
                    result = await sub_ctx["__callable__"](ctx)
                    if asyncio.iscoroutine(result):
                        await result
                    failed = False
                except Exception:
                    traceback.print_exc()
                    failed = True
                finally:
                    exec_time = round((time.perf_counter() - start_time) * 1000)

        result = []
        if stdout := stdout.getvalue():
            result.append("- /dev/stdout:")
            result.extend(stdout.splitlines())
        if stderr := stderr.getvalue():
            result.append("- /dev/stderr:")
            result.extend(stderr.splitlines())
        return result or ["..."], exec_time, failed

    @command_client.command(greedy=True, aliases=["exec", "sudo"])
    async def eval(self, ctx: command_client.Context, code: str) -> None:
        code = re.findall(r"```(?:[\w]*\n?)([\s\S(^\\`{3})]*?)\n*```", code)
        if not code:
            await ctx.message.reply(content="Expected a python code block.")
            return

        result, exec_time, failed = await self.eval_python_code(ctx, code[0])
        color = 0xF04747 if failed else 0x43B581
        page_generator = embed_paginator.string_paginator(result, wrapper="```python\n{}\n```", char_limit=2034)
        embed_generator = (
            (
                "",
                embeds.Embed(color=color, description=text, title=f"Eval page {page}").set_footer(
                    text=f"Time taken: {exec_time} ms"
                ),
            )
            for text, page in page_generator
        )
        first_page = next(embed_generator)
        message = await ctx.message.reply(embed=first_page[1])
        await self.paginator_pool.register_message(
            message, generator=embed_generator, first_entry=first_page, authors=[ctx.message.author.id]
        )

    @command_client.command(greedy=True)
    async def steal(self, ctx: command_client.Context, target: bases.Snowflake, args: str = ""):
        """Used to steal emojis from messages content or reactions.

        Pass "r" as the last argument to steal from the message reactions.
        Pass "u" or "c" or "s" to steal from a user custom status.
        """
        if not self._components.config.emoji_guild:
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
                await self._components.rest.create_guild_emoji(
                    guild=self._components.config.emoji_guild,
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


@SudoCluster.error.hooks.set_on_error
async def on_error(ctx: command_client.Context, exception) -> None:
    await ctx.message.reply(content=f"test {exception}")
