from __future__ import annotations

__all__: typing.Sequence[str] = ["SudoComponent"]

import ast
import asyncio
import contextlib
import inspect
import io
import json
import re
import time
import traceback
import typing
from builtins import str

import hikari
from hikari import embeds
from hikari import emojis
from hikari import errors as hikari_errors
from hikari import snowflakes
from hikari import undefined
from tanjun import checks as checks_
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import parsing
from yuyo import backoff
from yuyo import paginaton

from ..util import constants
from ..util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import messages
    from tanjun import traits as tanjun_traits


CallbackT = typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, typing.Any]]


class SudoComponent(components.Component):
    """Component used by this bot's owner."""

    __slots__: typing.Sequence[str] = ("emoji_guild", "owner_check", "paginator_pool")

    def __init__(
        self,
        *,
        checks: typing.Optional[typing.Iterable[tanjun_traits.CheckT]] = None,
        emoji_guild: typing.Optional[snowflakes.Snowflake] = None,
        hooks: typing.Optional[tanjun_traits.Hooks] = None,
    ) -> None:
        self.owner_check = checks_.ApplicationOwnerCheck()
        super().__init__(checks=checks, hooks=hooks)
        self.emoji_guild = emoji_guild
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None
        self.add_check(self.owner_check)

    def bind_client(self, client: tanjun_traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest_service, client.event_service)

    async def close(self) -> None:
        await super().close()
        if self.paginator_pool is not None:
            await self.paginator_pool.close()

        self.owner_check.close()

    async def open(self) -> None:
        if self.client is None or self.paginator_pool is None:
            raise RuntimeError("Cannot open this component before binding it to a client.")

        await self.owner_check.open(self.client)
        await self.paginator_pool.open()
        await super().open()

    @components.as_command("error")
    async def error(self, _: tanjun_traits.Context) -> None:
        """Command used for testing the current error handling."""
        raise Exception("This is an exception, get used to it.")

    @parsing.with_option("raw_embed", "--embed", "-e", converters=json.loads, default=undefined.UNDEFINED)
    @parsing.with_greedy_argument("content", default=undefined.UNDEFINED)
    @parsing.with_parser
    @components.as_command("echo")
    async def echo(
        self,
        ctx: tanjun_traits.Context,
        content: undefined.UndefinedOr[str],
        raw_embed: undefined.UndefinedOr[typing.Dict[str, typing.Any]],
    ) -> None:
        """Command used for getting the bot to mirror a response.

        Arguments:
            * content: The greedy string content the bot should send back. This must be included if `embed` is not.

        Options:
            * embed (--embed, -e): String JSON object of an embed for the bot to send.
        """
        embed: undefined.UndefinedOr[embeds.Embed] = undefined.UNDEFINED
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )
        if raw_embed is not undefined.UNDEFINED:
            try:
                embed = ctx.rest_service.entity_factory.deserialize_embed(raw_embed)

                if embed.colour is None:
                    embed.colour = constants.embed_colour()

            except (TypeError, ValueError) as exc:
                await error_manager.try_respond(ctx, content=f"Invalid embed passed: {str(exc)[:1970]}")
                return

        if content or embed:
            await error_manager.try_respond(ctx, content=content, embed=embed)

    @staticmethod
    def _yields_results(*args: io.StringIO) -> typing.Iterator[str]:
        for name, stream in zip("stdout stderr".split(), args):
            yield f"- /dev/{name}:"
            while lines := stream.readlines(25):
                yield from (line[:-1] for line in lines)

    def build_eval_globals(self, ctx: tanjun_traits.Context, /) -> typing.Dict[str, typing.Any]:
        return {
            "asyncio": asyncio,
            "app": ctx.rest_service,
            "bot": ctx.rest_service,
            "client": self.client,
            "component": self,
            "ctx": ctx,
            "hikari": hikari,
        }

    async def eval_python_code(
        self, ctx: tanjun_traits.Context, code: str
    ) -> typing.Tuple[typing.Iterable[str], int, bool]:
        globals_ = self.build_eval_globals(ctx)
        stdout = io.StringIO()
        stderr = io.StringIO()
        # contextlib.redirect_xxxxx doesn't work properly with contextlib.ExitStack
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                start_time = time.perf_counter()
                try:
                    compiled_code = compile(code, "", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                    if compiled_code.co_flags & inspect.CO_COROUTINE:
                        await eval(compiled_code, globals_)

                    else:
                        eval(compiled_code, globals_)

                    failed = False
                except BaseException:
                    traceback.print_exc()
                    failed = True
                finally:
                    exec_time = round((time.perf_counter() - start_time) * 1000)

        stdout.seek(0)
        stderr.seek(0)
        return self._yields_results(stdout, stderr), exec_time, failed

    async def eval_python_code_no_capture(self, ctx: tanjun_traits.Context, code: str) -> None:
        globals_ = self.build_eval_globals(ctx)
        try:
            compiled_code = compile(code, "", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            if compiled_code.co_flags & inspect.CO_COROUTINE:
                await eval(compiled_code, globals_)

            else:
                eval(compiled_code, globals_)

        except BaseException:
            traceback.print_exc()
            pass

    @parsing.with_option("suppress_response", "-s", "--suppress", converters=bool, default=False, empty_value=True)
    @parsing.with_parser
    @components.as_command("eval", "exec", "sudo")
    async def eval(self, ctx: tanjun_traits.Context, suppress_response: bool = False) -> None:
        """Dynamically evaluate a script in the bot's environment.

        This can only be used by the bot's owner.

        Arguments:
            * code: Greedy multi-line string argument of the code to execute. This should be in a code block.
            * suppress_response (-s, --suppress): Whether to suppress this command's confirmation response.
                This defaults to false and will be set to true if no value is provided.
        """
        assert ctx.message.content is not None  # This shouldn't ever be the case in a command client.
        code = re.findall(r"```(?:[\w]*\n?)([\s\S(^\\`{3})]*?)\n*```", ctx.message.content)
        if not code:
            raise tanjun_errors.CommandError("Expected a python code block.")

        if suppress_response:
            await self.eval_python_code_no_capture(ctx, code[0])
            return

        result, exec_time, failed = await self.eval_python_code(ctx, code[0])
        colour = constants.FAILED_COLOUR if failed else constants.PASS_COLOUR
        string_paginator = paginaton.string_paginator(iter(result), wrapper="```python\n{}\n```", char_limit=2034)
        embed_generator = (
            (
                undefined.UNDEFINED,
                embeds.Embed(colour=colour, description=text, title=f"Eval page {page}").set_footer(
                    text=f"Time taken: {exec_time} ms"
                ),
            )
            async for text, page in string_paginator
        )
        response_paginator = paginaton.Paginator(
            ctx.rest_service, ctx.message.channel_id, embed_generator, authors=[ctx.message.author.id]
        )
        message = await response_paginator.open()
        assert self.paginator_pool is not None
        self.paginator_pool.add_paginator(message, response_paginator)

    @components.as_command("commands")
    async def commands_command(self, ctx: tanjun_traits.Context) -> None:
        commands = (
            f"  {type(component).__name__}: " + ", ".join(map(repr, component.commands))
            for component in ctx.client.components
        )
        error_manager = rest_manager.HikariErrorManager(
            break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )
        await error_manager.try_respond(ctx, content="Loaded commands\n" + "\n".join(commands))

    @components.as_group("note", "notes")
    async def note(self, ctx: tanjun_traits.Context) -> None:
        await ctx.message.respond("You have zero tags")

    @note.with_command("add")
    async def note_add(self, ctx: tanjun_traits.Context) -> None:
        await ctx.message.respond("todo")

    @note.with_command("remove")
    async def note_remove(self, ctx: tanjun_traits.Context) -> None:
        await ctx.message.respond("todo")

    async def steal(self, ctx: tanjun_traits.Context, target: snowflakes.Snowflake, *args: str) -> None:
        # TODO: emoji steal command
        ...
