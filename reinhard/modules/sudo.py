from __future__ import annotations

__all__: typing.Sequence[str] = ["SudoComponent"]

import asyncio
import contextlib
import distutils.util
import io
import json
import re
import textwrap
import time
import traceback
import typing

from hikari import embeds
from hikari import errors as hikari_errors
from hikari import files
from hikari import undefined
from tanjun import checks
from tanjun import commands
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import hooks
from tanjun import parsing
from yuyo import backoff
from yuyo import paginaton

from reinhard.util import command_hooks
from reinhard.util import constants
from reinhard.util import help as help_util
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import messages as messages
    from hikari import presences
    from hikari import snowflakes
    from tanjun import context
    from tanjun import traits as tanjun_Traits


__exports__ = ["SudoComponent"]


@help_util.with_component_name("Sudo Component")
@help_util.with_component_doc("Component used by this bot's owner.")
class SudoComponent(components.Component):
    __slots__: typing.Sequence[str] = ("emoji_guild", "owner_check", "paginator_pool")

    def __init__(self, *, emoji_guild: typing.Optional[snowflakes.Snowflake] = None) -> None:
        super().__init__(
            hooks=hooks.Hooks(error=command_hooks.error_hook, conversion_error=command_hooks.on_conversion_error),
        )
        self.emoji_guild = emoji_guild
        self.owner_check = checks.IsApplicationOwner()
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None
        for command in self.commands:
            if isinstance(command, commands.Command):
                command.add_check(self.owner_check)

    def bind_client(self, client: tanjun_Traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest, client.dispatch)

    async def close(self) -> None:
        if self.paginator_pool is not None:
            await self.paginator_pool.close()

        self.owner_check.close()
        await super().close()

    async def open(self) -> None:
        if self.client is None or self.paginator_pool is None:
            raise RuntimeError("Cannot open this component before binding it to a client.")

        await self.owner_check.open(self.client)
        await self.paginator_pool.open()
        await super().open()

    @help_util.with_command_doc("Command used for testing the current error handling")
    @components.command("error")
    async def error(self, _: context.Context) -> None:
        raise Exception("This is an exception, get used to it.")

    @help_util.with_parameter_doc(
        "--embed | -e", "An optional argument used to specify the json of a embed for the bot to send."
    )
    @help_util.with_command_doc("Command used for getting the bot to mirror a response.")
    @parsing.option("raw_embed", "--embed", "-e", converters=(json.loads,), default=undefined.UNDEFINED)
    @parsing.greedy_argument("content", default=undefined.UNDEFINED)
    @components.command("echo")
    async def echo(
        self,
        ctx: context.Context,
        content: undefined.UndefinedOr[str],
        raw_embed: undefined.UndefinedOr[typing.Dict[str, typing.Any]] = undefined.UNDEFINED,
    ) -> None:
        embed: undefined.UndefinedOr[embeds.Embed] = undefined.UNDEFINED
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )
        if raw_embed is not undefined.UNDEFINED:
            try:
                embed = ctx.client.rest.entity_factory.deserialize_embed(raw_embed)
            except (TypeError, ValueError) as exc:
                async for _ in retry:
                    with error_manager:
                        await ctx.message.reply(content=f"Invalid embed passed: {str(exc)[:1970]}")
                        break

                return

        if content or embed:
            retry.reset()
            async for _ in retry:
                with error_manager:
                    await ctx.message.reply(content=content, embed=embed)
                    break

    @staticmethod
    def _yields_results(*args: io.StringIO) -> typing.Iterator[str]:
        for name, stream in zip("stdout stderr".split(), args):
            yield f"- /dev/{name}:"
            while lines := stream.readlines(25):
                yield from (line[:-1] for line in lines)

    CallbackT = typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, typing.Any]]

    async def eval_python_code(self, ctx: context.Context, code: str) -> typing.Tuple[typing.Iterable[str], int, bool]:
        globals_ = {"ctx": ctx, "client": self}
        stdout = io.StringIO()
        stderr = io.StringIO()
        # contextlib.redirect_xxxxx doesn't work properly with contextlib.ExitStack
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                start_time = time.perf_counter()
                try:
                    exec(f"async def __callable__(ctx):\n{textwrap.indent(code, '   ')}", globals_)
                    callback = typing.cast(self.CallbackT, globals_["__callable__"])

                    if asyncio.iscoroutine(result := await callback(ctx)):
                        await result

                    failed = False
                except BaseException:
                    traceback.print_exc()
                    failed = True
                finally:
                    exec_time = round((time.perf_counter() - start_time) * 1000)

        stdout.seek(0)
        stderr.seek(0)
        return self._yields_results(stdout, stderr), exec_time, failed

    @help_util.with_parameter_doc(
        "--suppress-response | -s", "A optional argument used to disable the bot's post-eval response."
    )
    @help_util.with_command_doc("Dynamically evaluate a script in the bot's environment.")
    @parsing.option(
        "suppress_response",
        "--suppress-response",
        "-s",
        converters=(distutils.util.strtobool,),
        default=False,
        empty_value=True,
    )
    @components.command("eval", "exec", "sudo")
    async def eval(self, ctx: context.Context, suppress_response: bool = False) -> None:
        assert ctx.message.content is not None  # This shouldn't ever be the case in a command client.
        code = re.findall(r"```(?:[\w]*\n?)([\s\S(^\\`{3})]*?)\n*```", ctx.message.content)
        if not code:
            raise tanjun_errors.CommandError("Expected a python code block.")

        result, exec_time, failed = await self.eval_python_code(ctx, code[0])
        color = constants.FAILED_COLOUR if failed else constants.PASS_COLOUR
        if suppress_response:
            return

        string_paginator = paginaton.string_paginator(iter(result), wrapper="```python\n{}\n```", char_limit=2034)
        embed_generator = (
            (
                undefined.UNDEFINED,
                embeds.Embed(color=color, description=text, title=f"Eval page {page}").set_footer(
                    text=f"Time taken: {exec_time} ms"
                ),
            )
            async for text, page in string_paginator
        )
        response_paginator = paginaton.Paginator(
            ctx.client.rest, ctx.message.channel_id, embed_generator, authors=[ctx.message.author.id]
        )
        message = await response_paginator.open()
        self.paginator_pool.add_paginator(message, response_paginator)

    # @components.command
    async def steal(self, ctx: context.Context, target: snowflakes.Snowflake, *args: str) -> None:
        """Used to steal emojis from messages content or reactions.

        Pass "r" as the last argument to steal from the message reactions.
        Pass "u" or "c" or "s" to steal from a user custom status.
        """
        if not self.emoji_guild:
            await ctx.message.reply(content="Target emoji guild isn't set for this bot.")
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
            message = await ctx.client.rest.rest.fetch_message(channel, target)
        except (hikari_errors.ForbiddenError, hikari_errors.NotFoundError) as exc:
            await ctx.message.reply(content=str(exc))
            return

        def get_info_from_string(emojis_objs: typing.Sequence[str]) -> typing.Tuple[str, str]:
            for emoji in emojis_objs:
                animated, emoji_name, emoji_id = re.search(r"(?:<)(a?)(?::)(\w+)(?::)(\d+)(?:>)", emoji).groups()
                yield emoji_name, f"{emoji_id}.{'gif' if animated else 'png'}"

        def attributed_with_emoji(
            objs: typing.Sequence[typing.Union[messages.Reaction, presences.Activity]]
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
                await ctx.client.rest.rest.create_emoji(
                    guild=self.emoji_guild, reason=reason, name=name, image=files.URL(url),
                )
            except (hikari_errors.ForbiddenError, hikari_errors.BadRequestError) as exc:
                exceptions.append(f"{name}|{url}: {exc}")
            finally:
                count += 1

        if exceptions:
            await ctx.message.reply(
                content=f"{len(exceptions)} out of {count} emoji(s) failed: ```python\n{exceptions}```"
            )
        else:
            await ctx.message.reply(content=f":thumbsup: ({count})")
