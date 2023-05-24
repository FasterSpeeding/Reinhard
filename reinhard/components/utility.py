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

__all__: list[str] = ["load_utility"]

import unicodedata
from typing import Annotated

import hikari
import tanjun
from tanchan import doc_parse
from tanjun.annotations import Bool
from tanjun.annotations import Channel
from tanjun.annotations import Color
from tanjun.annotations import Flag
from tanjun.annotations import Greedy
from tanjun.annotations import Member
from tanjun.annotations import Role
from tanjun.annotations import Snowflake
from tanjun.annotations import Str
from tanjun.annotations import User
from tanjun.annotations import channel_field

from .. import utility


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("color", "colour")
@doc_parse.as_slash_command()
async def color(
    ctx: tanjun.abc.Context, color: Annotated[Color | None, Flag(aliases=["-r"])] = None, role: Role | None = None
) -> None:
    """Get a visual representation of a color or role's color.

    Parameters
    ----------
    color
        The hex/int literal representation of a colour to show.
    role
        A role to get the colour for.
    """
    if role:
        color = role.color

    elif color is None:
        raise tanjun.CommandError("Either role or color must be provided", component=utility.delete_row(ctx))

    embed = (
        hikari.Embed(colour=color)
        .add_field(name="RGB", value=str(color.rgb))
        .add_field(name="HEX", value=str(color.hex_code))
    )
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.as_message_command("member")
@doc_parse.as_slash_command(dm_enabled=False)
async def member(ctx: tanjun.abc.Context, member: Member | None = None) -> None:
    """Get information about a member in the current guild.

    Parameters
    ----------
    member
        The member to get information about.
        If not provided then this will default to the command's author.
    """
    assert ctx.guild_id is not None  # This is asserted by a previous check.
    assert ctx.member is not None  # This is always the case for messages made in hikari.
    if member is None:
        member = ctx.member

    # TODO: might want to try cache first at one point even if it cursifies the whole thing.
    guild = await ctx.rest.fetch_guild(guild=ctx.guild_id)
    roles = {role.id: role for role in map(guild.roles.get, member.role_ids) if role}
    ordered_roles = sorted(((role.position, role) for role in roles.values()), reverse=True)

    roles_repr = "\n".join(map("{0[1].name}: {0[1].id}".format, ordered_roles))  # noqa: FS002

    for _, role in ordered_roles:
        if role.colour:
            colour = role.colour
            break
    else:
        colour = hikari.Colour(0)

    if isinstance(member, hikari.InteractionMember):
        permissions = member.permissions

    else:
        permissions = tanjun.utilities.calculate_permissions(member, guild, roles)

    permissions_grid = utility.basic_name_grid(permissions) or "None"
    member_information = [
        f"Color: {colour}",
        f"Joined Discord: {tanjun.conversion.from_datetime(member.user.created_at)}",
        f"Joined Server: {tanjun.conversion.from_datetime(member.joined_at)}",
    ]

    if member.nickname:
        member_information.append(f"Nickname: {member.nickname}")

    if member.premium_since:
        member_information.append(f"Boosting since: {tanjun.conversion.from_datetime(member.premium_since)}")

    if member.user.is_bot:
        member_information.append("System bot" if member.user.is_system else "Bot")

    if member.user.id == guild.owner_id:
        member_information.append("Server owner")

    # TODO: this embed will go over the character limit easily
    embed = (
        hikari.Embed(
            description="\n".join(member_information) + f"\n\nRoles:\n{roles_repr}\n\nPermissions:\n{permissions_grid}",
            colour=colour,
            title=f"{member.user.username}#{member.user.discriminator}",
            url=f"https://discord.com/users/{member.user.id}",
        )
        .set_thumbnail(member.avatar_url or member.default_avatar_url)
        .set_footer(text=str(member.user.id), icon=member.user.default_avatar_url)
    )
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.as_message_command("role")
# TODO: the normal role converter is limited to the current guild right?
@doc_parse.as_slash_command(dm_enabled=False)
async def role(ctx: tanjun.abc.Context, role: Role) -> None:
    """Get information about a role in the current guild.

    Parameters
    ----------
    role
        The role to get information about.
    """
    if role.guild_id != ctx.guild_id:
        raise tanjun.CommandError("Role not found", component=utility.delete_row(ctx))

    permissions = utility.basic_name_grid(role.permissions) or "None"
    role_information = [f"Created: {tanjun.conversion.from_datetime(role.created_at)}", f"Position: {role.position}"]

    if role.colour:
        role_information.append(f"Color: `{role.colour}`")

    if role.is_hoisted:
        role_information.append("Member list hoisted")

    if role.is_managed:
        role_information.append("Managed by an integration")

    if role.is_mentionable:
        role_information.append("Can be mentioned")

    embed = hikari.Embed(
        colour=role.colour,
        title=role.name,
        description="\n".join(role_information) + f"\n\nPermissions:\n{permissions}",
    )
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("user")
@doc_parse.as_slash_command()
async def user(ctx: tanjun.abc.Context, user: User | None = None) -> None:
    """Get information about a Discord user.

    Parameters
    ----------
    user
        The user to target.
        If left as None then this will target the command's author.
    """
    if user is None:
        user = ctx.author

    flags = utility.basic_name_grid(user.flags) or "NONE"
    embed = (
        hikari.Embed(
            colour=utility.embed_colour(),
            description=(
                f"Bot: {user.is_bot}\nSystem bot: {user.is_system}\n"
                f"Joined Discord: {tanjun.conversion.from_datetime(user.created_at)}\n\nFlags: {int(user.flags)}\n{flags}"
            ),
            title=f"{user.username}#{user.discriminator}",
            url=f"https://discord.com/users/{user.id}",
        )
        .set_thumbnail(user.avatar_url or user.default_avatar_url)
        .set_footer(text=str(user.id), icon=user.default_avatar_url)
    )
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("avatar")
@doc_parse.as_slash_command()
async def avatar(ctx: tanjun.abc.Context, user: User | None = None) -> None:
    """Get a user's avatar.

    Parameters
    ----------
    user
        User to get the avatar for.
        If not provided then this returns the current user's avatar.
    """
    if user is None:
        user = ctx.author

    avatar = user.avatar_url or user.default_avatar_url
    embed = hikari.Embed(title=str(user), url=str(avatar), colour=utility.embed_colour()).set_image(avatar)
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("mentions")
# TODO: check if the user can access the provided channel
@doc_parse.as_slash_command()
async def mentions(
    ctx: tanjun.abc.Context,
    message: Snowflake,
    channel: Channel
    | None
    | hikari.Snowflake = channel_field(or_snowflake=True, message_names=["--channel", "-c"], default=None),
) -> None:
    """Get a list of the users who were pinged by a message.

    Parameters
    ----------
    message
        ID of the message to get the ping list for.
    channel
        The channel the message is in.
    """
    channel_id = hikari.Snowflake(channel) if channel else ctx.channel_id
    try:
        message_ = await ctx.rest.fetch_message(channel_id, message)
    except hikari.NotFoundError:
        raise tanjun.CommandError("Message not found", component=utility.delete_row(ctx)) from None

    mentions: str | None = None
    if message_.user_mentions:
        mentions = ", ".join(map(str, message_.user_mentions.values()))

    await ctx.respond(
        content=f"Pinging mentions: {mentions}" if mentions else "No pinging mentions.",
        component=utility.delete_row(ctx),
    )


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.as_message_command("members")
@doc_parse.as_slash_command(dm_enabled=False)
async def members(ctx: tanjun.abc.Context, name: Annotated[Str, Greedy()]) -> None:
    """Search for a member in the current guild.

    Parameters
    ----------
    name
        Greedy argument of the name to search for.
    """
    assert ctx.guild_id is not None
    members = await ctx.rest.search_members(ctx.guild_id, name)

    if members:
        content = "Similar members:\n* " + "\n* ".join(
            f"{member.username} ({member.nickname})" if member.nickname else member.username for member in members
        )

    else:
        content = "No similar members found"

    await ctx.respond(content=content, component=utility.delete_row(ctx))


def _format_char_line(char: str, to_file: bool) -> str:
    code = ord(char)
    name = unicodedata.name(char, "???")
    if to_file:
        return f"* `\\U{code:08x}`/`{char}`: {name} <http://www.fileformat.info/info/unicode/char/{code:x}>"

    return f"`\\U{code:08x}`/`{char}`: {name} <http://www.fileformat.info/info/unicode/char/{code:x}>"


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("char")
@doc_parse.as_slash_command()
async def char(
    ctx: tanjun.abc.Context,
    characters: Annotated[Str, Greedy()],
    file: Annotated[Bool, Flag(aliases=["-f"], empty_value=True)] = False,
) -> None:
    """Get information about the UTF-8 characters in the executing message.

    Running `char file...` will ensure that the output is always sent as a markdown file.

    Parameters
    ----------
    characters
        The UTF-8 characters to get information about.
    file
        Whether this should send a file response regardless of response length.
    """
    if len(characters) > 20:
        file = True  # noqa: VNE002

    content: hikari.UndefinedOr[str] = hikari.UNDEFINED
    content = "\n".join(_format_char_line(char, file) for char in characters)
    response_file: hikari.UndefinedOr[hikari.Bytes] = hikari.UNDEFINED

    # highly doubt this'll ever be over 1990 when file is False but better safe than sorry.
    if file or len(content) >= 1990:
        response_file = hikari.Bytes(content.encode(), "character-info.md", mimetype="text/markdown; charset=UTF-8")

    await ctx.respond(content=content, attachment=response_file, component=utility.delete_row(ctx))


load_utility = tanjun.Component(name="utility", strict=True).load_from_scope().make_loader()
