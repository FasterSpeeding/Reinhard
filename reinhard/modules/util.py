from __future__ import annotations

__all__: typing.Sequence[str] = ["UtilComponent"]

import typing

from hikari import colors
from hikari import embeds
from hikari import errors as hikari_errors
from hikari import snowflakes
from hikari import users
from tanjun import components
from tanjun import conversion
from tanjun import errors as tanjun_errors
from tanjun import hooks
from tanjun import parsing
from tanjun import traits
from yuyo import backoff

from reinhard.util import basic
from reinhard.util import command_hooks
from reinhard.util import constants
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import guilds


__exports__ = ["UtilComponent"]


class UtilComponent(components.Component):
    __slots__: typing.Sequence[str] = ("own_user",)

    def __init__(self) -> None:
        super().__init__(
            hooks=hooks.Hooks(error=command_hooks.error_hook, conversion_error=command_hooks.on_conversion_error),
        )
        self.own_user: typing.Optional[users.OwnUser] = None

    async def open(self) -> None:
        if self.client is None:
            raise RuntimeError("Cannot start this component before binding a client")

        retry = backoff.Backoff(max_retries=4)
        error_manager = rest_manager.HikariErrorManager(retry)

        async for _ in retry:
            with error_manager:
                self.own_user = await self.client.rest.rest.fetch_my_user()
                break

        else:
            self.own_user = await self.client.rest.rest.fetch_my_user()

        await super().open()

    @parsing.greedy_argument("color", converters=(conversion.ColorConverter, conversion.SnowflakeConverter))
    @components.command("color", "colour")
    async def color(self, ctx: traits.Context, color_or_role: typing.Union[colors.Color, snowflakes.Snowflake]) -> None:
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
        ).with_rule((KeyError,), basic.raise_command_error("Failed to find role."))

        if isinstance(color_or_role, snowflakes.Snowflake):
            if ctx.message.guild_id is None:
                raise tanjun_errors.CommandError("Cannot get a role's colour in a DM channel.")

            async for _ in retry:
                with error_manager:
                    role = (await ctx.client.rest.rest.fetch_roles(ctx.message.guild_id))[color_or_role]
                    break

            else:
                raise tanjun_errors.CommandError("Couldn't fetch role in time")

            color_or_role = role.color

        embed = (
            embeds.Embed(color=color_or_role)
            .add_field(name="RGB", value=str(color_or_role.rgb))
            .add_field(name="HEX", value=str(color_or_role.hex_code))
        )
        retry.reset()
        error_manager.clear_rules(break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError))

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    # # @decorators.command
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

    @parsing.argument("member", converters=(conversion.MemberConverter, conversion.SnowflakeConverter), default=None)
    @components.command("member", checks=[lambda ctx: ctx.message.guild_id is not None])
    async def member(
        self, ctx: traits.Context, member: typing.Union[guilds.Member, snowflakes.Snowflake, None]
    ) -> None:
        assert ctx.message.guild_id is not None  # This is asserted by a previous check.
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(retry, break_on=(hikari_errors.ForbiddenError,)).with_rule(
            (hikari_errors.BadRequestError, hikari_errors.NotFoundError,),
            basic.raise_command_error("Couldn't find member."),
        )

        if member is None and ctx.message.member:
            member = ctx.message.member

        elif member is None:
            member = ctx.message.author.id

        if isinstance(member, snowflakes.Snowflake):
            async for _ in retry:
                with error_manager:
                    member = await ctx.client.rest.rest.fetch_member(guild=ctx.message.guild_id, user=member)
                    break

            else:
                if retry.is_depleted:
                    raise tanjun_errors.CommandError("Couldn't get member in time")

                return

        retry.reset()
        error_manager.clear_rules(break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError,))
        async for _ in retry:
            with error_manager:
                guild = await ctx.client.rest.rest.fetch_guild(guild=ctx.message.guild_id)
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
        roles = "\n".join(map("{0.name}: {0.id}".format, ordered_roles.values())) + "\n" if ordered_roles else ""

        for role in ordered_roles.values():
            if role.color:
                color = role.color
                break
        else:
            color = colors.Color(0)

        permissions = basic.basic_name_grid(permissions) or "NONE"
        member_information = [
            f"Color: {color}",
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
                description=(
                    "\n".join(member_information)
                    + f"\n\nFlags: {member.user.flags}\n\nRoles:\n{roles}everyone: {ctx.message.guild_id}\n\n"
                    f"Permissions:\n{permissions}"
                ),
                color=color,
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

    @parsing.argument("role", converters=(conversion.RoleConverter, conversion.SnowflakeConverter))
    @components.command("role", checks=[lambda ctx: ctx.message.guild_id is not None])
    async def role(self, ctx: traits.Context, role: typing.Union[guilds.Role, snowflakes.Snowflake]) -> None:
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        ).with_rule((StopAsyncIteration,), basic.raise_command_error("Couldn't find role."),)
        assert ctx.message.guild_id is not None  # This is asserted by a previous check.

        if isinstance(role, snowflakes.Snowflake):
            async for _ in retry:
                with error_manager:
                    roles = await ctx.client.rest.rest.fetch_roles(ctx.message.guild_id)
                    role = next(filter(self.filter_role(role), roles))
                    break

            else:
                if retry.is_depleted:
                    raise tanjun_errors.CommandError("Couldn't get role in time")

                return

        permissions = basic.basic_name_grid(role.permissions) or "None"
        role_information = [f"Created: {basic.pretify_date(role.created_at)}", f"Position: {role.position}"]

        if role.color:
            role_information.append(f"Color: `{role.color}`")

        if role.is_hoisted:
            role_information.append("Member list hoisted")

        if role.is_managed:
            role_information.append("Managed by an integration")

        if role.is_mentionable:
            role_information.append("Can be mentioned")

        retry.reset()
        error_manager.clear_rules(break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError))
        embed = embeds.Embed(
            color=role.color,
            title=role.name,
            description="\n".join(role_information) + f"\n\nPermissions:\n{permissions}",
        )

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break

    @parsing.argument("user", converters=(conversion.UserConverter, conversion.SnowflakeConverter), default=None)
    @components.command("user")
    async def user(self, ctx: traits.Context, user: typing.Union[users.User, snowflakes.Snowflake, None]) -> None:
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.HikariErrorManager(retry, break_on=(hikari_errors.ForbiddenError,)).with_rule(
            (hikari_errors.BadRequestError, hikari_errors.NotFoundError),
            basic.raise_command_error("Couldn't find user."),
        )
        if user is None:
            user = ctx.message.author

        elif isinstance(user, snowflakes.Snowflake):
            async for _ in retry:
                with error_manager:
                    user = await ctx.client.rest.rest.fetch_user(user)
                    break

            else:
                if retry.is_depleted:
                    raise tanjun_errors.CommandError("Couldn't fetch user in time")

                return

        flags = basic.basic_name_grid(user.flags) or "NONE"
        embed = (
            embeds.Embed(
                color=constants.EMBED_COLOUR,
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
        retry.reset()
        error_manager.clear_rules(break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError))

        async for _ in retry:
            with error_manager:
                await ctx.message.reply(embed=embed)
                break
