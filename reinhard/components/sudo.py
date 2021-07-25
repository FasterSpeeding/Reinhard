from __future__ import annotations

__all__: typing.Sequence[str] = ["sudo_component", "load_component"]

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

import hikari
import tanjun
from hikari import embeds
from hikari import errors as hikari_errors
from hikari import files
from hikari import traits as hikari_traits
from hikari import undefined
from yuyo import backoff
from yuyo import paginaton

from ..util import constants
from ..util import help as help_util
from ..util import rest_manager

CallbackT = typing.Callable[..., typing.Coroutine[typing.Any, typing.Any, typing.Any]]

sudo_component = tanjun.Component()
help_util.with_docs(sudo_component, "Sudo commands", "Component used by this bot's owner.")


@sudo_component.with_message_command
@tanjun.as_message_command("error")
async def error_command(_: tanjun.traits.MessageContext) -> None:
    """Command used for testing the current error handling."""
    raise Exception("This is an exception, get used to it.")


@sudo_component.with_message_command
@tanjun.with_option("raw_embed", "--embed", "-e", converters=json.loads, default=undefined.UNDEFINED)
@tanjun.with_greedy_argument("content", default=undefined.UNDEFINED)
@tanjun.with_parser
@tanjun.as_message_command("echo")
async def echo_command(
    ctx: tanjun.traits.MessageContext,
    content: undefined.UndefinedOr[str],
    raw_embed: undefined.UndefinedOr[typing.Dict[str, typing.Any]],
    entity_factory: hikari_traits.EntityFactoryAware = tanjun.injected(type=hikari_traits.EntityFactoryAware),
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
            embed = entity_factory.entity_factory.deserialize_embed(raw_embed)

            if embed.colour is None:
                embed.colour = constants.embed_colour()

        except (TypeError, ValueError) as exc:
            await error_manager.try_respond(ctx, content=f"Invalid embed passed: {str(exc)[:1970]}")
            return

    if content or embed:
        await error_manager.try_respond(ctx, content=content, embed=embed)


def _yields_results(*args: io.StringIO) -> typing.Iterator[str]:
    for name, stream in zip("stdout stderr".split(), args):
        yield f"- /dev/{name}:"
        while lines := stream.readlines(25):
            yield from (line[:-1] for line in lines)


def build_eval_globals(
    ctx: tanjun.traits.MessageContext, component: tanjun.traits.Component, /
) -> typing.Dict[str, typing.Any]:
    return {
        "asyncio": asyncio,
        "app": ctx.shards,
        "bot": ctx.shards,
        "client": ctx.client,
        "component": component,
        "ctx": ctx,
        "hikari": hikari,
    }


async def eval_python_code(
    ctx: tanjun.traits.MessageContext, component: tanjun.traits.Component, code: str
) -> typing.Tuple[typing.Iterable[str], int, bool]:
    globals_ = build_eval_globals(ctx, component)
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
    return _yields_results(stdout, stderr), exec_time, failed


async def eval_python_code_no_capture(
    ctx: tanjun.traits.MessageContext, component: tanjun.traits.Component, code: str
) -> None:
    globals_ = build_eval_globals(ctx, component)
    try:
        compiled_code = compile(code, "", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
        if compiled_code.co_flags & inspect.CO_COROUTINE:
            await eval(compiled_code, globals_)

        else:
            eval(compiled_code, globals_)

    except BaseException:
        traceback.print_exc()
        pass


@sudo_component.with_message_command
@tanjun.with_option("suppress_response", "-s", "--suppress", converters=bool, default=False, empty_value=True)
@tanjun.with_option("file_output", "-f", "--file-out", "--file", converters=bool, default=False, empty_value=True)
@tanjun.with_parser
@tanjun.as_message_command("eval", "exec")
async def eval_command(
    ctx: tanjun.traits.MessageContext,
    file_output: bool = False,
    suppress_response: bool = False,
    component: tanjun.traits.Component = tanjun.injected(type=tanjun.traits.Component),
    paginator_pool: paginaton.PaginatorPool = tanjun.injected(type=paginaton.PaginatorPool),
    rest_service: hikari_traits.RESTAware = tanjun.injected(type=hikari_traits.RESTAware),
) -> None:
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
        raise tanjun.CommandError("Expected a python code block.")

    if suppress_response:
        await eval_python_code_no_capture(ctx, component, code[0])
        return

    result, exec_time, failed = await eval_python_code(ctx, component, code[0])

    if file_output:
        await ctx.message.respond(
            attachment=files.Bytes("\n".join(result), "output.py", mimetype="text/x-python;charset=utf-8")
        )
        return

    colour = constants.FAILED_COLOUR if failed else constants.PASS_COLOUR
    string_paginator = paginaton.string_paginator(iter(result), wrapper="```python\n{}\n```", char_limit=2034)
    embed_generator = (
        (
            undefined.UNDEFINED,
            embeds.Embed(colour=colour, description=text, title=f"Eval page {page}").set_footer(
                text=f"Time taken: {exec_time} ms"
            ),
        )
        for text, page in string_paginator
    )
    response_paginator = paginaton.Paginator(
        rest_service,
        ctx.channel_id,
        embed_generator,
        authors=[ctx.author.id],
        triggers=(
            paginaton.LEFT_DOUBLE_TRIANGLE,
            paginaton.LEFT_TRIANGLE,
            paginaton.STOP_SQUARE,
            paginaton.RIGHT_TRIANGLE,
            paginaton.RIGHT_DOUBLE_TRIANGLE,
        ),
    )
    message = await response_paginator.open()
    paginator_pool.add_paginator(message, response_paginator)


@sudo_component.with_message_command
@tanjun.as_message_command("commands")
async def commands_command(ctx: tanjun.traits.MessageContext) -> None:
    commands = (
        f"  {type(component).__name__}: " + ", ".join(map(repr, component.message_commands))
        for component in ctx.client.components
    )
    error_manager = rest_manager.HikariErrorManager(
        break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
    )
    await error_manager.try_respond(ctx, content="Loaded commands\n" + "\n".join(commands))


@sudo_component.with_message_command
@tanjun.as_message_command_group("note", "notes")
async def note_command(ctx: tanjun.traits.MessageContext) -> None:
    await ctx.message.respond("You have zero tags")


@note_command.with_command
@tanjun.as_message_command("add")
async def note_add_command(ctx: tanjun.traits.MessageContext) -> None:
    await ctx.message.respond("todo")


@note_command.with_command
@tanjun.as_message_command("remove")
async def note_remove_command(ctx: tanjun.traits.MessageContext) -> None:
    await ctx.message.respond("todo")


@tanjun.as_loader
def load_component(cli: tanjun.traits.Client, /) -> None:
    cli.add_component(sudo_component.copy().add_check(tanjun.checks.ApplicationOwnerCheck()))
