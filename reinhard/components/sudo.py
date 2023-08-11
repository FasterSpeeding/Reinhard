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

__all__: list[str] = ["load_sudo", "unload_sudo"]

import ast
import asyncio
import contextlib
import copy
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
from tanchan import doc_parse
from tanjun.annotations import Bool
from tanjun.annotations import Converted
from tanjun.annotations import Flag
from tanjun.annotations import Greedy
from tanjun.annotations import Positional
from tanjun.annotations import Str

from .. import config
from .. import utility

component = tanjun.Component(name="sudo", strict=True)


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
THUMBS_UP_EMOJI = "\N{THUMBS UP SIGN}"
THUMBS_DOWN_EMOJI = "\N{THUMBS DOWN SIGN}"


async def _check_owner(
    client: tanjun.abc.Client,
    authors: tanjun.dependencies.AbstractOwners,
    ctx: yuyo.ComponentContext | yuyo.ModalContext,
) -> None:
    if not await authors.check_ownership(client, ctx.interaction.user):
        raise yuyo.InteractionError("You cannot use this button")


@yuyo.modals.as_modal(parse_signature=True)
async def eval_modal(
    ctx: yuyo.ModalContext,
    client: alluka.Injected[tanjun.abc.Client],
    component_client: alluka.Injected[yuyo.ComponentClient],
    authors: alluka.Injected[tanjun.dependencies.AbstractOwners],
    *,
    content: str = yuyo.modals.text_input("Content", style=hikari.TextInputStyle.PARAGRAPH),
    raw_file_output: str = yuyo.modals.text_input(
        "File output (y/n)", default=THUMBS_DOWN_EMOJI, min_length=1, max_length=5
    ),
) -> None:
    """Evaluate the input from an eval modal call."""
    try:
        file_output = tanjun.conversion.to_bool(raw_file_output)

    except ValueError:
        await ctx.create_initial_response("Invalid value passed for File output", ephemeral=True)
        return

    await _check_owner(client, authors, ctx)
    if ctx.interaction.message:
        # Being executed as a button attached to an eval call's response to edit it.
        await ctx.create_initial_response(response_type=hikari.ResponseType.MESSAGE_UPDATE)

    else:
        # Being executed in response to the slash command.
        await ctx.create_initial_response("Loading...")

    state = json.dumps({"content": content, "file_output": file_output})
    await eval_message_command(
        ctx,
        client,
        component_client,
        content=content,
        file_output=file_output,
        state_attachment=hikari.Bytes(state, STATE_FILE_NAME),
    )


def _make_rows(
    *, default: str | None = None, file_output: bool | None = None
) -> collections.Sequence[hikari.api.ModalActionRowBuilder]:
    """Make a custom instance of the eval modal's rows with the eval content pre-set."""
    rows = list(eval_modal.rows)
    content_row = eval_modal.rows[0]
    if default is not None:
        assert isinstance(content_row.components[0], hikari.api.TextInputBuilder)
        rows[0] = hikari.impl.ModalActionRowBuilder().add_component(
            copy.copy(content_row.components[0]).set_value(default)
        )

    button_row = eval_modal.rows[1]
    if file_output is not None:
        assert isinstance(button_row.components[0], hikari.api.TextInputBuilder)
        file_output_repr = THUMBS_UP_EMOJI if file_output else THUMBS_DOWN_EMOJI
        rows[1] = hikari.impl.ModalActionRowBuilder().add_component(
            copy.copy(button_row.components[0]).set_value(file_output_repr)
        )

    return rows


@yuyo.components.as_single_executor(EVAL_MODAL_ID, ephemeral_default=True)
async def on_edit_button(
    ctx: yuyo.ComponentContext,
    client: alluka.Injected[tanjun.abc.Client],
    authors: alluka.Injected[tanjun.dependencies.AbstractOwners],
) -> None:
    await _check_owner(client, authors, ctx)
    rows = eval_modal.rows
    # Try to get the old eval call's code
    for attachment in ctx.interaction.message.attachments:
        # If the edit button has been used already then a state file will be present.
        if attachment.filename == STATE_FILE_NAME:
            try:
                data = await attachment.read()

            except hikari.HikariError:
                break

            try:
                data = json.loads(data)

            # Backwards compatibility with old eval responses which just stored
            # the eval code in the file output file raw without any json wrapping.
            except json.JSONDecodeError:
                rows = _make_rows(default=data.decode())

            else:
                rows = _make_rows(default=data["content"], file_output=data["file_output"])

            break

    else:
        # Otherwise try to get the source message.
        message = await client.rest.fetch_message(ctx.interaction.channel_id, ctx.interaction.message)
        if message.referenced_message and message.referenced_message.content:
            with contextlib.suppress(IndexError):
                rows = _make_rows(default=CODEBLOCK_REGEX.findall(message.referenced_message.content)[0])

    await ctx.create_modal_response("Edit eval", EVAL_MODAL_ID, components=rows)


async def _on_noop(ctx: yuyo.ComponentContext) -> None:
    raise RuntimeError("Shouldn't be reached")


@tanjun.annotations.with_annotated_args
@tanjun.as_message_command("eval", "exec")
async def eval_message_command(
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
    """Owner only command used to dynamically evaluate a script."""
    if isinstance(ctx, tanjun.abc.MessageContext):
        code = CODEBLOCK_REGEX.findall(ctx.content)
        kwargs: dict[str, typing.Any] = {"reply": ctx.message.id}
        respond = ctx.respond

        if not code:
            raise tanjun.CommandError(
                "Expected a python code block.", component=utility.delete_row_from_authors(ctx.author.id)
            )

        code = code[0]

    else:
        assert content is not None
        code = content
        kwargs = {}
        respond = ctx.edit_initial_response

    if suppress_response:
        # Doesn't want a response, just run the eval to completion
        await eval_python_code_no_capture(client, ctx, code, component=component)
        return

    stdout, stderr, exec_time, failed = await eval_python_code(client, ctx, code, component=component)
    attachments = [state_attachment] if state_attachment else []

    if file_output:
        # Wants the output to be attached as two files, avoid building a paginator.
        message = await respond(
            "",
            attachments=[
                hikari.Bytes(stdout, "stdout.py", mimetype="text/x-python;charset=utf-8"),
                hikari.Bytes(stderr, "stderr.py", mimetype="text/x-python;charset=utf-8"),
                *attachments,
            ],
            component=utility.delete_row_from_authors(ctx.author.id).add_interactive_button(
                hikari.ButtonStyle.SECONDARY, EVAL_MODAL_ID, emoji=EDIT_BUTTON_EMOJI
            ),
            embeds=[],
            **kwargs,
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
    message = await respond(
        **first_response.to_kwargs() | {"attachments": attachments, "content": ""}, components=paginator.rows, **kwargs
    )
    _try_deregister(component_client, message)
    component_client.register_executor(paginator, message=message)


@doc_parse.with_annotated_args
@tanjun.with_owner_check
@doc_parse.as_slash_command(name="eval", is_global=False)
async def eval_slash_command(ctx: tanjun.abc.SlashContext, file_output: Bool | None = None) -> None:
    """Owner only command used to dynamically evaluate a script.

    This can only be used by the bot's owner.

    Parameters
    ----------
    file_output
        Whether this should send the output as embeddable txt files.

        Defaults to False.
    """
    await ctx.create_modal_response("Eval", EVAL_MODAL_ID, components=_make_rows(file_output=file_output))


@component.with_listener()
async def on_guild_create(
    event: hikari.GuildJoinEvent | hikari.GuildAvailableEvent, config: alluka.Injected[config.FullConfig]
) -> None:
    if event.guild_id in config.eval_guilds:
        app = await event.app.rest.fetch_application()
        await eval_slash_command.build().create(event.app.rest, app.id, guild=event.guild_id)


def _try_deregister(client: yuyo.ComponentClient, message: hikari.Message) -> None:
    with contextlib.suppress(KeyError):
        client.deregister_message(message)


component.add_check(tanjun.checks.OwnerCheck()).load_from_scope()


@tanjun.as_loader
def load_sudo(client: tanjun.abc.Client) -> None:
    client.add_component(component)

    component_client = client.injector.get_type_dependency(yuyo.ComponentClient)
    modal_client = client.injector.get_type_dependency(yuyo.ModalClient)
    assert component_client
    assert modal_client
    component_client.register_executor(on_edit_button, timeout=None)
    modal_client.register_modal(EVAL_MODAL_ID, eval_modal, timeout=None)


@tanjun.as_unloader
def unload_sudo(client: tanjun.abc.Client) -> None:
    client.remove_component_by_name(component.name)

    component_client = client.injector.get_type_dependency(yuyo.ComponentClient)
    modal_client = client.injector.get_type_dependency(yuyo.ModalClient)
    assert component_client
    assert modal_client
    component_client.deregister_executor(on_edit_button)
    modal_client.deregister_modal(EVAL_MODAL_ID)
