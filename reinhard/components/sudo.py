# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__: list[str] = ["sudo_component", "load_sudo", "unload_sudo"]

import ast
import asyncio
import contextlib
import datetime
import inspect
import io
import json
import re
import time
import traceback
import typing
from collections import abc as collections

import hikari
import tanjun
import yuyo
from hikari import traits

from .. import utility

CallbackT = collections.Callable[..., collections.Coroutine[typing.Any, typing.Any, typing.Any]]


@tanjun.as_message_command("error")
async def error_message_command(_: tanjun.abc.Context) -> None:
    """Command used for testing the current error handling."""
    raise Exception("This is an exception, get used to it.")


@tanjun.with_option("raw_embed", "--embed", "-e", converters=json.loads, default=hikari.UNDEFINED)
@tanjun.with_greedy_argument("content", default=hikari.UNDEFINED)
@tanjun.with_parser
@tanjun.as_message_command("echo")
async def echo_command(
    ctx: tanjun.abc.Context,
    content: hikari.UndefinedOr[str],
    raw_embed: hikari.UndefinedOr[dict[str, typing.Any]],
    entity_factory: traits.EntityFactoryAware = tanjun.inject(type=traits.EntityFactoryAware),
) -> None:
    """Command used for getting the bot to mirror a response.

    Arguments:
        * content: The greedy string content the bot should send back. This must be included if `embed` is not.

    Options:
        * embed (--embed, -e): String JSON object of an embed for the bot to send.
    """
    embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED
    if raw_embed is not hikari.UNDEFINED:
        try:
            embed = entity_factory.entity_factory.deserialize_embed(raw_embed)

            if embed.colour is None:
                embed.colour = utility.embed_colour()

        except (TypeError, ValueError) as exc:
            await ctx.respond(content=f"Invalid embed passed: {str(exc)[:1970]}")
            return

    if content or embed:
        await ctx.respond(content=content, embed=embed, component=utility.delete_row(ctx))

    else:
        await ctx.respond(content="No content provided", component=utility.delete_row(ctx))


def _yields_results(*args: io.StringIO) -> collections.Iterator[str]:
    for name, stream in zip(("stdout", "stderr"), args):
        yield f"- /dev/{name}:"
        while lines := stream.readlines(25):
            yield from (line[:-1] for line in lines)


def build_eval_globals(ctx: tanjun.abc.Context, component: tanjun.abc.Component, /) -> dict[str, typing.Any]:
    return {
        "asyncio": asyncio,
        "app": ctx.shards,
        "bot": ctx.shards,
        "client": ctx.client,
        "component": component,
        "ctx": ctx,
        "hikari": hikari,
        "tanjun": tanjun,
    }


async def eval_python_code(
    ctx: tanjun.abc.Context, component: tanjun.abc.Component, code: str
) -> tuple[io.StringIO, io.StringIO, int, bool]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    # contextlib.redirect_xxxxx doesn't work properly with contextlib.ExitStack
    with contextlib.redirect_stdout(stdout):
        with contextlib.redirect_stderr(stderr):
            start_time = time.perf_counter()
            try:
                await eval_python_code_no_capture(ctx, component, code)
                failed = False
            except Exception:
                traceback.print_exc()
                failed = True
            finally:
                exec_time = round((time.perf_counter() - start_time) * 1000)

    stdout.seek(0)
    stderr.seek(0)
    return stdout, stderr, exec_time, failed


async def eval_python_code_no_capture(ctx: tanjun.abc.Context, component: tanjun.abc.Component, code: str) -> None:
    globals_ = build_eval_globals(ctx, component)
    compiled_code = compile(code, "", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    if compiled_code.co_flags & inspect.CO_COROUTINE:
        await eval(compiled_code, globals_)

    else:
        eval(compiled_code, globals_)


def _read_and_keep_index(stream: io.StringIO) -> str:
    index = stream.tell()
    stream.seek(0)
    data = stream.read()
    stream.seek(index)
    return data


# @tanjun.with_option("ephemeral_response", "-e", "--ephemeral", converters=bool, default=False, empty_value=True)
@tanjun.with_option("suppress_response", "-s", "--suppress", converters=bool, default=False, empty_value=True)
@tanjun.with_option("file_output", "-f", "--file-out", "--file", converters=bool, default=False, empty_value=True)
@tanjun.with_parser
@tanjun.as_message_command("eval", "exec")
async def eval_command(
    ctx: tanjun.abc.MessageContext,
    file_output: bool = False,
    # ephemeral_response: bool = False,
    suppress_response: bool = False,
    component: tanjun.abc.Component = tanjun.inject(type=tanjun.abc.Component),
    component_client: yuyo.ComponentClient = tanjun.inject(type=yuyo.ComponentClient),
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

    stdout, stderr, exec_time, failed = await eval_python_code(ctx, component, code[0])

    if file_output:
        await ctx.respond(
            attachments=[
                hikari.Bytes(stdout, "stdout.py", mimetype="text/x-python;charset=utf-8"),
                hikari.Bytes(stderr, "stderr.py", mimetype="text/x-python;charset=utf-8"),
            ],
            component=utility.delete_row(ctx),
        )
        return

    colour = utility.FAILED_COLOUR if failed else utility.PASS_COLOUR
    string_paginator = yuyo.sync_paginate_string(
        _yields_results(stdout, stderr), wrapper="```python\n{}\n```", char_limit=2034
    )
    embed_generator = (
        (
            hikari.UNDEFINED,
            hikari.Embed(colour=colour, description=text, title=f"Eval page {page}").set_footer(
                text=f"Time taken: {exec_time} ms"
            ),
        )
        for text, page in string_paginator
    )
    response_paginator = yuyo.ComponentPaginator(
        embed_generator,
        authors=[ctx.author.id],
        triggers=(
            yuyo.pagination.LEFT_DOUBLE_TRIANGLE,
            yuyo.pagination.LEFT_TRIANGLE,
            yuyo.pagination.STOP_SQUARE,
            yuyo.pagination.RIGHT_TRIANGLE,
            yuyo.pagination.RIGHT_DOUBLE_TRIANGLE,
        ),
        timeout=datetime.timedelta(days=99999),  # TODO: switch to passing None here
    )
    first_response = await response_paginator.get_next_entry()

    async def send_file(ctx_: yuyo.ComponentContext) -> None:
        await ctx_.defer(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
        await ctx.edit_initial_response(component=response_paginator)
        await ctx_.edit_initial_response(
            attachments=[
                hikari.Bytes(_read_and_keep_index(stdout), "stdout.py", mimetype="text/x-python;charset=utf-8"),
                hikari.Bytes(_read_and_keep_index(stderr), "stderr.py", mimetype="text/x-python;charset=utf-8"),
            ],
            component=utility.delete_row(ctx),
        )

    executor = (
        yuyo.MultiComponentExecutor()  # TODO: add authors here
        .add_executor(response_paginator)
        .add_builder(response_paginator)
        .add_action_row()
        .add_button(hikari.ButtonStyle.SECONDARY, send_file)
        .set_emoji("\N{CARD FILE BOX}\N{VARIATION SELECTOR-16}")
        .add_to_container()
        .add_to_parent()
    )

    assert first_response is not None
    content, embed = first_response
    message = await ctx.respond(content=content, embed=embed, components=executor.builders, ensure_result=True)
    component_client.set_executor(message, executor)


sudo_component = tanjun.Component(name="sudo", strict=True).detect_commands()


@tanjun.as_loader
def load_sudo(cli: tanjun.Client, /) -> None:
    cli.add_component(sudo_component.copy().add_check(tanjun.checks.OwnerCheck()))


@tanjun.as_unloader
def unload_sudo(cli: tanjun.Client, /) -> None:
    cli.remove_component_by_name(sudo_component.name)
