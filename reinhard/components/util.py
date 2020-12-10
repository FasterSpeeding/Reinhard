from __future__ import annotations

__all__: typing.Sequence[str] = ["UtilComponent"]

import typing

from hikari import colours
from hikari import embeds
from hikari import errors as hikari_errors
from hikari import guilds
from hikari import snowflakes
from hikari import users
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import parsing
from tanjun import traits as tanjun_traits
from yuyo import backoff

from reinhard.util import basic
from reinhard.util import constants
from reinhard.util import conversion
from reinhard.util import help as help_util
from reinhard.util import rest_manager

__exports__ = ["UtilComponent"]


@help_util.with_component_doc("Component used for getting miscellaneous Discord information.")
@help_util.with_component_name("Utility Component")
class UtilComponent(components.Component):
    __slots__: typing.Sequence[str] = ("own_user",)

    def __init__(self, *, hooks: typing.Optional[tanjun_traits.Hooks] = None) -> None:
        super().__init__(hooks=hooks)
        self.own_user: typing.Optional[users.OwnUser] = None

    async def open(self) -> None:
        if self.client is None:
            raise RuntimeError("Cannot start this component before binding a client")

        retry = backoff.Backoff(max_retries=4)
        error_manager = rest_manager.HikariErrorManager(retry)

        async for _ in retry:
            with error_manager:
                self.own_user = await self.client.rest_service.rest.fetch_my_user()
                break

        else:
            self.own_user = await self.client.rest_service.rest.fetch_my_user()

        await super().open()

    @help_util.with_parameter_doc(
        "colour", "A required argument of either a text colour representation or a role's ID."
    )
    @help_util.with_command_doc("Get a visual representation of a color or role's color.")
    @parsing.with_greedy_argument("colour", converters=(conversion.ColorConverter, conversion.RESTFulRoleConverter))
    @parsing.with_parser
    @components.as_command("color", "colour")
    async def colour(self, ctx: tanjun_traits.Context, colour: typing.Union[colours.Colour, guilds.Role]) -> None:
        if isinstance(colour, guilds.Role):
            colour = colour.colour

        embed = (
            embeds.Embed(colour=colour)
            .add_field(name="RGB", value=str(colour.rgb))
            .add_field(name="HEX", value=str(colour.hex_code))
        )
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
        )

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    # # @decorators.as_command
    # async def copy(
    #     self,
    #     ctx: commands.Context,
    #     message: converters.BaseIDConverter,
    #     channel: typing.Optional[converters.BaseIDConverter] = None,
    # ) -> None:
    #     try:
    #         message = await self.components.rest.fetch_message(
    #             message=message, channel=channel or ctx.message.channel_id
    #         )
    #     except (hikari_errors.NotFound, hikari_errors.Forbidden) as exc:
    #         await ctx.message.reply(content="Failed to get message.")
    #     else:
    #         ...  # TODO: Implement this to allow getting the embeds from a suppressed message.

    @help_util.with_parameter_doc(
        "member",
        "The optional argument of a member mention or ID. "
        "If not supplied then this command will target the member triggering it.",
    )
    @help_util.with_command_doc("Get information about a member in the current guild.")
    @parsing.with_greedy_argument("member", converters=(conversion.RESTFulMemberConverter,), default=None)
    @parsing.with_parser
    @components.as_command("member", checks=[lambda ctx: ctx.message.guild_id is not None])
    async def member(self, ctx: tanjun_traits.Context, member: typing.Union[guilds.Member, None]) -> None:
        assert ctx.message.guild_id is not None  # This is asserted by a previous check.
        assert ctx.message.member is not None  # This is always the case for messages made in guilds.
        if member is None:
            member = ctx.message.member

        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError,)
        )
        async for _ in retry:
            with error_manager:
                guild = await ctx.client.rest_service.rest.fetch_guild(guild=ctx.message.guild_id)
                break

        else:
            if retry.is_depleted:
                raise tanjun_errors.CommandError("Couldn't get guild in time")

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
            colour = colours.Colour(0)

        permissions_grid = basic.basic_name_grid(permissions) or "None"
        member_information = [
            f"Color: {colour}",
            f"Joined Discord: {basic.pretify_date(member.user.created_at)}",
            f"Joined Server: {basic.pretify_date(member.joined_at)}",
        ]

        if member.nickname:
            member_information.append(f"Nickname: {member.nickname}")

        if member.premium_since:
            member_information.append(f"Boosting since: {basic.pretify_date(member.premium_since)}")

        if member.user.is_bot:
            member_information.append("System bot" if member.user.is_system else "Bot")

        if member.user.id == guild.owner_id:
            member_information.append("Server owner")

        # TODO: this embed will go over the character limit easily
        embed = (
            embeds.Embed(
                description="\n".join(member_information) + f"\n\nRoles:\n{roles}\n\nPermissions:\n{permissions_grid}",
                colour=colour,
                title=f"{member.user.username}#{member.user.discriminator}",
                url=f"https://discordapp.com/users/{member.user.id}",
            )
            .set_thumbnail(member.user.avatar_url)
            .set_footer(text=str(member.user.id), icon=member.user.default_avatar_url)
        )
        retry.reset()
        error_manager.clear_rules()

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    @staticmethod
    def filter_role(role_id: snowflakes.Snowflake) -> typing.Callable[[guilds.Role], bool]:
        return lambda role: role.id == role_id

    @help_util.with_parameter_doc("role", "The required argument of a role ID.")
    @help_util.with_command_doc("Get information about a role in the current guild.")
    @parsing.with_argument("role", converters=(conversion.RESTFulRoleConverter,))
    @parsing.with_parser
    @components.as_command("role", checks=[lambda ctx: ctx.message.guild_id is not None])
    async def role(self, ctx: tanjun_traits.Context, role: guilds.Role) -> None:
        permissions = basic.basic_name_grid(role.permissions) or "None"
        role_information = [f"Created: {basic.pretify_date(role.created_at)}", f"Position: {role.position}"]

        if role.colour:
            role_information.append(f"Color: `{role.colour}`")

        if role.is_hoisted:
            role_information.append("Member list hoisted")

        if role.is_managed:
            role_information.append("Managed by an integration")

        if role.is_mentionable:
            role_information.append("Can be mentioned")

        retry = backoff.Backoff(max_retries=5, maximum=2.0)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )
        embed = embeds.Embed(
            colour=role.colour,
            title=role.name,
            description="\n".join(role_information) + f"\n\nPermissions:\n{permissions}",
        )

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    @help_util.with_parameter_doc(
        "user",
        "The optional argument of the mention or ID of the user to target. "
        "If not supplied then this command will target the user triggering it.",
    )
    @help_util.with_command_doc("Get information about a Discord user.")
    @parsing.with_greedy_argument(
        "user", converters=(conversion.RESTFulUserConverter, conversion.RESTFulMemberConverter), default=None
    )
    @parsing.with_parser
    @components.as_command("user")
    async def user(self, ctx: tanjun_traits.Context, user: typing.Union[users.User, None]) -> None:
        if user is None:
            user = ctx.message.author

        flags = basic.basic_name_grid(user.flags) or "NONE"
        embed = (
            embeds.Embed(
                colour=constants.embed_colour(),
                description=(
                    f"Bot: {user.is_system}\nSystem bot: {user.is_system}\n"
                    f"Joined Discord: {basic.pretify_date(user.created_at)}\n\nFlags\n{flags}"
                ),
                title=f"{user.username}#{user.discriminator}",
                url=f"https://discordapp.com/users/{user.id}",
            )
            .set_thumbnail(user.avatar_url)
            .set_footer(text=str(user.id), icon=user.default_avatar_url)
        )
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )
        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    @help_util.with_parameter_doc(
        "user",
        "The optional argument of a mention or ID of the user to get the avatar for. "
        "If this isn't provided then this command will target the user who triggered it.",
    )
    @help_util.with_command_doc("Get a user's avatar.")
    @parsing.with_greedy_argument(
        "user", converters=(conversion.RESTFulUserConverter, conversion.RESTFulMemberConverter), default=None
    )
    @parsing.with_parser
    @components.as_command("avatar", "pfp")
    async def avatar(self, ctx: tanjun_traits.Context, user: typing.Union[users.User, None]) -> None:

        if user is None:
            user = ctx.message.author

        retry = backoff.Backoff(max_retries=5, maximum=2.0)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )
        avatar = user.avatar_url or user.default_avatar_url
        embed = embeds.Embed(title=str(user), url=str(avatar), colour=constants.embed_colour()).set_image(avatar)

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    @parsing.with_argument("message_id", (snowflakes.Snowflake,))
    @parsing.with_option("channel_id", "--channel", "-c", converters=(snowflakes.Snowflake,), default=None)
    @parsing.with_parser
    @components.as_command("mentions")
    async def mentions(
        self,
        ctx: tanjun_traits.Context,
        message_id: snowflakes.Snowflake,
        channel_id: typing.Optional[snowflakes.Snowflake],
    ) -> None:
        if channel_id is None:
            channel_id = ctx.message.channel_id

        retry = backoff.Backoff()
        error_handler = rest_manager.HikariErrorManager(retry).with_rule(
            (hikari_errors.NotFoundError, hikari_errors.ForbiddenError, hikari_errors.BadRequestError),
            basic.raise_error("Message not found."),
        )
        async for _ in retry:
            with error_handler:
                message = await ctx.client.rest_service.rest.fetch_message(channel_id, message_id)
                break

        retry.reset()
        error_handler.clear_rules(break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError))
        async for _ in retry:
            with error_handler:
                mentions = ", ".join(map(str, message.mentions.users.values())) if message.mentions.users else None
                await ctx.message.reply(f"Mentions: {mentions}" if mentions else "No mentions.")
                break
