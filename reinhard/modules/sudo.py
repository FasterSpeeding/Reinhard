from __future__ import annotations

__all__: typing.Sequence[str] = ["SudoComponent"]

import asyncio
import contextlib
import io
import json
import re
import textwrap
import time
import traceback
import typing

from hikari import embeds
from hikari import errors as hikari_errors
from hikari import undefined
from tanjun import checks
from tanjun import commands
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import parsing
from yuyo import backoff
from yuyo import paginaton

from reinhard.util import constants
from reinhard.util import help as help_util
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import snowflakes
    from tanjun import context
    from tanjun import traits as tanjun_traits


__exports__ = ["SudoComponent"]
CallbackT = typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, typing.Any]]


@help_util.with_component_name("Sudo Component")
@help_util.with_component_doc("Component used by this bot's owner.")
class SudoComponent(components.Component):
    __slots__: typing.Sequence[str] = ("emoji_guild", "owner_check", "paginator_pool")

    def __init__(
        self,
        *,
        emoji_guild: typing.Optional[snowflakes.Snowflake] = None,
        hooks: typing.Optional[tanjun_traits.Hooks] = None,
    ) -> None:
        super().__init__(hooks=hooks)
        self.emoji_guild = emoji_guild
        self.owner_check = checks.IsApplicationOwner()
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None
        for command in self.commands:
            if isinstance(command, commands.Command):
                command.add_check(self.owner_check)

    def bind_client(self, client: tanjun_traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest_service, client.dispatch_service)

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
                embed = ctx.client.rest_service.entity_factory.deserialize_embed(raw_embed)
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
                    callback = typing.cast(CallbackT, globals_["__callable__"])

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
        "suppress_response", "--suppress-response", "-s", converters=(bool,), default=False, empty_value=True,
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
            ctx.client.rest_service, ctx.message.channel_id, embed_generator, authors=[ctx.message.author.id]
        )
        message = await response_paginator.open()
        self.paginator_pool.add_paginator(message, response_paginator)

    async def steal(self, ctx: context.Context, target: snowflakes.Snowflake, *args: str) -> None:
        # TODO: emoji steal command
        ...
