# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2022, Faster Speeding
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
from tanjun.annotations import Bool
from tanjun.annotations import Channel
from tanjun.annotations import Color
from tanjun.annotations import Flag
from tanjun.annotations import Greedy
from tanjun.annotations import Member
from tanjun.annotations import Role
from tanjun.annotations import Snowflake
from tanjun.annotations import SnowflakeOr
from tanjun.annotations import Str
from tanjun.annotations import User
from tanjun.annotations import with_annotated_args

from .. import utility


@with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("color", "colour")
@tanjun.as_slash_command("color", "Get a visual representation of a color or role's color.")
async def colour_command(
    ctx: tanjun.abc.Context,
    color: Annotated[
        Color | None, Flag(aliases=("-r",)), "the hex/int literal representation of a colour to show"
    ] = None,
    role: Annotated[Role | None, "A role to get the colour for."] = None,
) -> None:
    """Get a visual representation of a color or role's color.

    Argument:
        colour: Either the hex/int literal representation of a colour to show or the ID/mention of a role to get
            the colour of.
    """
    if role:
        color = role.color

    elif color is None:
        # TODO: delete row
        raise tanjun.CommandError("Either role or color must be provided")

    embed = (
        hikari.Embed(colour=color)
        .add_field(name="RGB", value=str(color.rgb))
        .add_field(name="HEX", value=str(color.hex_code))
    )
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


# # @decorators.as_message_command
# async def copy_command(
#     self,
#     ctx: tanjun.MessageContext,
#     message: converters.BaseIDConverter,
#     channel: converters.BaseIDConverter | None = None,
# ) -> None:
#     try:
#         message = await self.tanjun.rest.fetch_message(
#             message=message, channel=channel or ctx.channel_id
#         )
#     except (hikari.NotFound, hikari.Forbidden) as exc:
#         await ctx.respond(content="Failed to get message.")
#     else:
#         ...  # TODO: Implement this to allow getting the embeds from a suppressed message.


@with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.as_message_command("member")
@tanjun.as_slash_command("member", "Get information about a member in the current guild.", dm_enabled=False)
async def member_command(
    ctx: tanjun.abc.Context,
    member: Annotated[
        Member | None,
        "The member to get information about. If not provided then this will default to the command's author",
    ] = None,
) -> None:
    """Get information about a member in the current guild."""
    assert ctx.guild_id is not None  # This is asserted by a previous check.
    assert ctx.member is not None  # This is always the case for messages made in hikari.
    if member is None:
        member = ctx.member

    # TODO: might want to try cache first at one point even if it cursifies the whole thing.
    guild = await ctx.rest.fetch_guild(guild=ctx.guild_id)
    roles = {role.id: role for role in map(guild.roles.get, member.role_ids) if role}
    ordered_roles = sorted(((role.position, role) for role in roles.values()), reverse=True)

    roles_repr = "\n".join(map("{0[1].name}: {0[1].id}".format, ordered_roles))

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


@with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.as_message_command("role")
# TODO: the normal role converter is limited to the current guild right?
@tanjun.as_slash_command("role", "Get information about a role in the current guild.", dm_enabled=False)
async def role_command(ctx: tanjun.abc.Context, role: Annotated[Role, "The role to get information about."]) -> None:
    """Get information about a role in the current guild."""
    if role.guild_id != ctx.guild_id:
        raise tanjun.CommandError("Role not found")

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


@with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("user")
@tanjun.as_slash_command("user", "Get information about a Discord user.")
async def user_command(
    ctx: tanjun.abc.Context,
    user: Annotated[
        User | None, "The user to target. If left as None then this will target the command's author."
    ] = None,
) -> None:
    """Get information about a Discord user."""
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


@with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("avatar")
@tanjun.as_slash_command("avatar", "Get a user's avatar.")
async def avatar_command(
    ctx: tanjun.abc.Context,
    user: Annotated[
        User | None, "User to get the avatar for. If not provided then this returns the current user's avatar."
    ] = None,
) -> None:
    """Get a user's avatar."""
    if user is None:
        user = ctx.author

    avatar = user.avatar_url or user.default_avatar_url
    embed = hikari.Embed(title=str(user), url=str(avatar), colour=utility.embed_colour()).set_image(avatar)
    await ctx.respond(embed=embed, component=utility.delete_row(ctx))


@with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("mentions")
# TODO: check if the user can access the provided channel
@tanjun.as_slash_command("mentions", "Get a list of the users who were pinged by a message.")
async def mentions_command(
    ctx: tanjun.abc.Context,
    message: Annotated[Snowflake, "ID of the message to get the ping list for."],
    channel: Annotated[SnowflakeOr[Channel | None], Flag(aliases=("-c",)), "The channel the message is in."] = None,
) -> None:
    """Get a list of the users who were pinged by a message."""
    channel_id = hikari.Snowflake(channel) if channel else ctx.channel_id
    try:
        message_ = await ctx.rest.fetch_message(channel_id, message)
    except hikari.NotFoundError:
        raise tanjun.CommandError("Message not found") from None

    mentions: str | None = None
    if message_.mentions.users:
        mentions = ", ".join(map(str, message_.mentions.users.values()))

    await ctx.respond(
        content=f"Pinging mentions: {mentions}" if mentions else "No pinging mentions.",
        component=utility.delete_row(ctx),
    )


@with_annotated_args(follow_wrapped=True)
@tanjun.with_guild_check(follow_wrapped=True)
@tanjun.as_message_command("members")
@tanjun.as_slash_command("members", "Search for a member in the current guild.", dm_enabled=False)
async def members_command(
    ctx: tanjun.abc.Context, name: Annotated[Greedy[Str], "Greedy argument of the name to search for."]
) -> None:
    """Search for a member in the current guild."""
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


@with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("char")
@tanjun.as_slash_command("char", "Get information about the UTF-8 characters in the executing message.")
async def char_command(
    ctx: tanjun.abc.Context,
    characters: Annotated[Greedy[Str], "The UTF-8 characters to get information about"],
    file: Annotated[
        Bool,
        Flag(aliases=("-f",), empty_value=True),
        "Whether this should send a file response regardless of response length",
    ] = False,
) -> None:
    """Get information about the UTF-8 characters in the executing message.

    Running `char file...` will ensure that the output is always sent as a markdown file.
    """
    if len(characters) > 20:
        file = True

    content: hikari.UndefinedOr[str] = hikari.UNDEFINED
    content = "\n".join(_format_char_line(char, file) for char in characters)
    response_file: hikari.UndefinedOr[hikari.Bytes] = hikari.UNDEFINED

    # highly doubt this'll ever be over 1990 when file is False but better safe than sorry.
    if file or len(content) >= 1990:
        response_file = hikari.Bytes(content.encode(), "character-info.md", mimetype="text/markdown; charset=UTF-8")

    else:
        content = content

    await ctx.respond(content=content, attachment=response_file, component=utility.delete_row(ctx))


load_utility = tanjun.Component(name="utility", strict=True).load_from_scope().make_loader()
