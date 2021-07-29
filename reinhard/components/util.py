from __future__ import annotations

__all__: list[str] = ["util_component", "load_component"]

import unicodedata

import hikari
import tanjun
from yuyo import backoff

from ..util import basic as basic_util
from ..util import constants
from ..util import conversion
from ..util import help as help_util
from ..util import rest_manager

util_component = tanjun.Component(strict=True)
help_util.with_docs(util_component, "Utility commands", "Component used for getting miscellaneous Discord information.")


@util_component.with_message_command
@tanjun.with_greedy_argument("colour", converters=(conversion.ColorConverter(), conversion.RESTFulRoleConverter()))
@tanjun.with_parser
@tanjun.as_message_command("color", "colour")
async def colour_command(ctx: tanjun.traits.MessageContext, colour: hikari.Colour | hikari.Role) -> None:
    """Get a visual representation of a color or role's color.

    Argument:
        colour: Either the hex/int literal representation of a colour to show or the ID/mention of a role to get
            the colour of.
    """
    if isinstance(colour, hikari.Role):
        colour = colour.colour

    embed = (
        hikari.Embed(colour=colour)
        .add_field(name="RGB", value=str(colour.rgb))
        .add_field(name="HEX", value=str(colour.hex_code))
    )
    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
    await error_manager.try_respond(ctx, embed=embed)


# # @decorators.as_message_command
# async def copy_command(
#     self,
#     ctx: tanjun.MessageContext,
#     message: converters.BaseIDConverter,
#     channel: converters.BaseIDConverter | None = None,
# ) -> None:
#     try:
#         message = await self.tanjun.rest.fetch_message(
#             message=message, channel=channel or ctx.message.channel_id
#         )
#     except (hikari.NotFound, hikari.Forbidden) as exc:
#         await ctx.message.respond(content="Failed to get message.")
#     else:
#         ...  # TODO: Implement this to allow getting the embeds from a suppressed message.


@util_component.with_message_command
@tanjun.with_greedy_argument("member", converters=conversion.RESTFulMemberConverter(), default=None)
@tanjun.with_parser
@tanjun.with_check(lambda ctx: ctx.message.guild_id is not None)
@tanjun.as_message_command("member")
async def member_command(ctx: tanjun.traits.MessageContext, member: hikari.Member | None) -> None:
    """Get information about a member in the current guild.

    Arguments:
        * member: The optional argument of the mention or ID of a member to get information about.
            If not provided then this will return information about the member executing this command.
    """
    assert ctx.message.guild_id is not None  # This is asserted by a previous check.
    assert ctx.message.member is not None  # This is always the case for messages made in hikari.
    if member is None:
        member = ctx.message.member

    retry = backoff.Backoff(max_retries=5)
    error_manager = rest_manager.HikariErrorManager(retry, break_on=(hikari.ForbiddenError, hikari.NotFoundError))
    async for _ in retry:
        with error_manager:
            guild = await ctx.rest.fetch_guild(guild=ctx.message.guild_id)
            break

    else:
        if retry.is_depleted:
            raise tanjun.CommandError("Couldn't get guild in time")

        return

    permissions = guild.roles[guild.id].permissions
    roles = {}

    for role_id in member.role_ids:
        role = guild.roles[role_id]
        permissions |= role.permissions
        roles[role.position] = role

    ordered_roles = dict(sorted(roles.items(), reverse=True))
    roles = "\n".join(map("{0.name}: {0.id}".format, ordered_roles.values()))

    for role in ordered_roles.values():
        if role.colour:
            colour = role.colour
            break
    else:
        colour = hikari.Colour(0)

    permissions_grid = basic_util.basic_name_grid(permissions) or "None"
    member_information = [
        f"Color: {colour}",
        f"Joined Discord: {basic_util.pretify_date(member.user.created_at)}",
        f"Joined Server: {basic_util.pretify_date(member.joined_at)}",
    ]

    if member.nickname:
        member_information.append(f"Nickname: {member.nickname}")

    if member.premium_since:
        member_information.append(f"Boosting since: {basic_util.pretify_date(member.premium_since)}")

    if member.user.is_bot:
        member_information.append("System bot" if member.user.is_system else "Bot")

    if member.user.id == guild.owner_id:
        member_information.append("Server owner")

    # TODO: this embed will go over the character limit easily
    embed = (
        hikari.Embed(
            description="\n".join(member_information) + f"\n\nRoles:\n{roles}\n\nPermissions:\n{permissions_grid}",
            colour=colour,
            title=f"{member.user.username}#{member.user.discriminator}",
            url=f"https://discordapp.com/users/{member.user.id}",
        )
        .set_thumbnail(member.user.avatar_url)
        .set_footer(text=str(member.user.id), icon=member.user.default_avatar_url)
    )
    error_manager.clear_rules()
    await error_manager.try_respond(ctx, embed=embed)


# TODO: the normal role converter is limited to the current guild right?
@util_component.with_message_command
@tanjun.with_argument("role", converters=conversion.RESTFulRoleConverter())
@tanjun.with_parser
@tanjun.with_check(lambda ctx: ctx.message.guild_id is not None)
@tanjun.as_message_command("role")
async def role_command(ctx: tanjun.traits.MessageContext, role: hikari.Role) -> None:
    """ "Get information about a role in the current guild.

    Arguments:
        * role: Mention or ID of the role to get information about.
    """

    permissions = basic_util.basic_name_grid(role.permissions) or "None"
    role_information = [f"Created: {basic_util.pretify_date(role.created_at)}", f"Position: {role.position}"]

    if role.colour:
        role_information.append(f"Color: `{role.colour}`")

    if role.is_hoisted:
        role_information.append("Member list hoisted")

    if role.is_managed:
        role_information.append("Managed by an integration")

    if role.is_mentionable:
        role_information.append("Can be mentioned")

    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.ForbiddenError, hikari.NotFoundError))
    embed = hikari.Embed(
        colour=role.colour,
        title=role.name,
        description="\n".join(role_information) + f"\n\nPermissions:\n{permissions}",
    )
    await error_manager.try_respond(ctx, embed=embed)


@util_component.with_message_command
@tanjun.with_greedy_argument(
    "user", converters=(conversion.RESTFulUserConverter(), conversion.RESTFulMemberConverter()), default=None
)
@tanjun.with_parser
@tanjun.as_message_command("user")
async def user_command(ctx: tanjun.traits.MessageContext, user: hikari.User | None) -> None:
    """ "Get information about a Discord user."

    Arguments:
        * user: Optional argument of the mention or ID of the user to target.
            If not supplied then this will return information about the triggering user.
    """
    if user is None:
        user = ctx.message.author

    flags = basic_util.basic_name_grid(user.flags) or "NONE"
    embed = (
        hikari.Embed(
            colour=constants.embed_colour(),
            description=(
                f"Bot: {user.is_system}\nSystem bot: {user.is_system}\n"
                f"Joined Discord: {basic_util.pretify_date(user.created_at)}\n\nFlags: {int(user.flags)}\n{flags}"
            ),
            title=f"{user.username}#{user.discriminator}",
            url=f"https://discordapp.com/users/{user.id}",
        )
        .set_thumbnail(user.avatar_url)
        .set_footer(text=str(user.id), icon=user.default_avatar_url)
    )
    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.ForbiddenError, hikari.NotFoundError))
    await error_manager.try_respond(ctx, embed=embed)


@util_component.with_message_command
@tanjun.with_greedy_argument(
    "user", converters=(conversion.RESTFulUserConverter(), conversion.RESTFulMemberConverter()), default=None
)
@tanjun.with_parser
@tanjun.as_message_command("avatar", "pfp")
async def avatar_command(ctx: tanjun.traits.MessageContext, user: hikari.User | None) -> None:
    """Get a user's avatar.

    Arguments:
        * user: Optional argument of a mention or ID of the user to get the avatar for.
            If this isn't provided then this command will return the avatar of the user who triggerred it.
    """
    if user is None:
        user = ctx.message.author

    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.ForbiddenError, hikari.NotFoundError))
    avatar = user.avatar_url or user.default_avatar_url
    embed = hikari.Embed(title=str(user), url=str(avatar), colour=constants.embed_colour()).set_image(avatar)
    await error_manager.try_respond(ctx, embed=embed)


@util_component.with_message_command
@tanjun.with_argument("message_id", (hikari.Snowflake,))
@tanjun.with_option("channel_id", "--channel", "-c", converters=hikari.Snowflake, default=None)
@tanjun.with_parser
@tanjun.as_message_command("pings", "mentions")
async def mentions_command(
    ctx: tanjun.traits.MessageContext,
    message_id: hikari.Snowflake,
    channel_id: hikari.Snowflake | None,
) -> None:
    """Get a list of the users who were pinged by a message.

    Arguments
        * message: ID of the message to get the ping list for.

    Options
        * channel: ID or mention of the channel the message is in.
            If this isn't provided then the command will assume the message is in the current channel.
    """
    if channel_id is None:
        channel_id = ctx.message.channel_id

    # TODO: set maximum?
    retry = backoff.Backoff()
    error_manager = rest_manager.HikariErrorManager(retry).with_rule(
        (hikari.NotFoundError, hikari.ForbiddenError, hikari.BadRequestError),
        basic_util.raise_error("Message not found."),
    )
    async for _ in retry:
        with error_manager:
            message = await ctx.rest.fetch_message(channel_id, message_id)
            break

    error_manager.clear_rules(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
    mentions = ", ".join(map(str, message.mentions.users.values())) if message.mentions.users else None
    await error_manager.try_respond(
        ctx, content=f"Pinging mentions: {mentions}" if mentions else "No pinging mentions."
    )


@util_component.with_message_command
@tanjun.with_guild_check
@tanjun.with_greedy_argument("name")
@tanjun.with_parser
@tanjun.as_message_command("members")
async def members_command(ctx: tanjun.traits.MessageContext, name: str) -> None:
    """Search for a member in the current guild.

    Arguments
        * name: Greedy argument of the name to search for.
    """
    assert ctx.guild_id is not None
    members = await ctx.rest.search_members(ctx.guild_id, name)

    if members:
        content = "Similar members:\n" + "\n".join(
            f"* {member.username} ({member.nickname})" if member.nickname else member.username for member in members
        )

    else:
        content = "No similar members found"

    await rest_manager.HikariErrorManager().try_respond(ctx, content=content)


def _format_char_line(char: str, to_file: bool) -> str:
    code = ord(char)
    name = unicodedata.name(char, "???")
    if to_file:
        return f"* `\\U{code:08x}`/`{char}`: {name} <http://www.fileformat.info/info/unicode/char/{code:x}>"

    return f"`\\U{code:08x}`/`{char}`: {name} <http://www.fileformat.info/info/unicode/char/{code:x}>"


@util_component.with_message_command
@tanjun.as_message_command_group("char", strict=True)
async def char_command(ctx: tanjun.traits.MessageContext, to_file: bool = False) -> None:
    """Get information about the UTF-8 characters in the executing message.

    Running `char file...` will ensure that the output is always sent as a markdown file.
    """
    if not ctx.content:
        return

    if len(ctx.content) > 20:
        to_file = True

    content: hikari.UndefinedOr[str]
    content = "\n".join(_format_char_line(char, to_file) for char in ctx.content)
    file: hikari.UndefinedOr[hikari.Bytes] = hikari.UNDEFINED

    # highly doubt this'll ever be over 1990 when to_file is False but better safe than sorry.
    if to_file or len(content) >= 1990:
        file = hikari.Bytes(content.encode(), "character-info.md", mimetype="text/markdown; charset=UTF-8")
        content = hikari.UNDEFINED

    else:
        content = content

    await ctx.message.respond(content=content, attachment=file)


@char_command.with_command
@tanjun.as_message_command("file")
async def char_file_command(ctx: tanjun.traits.MessageContext) -> None:
    await char_command(ctx, to_file=True)


@tanjun.as_loader
def load_component(cli: tanjun.traits.Client, /) -> None:
    cli.add_component(util_component.copy())
