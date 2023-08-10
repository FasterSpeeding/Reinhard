# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2023, Faster Speeding
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

__all__: list[str] = ["load_sudo"]

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
from collections import abc as collections
from typing import Annotated

import alluka
import hikari
import tanjun
import yuyo
from hikari import traits
from tanjun.annotations import Bool
from tanjun.annotations import Converted
from tanjun.annotations import Flag
from tanjun.annotations import Greedy
from tanjun.annotations import Positional
from tanjun.annotations import Str

from .. import utility

CallbackT = collections.Callable[..., collections.Coroutine[typing.Any, typing.Any, typing.Any]]


@tanjun.as_message_command("error")
async def error_message_command(_: tanjun.abc.Context) -> None:
    """Command used for testing the current error handling."""
    raise Exception("This is an exception, get used to it.")  # noqa: TC002


@tanjun.annotations.with_annotated_args
@tanjun.as_message_command("echo")
async def echo_command(
    ctx: tanjun.abc.Context,
    entity_factory: alluka.Injected[traits.EntityFactoryAware],
    # TODO: Greedy should implicitly mark arguments as positional.
    content: typing.Annotated[hikari.UndefinedOr[Str], Positional(), Greedy()] = hikari.UNDEFINED,
    raw_embed: typing.Annotated[
        hikari.UndefinedOr[typing.Any], Flag(aliases=["--embed", "-e"]), Converted(json.loads)
    ] = hikari.UNDEFINED,
) -> None:
    """Command used for getting the bot to mirror a response."""
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


async def eval_python_code(
    client: tanjun.abc.Client,
    ctx: tanjun.abc.Context | yuyo.ComponentContext | yuyo.ModalContext,
    code: str,
    /,
    *,
    component: tanjun.abc.Component | None = None,
) -> tuple[io.StringIO, io.StringIO, int, bool]:
    stdout = io.StringIO()
    stderr = io.StringIO()

    stack = contextlib.ExitStack()
    stack.enter_context(contextlib.redirect_stdout(stdout))
    stack.enter_context(contextlib.redirect_stderr(stderr))

    start_time = time.perf_counter()
    try:
        with stack:
            await eval_python_code_no_capture(client, ctx, code, component=component)

        failed = False
    except Exception:
        traceback.print_exc(file=stderr)
        failed = True
    finally:
        exec_time = round((time.perf_counter() - start_time) * 1000)

    stdout.seek(0)
    stderr.seek(0)
    return stdout, stderr, exec_time, failed


async def eval_python_code_no_capture(
    client: tanjun.abc.Client,
    ctx: tanjun.abc.Context | yuyo.ComponentContext | yuyo.ModalContext,
    code: str,
    /,
    *,
    component: tanjun.abc.Component | None = None,
    file_name: str = "<string>",
) -> None:
    globals_ = {
        "app": ctx.shards,
        "asyncio": asyncio,
        "bot": ctx.shards,
        "client": client,
        "component": component,
        "ctx": ctx,
        "hikari": hikari,
        "tanjun": tanjun,
    }
    compiled_code = compile(code, file_name, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    if compiled_code.co_flags & inspect.CO_COROUTINE:
        await eval(compiled_code, globals_)  # noqa: S307 - insecure function

    else:
        eval(compiled_code, globals_)  # noqa: S307 - insecure function


def _bytes_from_io(
    stream: io.StringIO, name: str, mimetype: str | None = "text/x-python;charset=utf-8"
) -> hikari.Bytes:
    index = stream.tell()
    stream.seek(0)
    data = stream.read()
    stream.seek(index)
    return hikari.Bytes(data, name, mimetype=mimetype)


EVAL_MODAL_ID = "UPDATE_EVAL"
CODEBLOCK_REGEX = re.compile(r"```(?:[\w]*\n?)([\s\S(^\\`{3})]*?)\n*```")
STATE_FILE_NAME = "EVAL_STATE"
EDIT_BUTTON_EMOJI = "\N{SQUARED NEW}"


async def _check_owner(
    client: tanjun.abc.Client,
    authors: tanjun.dependencies.AbstractOwners,
    ctx: yuyo.ComponentContext | yuyo.ModalContext,
) -> bool:
    state = await authors.check_ownership(client, ctx.interaction.user)
    if not state:
        # TODO: yuyo needs an equiv of CommandError
        await ctx.respond("You cannot use this button")

    return state


@yuyo.modals.as_modal(parse_signature=True)
async def eval_modal(
    ctx: yuyo.ModalContext,
    client: alluka.Injected[tanjun.abc.Client],
    component_client: alluka.Injected[yuyo.ComponentClient],
    authors: alluka.Injected[tanjun.dependencies.AbstractOwners],
    *,
    content: str = yuyo.modals.text_input("Content", style=hikari.TextInputStyle.PARAGRAPH),
    raw_file_output: str = yuyo.modals.text_input(
        "File output (y/n)", default="\N{THUMBS DOWN SIGN}", min_length=1, max_length=5
    ),
) -> None:
    """Evaluate the input from an eval modal call."""
    try:
        file_output = tanjun.conversion.to_bool(raw_file_output)

    except ValueError:
        # TODO: yuyo needs an equiv of CommandError
        await ctx.create_initial_response("Invalid value passed for File output", ephemeral=True)
        return

    if not await _check_owner(client, authors, ctx):
        return

    await ctx.defer(defer_type=hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    await eval_command(
        ctx,
        client,
        component_client,
        content=content,
        file_output=file_output,
        state_attachment=hikari.Bytes(content, STATE_FILE_NAME),
    )


def _make_rows(default: str) -> collections.Sequence[hikari.api.ModalActionRowBuilder]:
    """Make a custom instance of the eval modal's rows with the eval content pre-set."""
    assert isinstance(eval_modal.rows[0], hikari.api.ModalActionRowBuilder)
    assert isinstance(eval_modal.rows[0].components[0], hikari.api.TextInputBuilder)
    rows = [
        hikari.impl.ModalActionRowBuilder().add_component(
            eval_modal.rows[0].components[0].set_value(default or hikari.UNDEFINED)
        ),
        *eval_modal.rows[1:],
    ]
    return rows


@yuyo.components.as_single_executor(EVAL_MODAL_ID, ephemeral_default=True)
async def on_edit_button(
    ctx: yuyo.ComponentContext,
    client: alluka.Injected[tanjun.abc.Client],
    authors: alluka.Injected[tanjun.dependencies.AbstractOwners],
) -> None:
    if not await _check_owner(client, authors, ctx):
        return

    rows = eval_modal.rows

    # Try to get the old eval call's code
    for attachment in ctx.interaction.message.attachments:
        # If the edit button has been used already then a state file will be present.
        if attachment.filename == STATE_FILE_NAME:
            with contextlib.suppress(hikari.HikariError):
                rows = _make_rows((await attachment.read()).decode())

            break

    else:
        # Otherwise try to get the source message.
        message = await client.rest.fetch_message(ctx.interaction.channel_id, ctx.interaction.message)
        if message.referenced_message and message.referenced_message.content:
            with contextlib.suppress(IndexError):
                rows = _make_rows(CODEBLOCK_REGEX.findall(message.referenced_message.content)[0])

    await ctx.create_modal_response("Edit eval", EVAL_MODAL_ID, components=rows)


async def _on_noop(ctx: yuyo.ComponentContext) -> None:
    raise RuntimeError("Shouldn't be reached")


@tanjun.annotations.with_annotated_args
@tanjun.as_message_command("eval", "exec")
async def eval_command(
    ctx: typing.Union[tanjun.abc.MessageContext, yuyo.ModalContext],
    client: alluka.Injected[tanjun.abc.Client],
    component_client: alluka.Injected[yuyo.ComponentClient],
    *,
    content: str | None = None,
    component: alluka.Injected[tanjun.abc.Component | None] = None,
    file_output: Annotated[Bool, Flag(empty_value=True, aliases=["-f", "--file-out", "--file"])] = False,
    state_attachment: hikari.Bytes | None = None,
    suppress_response: Annotated[Bool, Flag(empty_value=True, aliases=["-s", "--suppress"])] = False,
) -> None:
    """Dynamically evaluate a script in the bot's environment.

    This can only be used by the bot's owner.
    """
    if isinstance(ctx, tanjun.abc.MessageContext):
        code = CODEBLOCK_REGEX.findall(ctx.content)
        kwargs: dict[str, typing.Any] = {"reply": ctx.message.id}

        if not code:
            raise tanjun.CommandError(
                "Expected a python code block.", component=utility.delete_row_from_authors(ctx.author.id)
            )

        code = code[0]

    else:
        assert content is not None
        code = content
        kwargs = {}

    if suppress_response:
        # Doesn't want a response, just run the eval to completion
        await eval_python_code_no_capture(client, ctx, code, component=component)
        return

    stdout, stderr, exec_time, failed = await eval_python_code(client, ctx, code, component=component)
    attachments = [state_attachment] if state_attachment else []

    if file_output:
        # Wants the output to be attached as two files, avoid building a paginator.
        message = await ctx.respond(
            attachments=[
                hikari.Bytes(stdout, "stdout.py", mimetype="text/x-python;charset=utf-8"),
                hikari.Bytes(stderr, "stderr.py", mimetype="text/x-python;charset=utf-8"),
                *attachments,
            ],
            component=utility.delete_row_from_authors(ctx.author.id).add_interactive_button(
                hikari.ButtonStyle.SECONDARY, EVAL_MODAL_ID, emoji=EDIT_BUTTON_EMOJI
            ),
            **kwargs,
            ensure_result=True,
        )
        _try_deregister(component_client, message)
        return

    colour = utility.FAILED_COLOUR if failed else utility.PASS_COLOUR
    string_paginator = yuyo.sync_paginate_string(
        _yields_results(stdout, stderr), wrapper="```python\n{}\n```", char_limit=2034
    )
    embed_generator = (
        (
            hikari.UNDEFINED,
            hikari.Embed(colour=colour, description=text, title=f"Eval page {page + 1}").set_footer(
                text=f"Time taken: {exec_time} ms"
            ),
        )
        for page, text in enumerate(string_paginator)
    )
    paginator = utility.make_paginator(embed_generator, author=ctx.author.id, full=True)
    first_response = await paginator.get_next_entry()
    utility.add_file_button(
        paginator, make_files=lambda: [_bytes_from_io(stdout, "stdout.py"), _bytes_from_io(stderr, "stderr.py")]
    )
    paginator.add_interactive_button(
        hikari.ButtonStyle.SECONDARY, _on_noop, custom_id=EVAL_MODAL_ID, emoji=EDIT_BUTTON_EMOJI
    )

    assert first_response is not None
    message = await ctx.respond(
        **first_response.to_kwargs() | {"attachments": attachments},
        components=paginator.rows,
        **kwargs,
        ensure_result=True,
    )
    _try_deregister(component_client, message)
    component_client.register_executor(paginator, message=message)


def _try_deregister(client: yuyo.ComponentClient, message: hikari.Message) -> None:
    with contextlib.suppress(KeyError):
        client.deregister_message(message)


load_sudo = (
    tanjun.Component(name="sudo", strict=True).add_check(tanjun.checks.OwnerCheck()).load_from_scope().make_loader()
)
