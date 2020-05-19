from __future__ import annotations

import typing

import aiohttp

from hikari import bases
from hikari import colors
from hikari import embeds
from hikari import errors as hikari_errors
from tanjun import clusters
from tanjun import commands
from tanjun import decorators
from tanjun import errors

from reinhard.util import basic
from reinhard.util import command_hooks
from reinhard.util import constants
from reinhard.util import paginators

if typing.TYPE_CHECKING:
    from hikari import applications
    from hikari import users


exports = ["UtilCluster"]


class UtilCluster(clusters.Cluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            *args,
            **kwargs,
            hooks=commands.Hooks(
                on_error=command_hooks.error_hook, on_conversion_error=command_hooks.on_conversion_error
            ),
        )
        self.application: typing.Optional[applications.Application] = None
        self.user: typing.Optional[users.MyUser] = None
        self.paginator_pool = paginators.PaginatorPool(self.components)

    async def load(self) -> None:
        self.application = await self.components.rest.fetch_my_application_info()
        self.user = await self.components.rest.fetch_me()
        await super().load()

    @decorators.command(aliases=("colour",), greedy="color_or_role")
    async def color(self, ctx: commands.Context, color_or_role: typing.Union[colors.Color, bases.Snowflake]) -> None:
        color = color_or_role
        if isinstance(color_or_role, bases.Snowflake):
            if not ctx.message.guild_id:
                raise errors.CommandError("Cannot get a role's colour in a DM channel.")

            try:
                role = (await ctx.components.rest.fetch_roles(ctx.message.guild_id))[color_or_role]
            except (KeyError, hikari_errors.Forbidden, hikari_errors.NotFound):
                raise errors.CommandError("Failed to find role.")
            color = role.color

        await ctx.message.reply(
            embed=embeds.Embed(color=color)
            .add_field(name="RGB", value=str(color.rgb))
            .add_field(name="HEX", value=str(color.hex_code))
        )

    @decorators.command(checks=[lambda ctx: ctx.message.guild_id is not None])
    async def member(self, ctx: commands.Context, member: bases.Snowflake) -> None:
        try:
            member = await ctx.components.rest.fetch_member(guild=ctx.message.guild_id, user=member)
        except (hikari_errors.NotFound, hikari_errors.BadRequest):
            await ctx.message.reply(content="Couldn't find member.")
        else:
            guild = await ctx.components.rest.fetch_guild(guild=ctx.message.guild_id)
            roles = guild.roles
            permissions = roles[ctx.message.guild_id].permissions
            role_list = {}
            for role_id in member.role_ids:
                role = roles[role_id]
                permissions |= role.permissions
                role_list[role.position] = f"{role.name}: {role.id}"
            role_list = dict(sorted(role_list.items(), reverse=True)).values()
            role_list = "\n".join(role_list) + "\n" if role_list else ""
            color = (roles[member.role_ids[0]] if member.role_ids else roles[ctx.message.guild_id]).color
            permissions = basic.basic_name_grid(permissions) or "NONE"
            owner = member.user.id == guild.owner_id
            await ctx.message.reply(
                embed=embeds.Embed(
                    description=(
                        f"Boosting since: {member.premium_since or 'N/A'}\nColor: `{color}`\n"
                        f"\nFlags: {member.user.flags}\nServer Owner {owner}\nIs bot: {member.user.is_system}\n"
                        f"Is system user: {member.user.is_system}\nJoined Discord: {member.user.created_at}\n"
                        f"Joined Server: {member.joined_at}\nNickname: {member.nickname}\n\n"
                        f"Voice chat:\nIs server deafened: {member.is_deaf}\nIs server muted: {member.is_mute}\n\n"
                        f"Roles:\n{role_list}everyone: {ctx.message.guild_id}\n\nPermissions:\n{permissions}"
                    ),
                    color=color,
                    title=f"{member.user.username}#{member.user.discriminator}",
                    url=f"https://discordapp.com/users/{member.user.id}",
                )
                .set_thumbnail(image=member.user.avatar_url)
                .set_footer(text=str(member.user.id), icon=member.user.default_avatar_url)
            )

    @decorators.command(checks=[lambda ctx: ctx.message.guild_id is not None])
    async def role(self, ctx: commands.Context, role: bases.Snowflake) -> None:
        try:
            role = (await ctx.components.rest.fetch_roles(ctx.message.guild_id))[role]
        except (IndexError, hikari_errors.NotFound, hikari_errors.Forbidden):
            await ctx.message.reply(content="Couldn't find role.")
        else:
            permissions = basic.basic_name_grid(role.permissions) or "None"
            await ctx.message.reply(
                embed=embeds.Embed(
                    color=role.color,
                    title=role.name,
                    description=(
                        f"Created at {role.created_at}\nIs hoisted: {role.is_hoisted}\n"
                        f"Is managed: {role.is_managed}\nIs mentionable: {role.is_mentionable}\n"
                        f"Position: {role.position}\n\nPermissions:\n{permissions}"
                    ),
                )
            )

    @decorators.command
    async def user(self, ctx: commands.Context, user: bases.Snowflake) -> None:
        try:
            user = await ctx.components.rest.fetch_user(user)
        except (hikari_errors.NotFound, hikari_errors.BadRequest):
            await ctx.message.reply(content="Couldn't find user.")
        else:
            flags = basic.basic_name_grid(user.flags) or "NONE"
            await ctx.message.reply(
                embed=embeds.Embed(
                    color=constants.EMBED_COLOUR,
                    description=(
                        f"\nIs bot: {user.is_system}\nIs system user: {user.is_system}\n"
                        f"Joined Discord: {user.created_at}\n\nFlags\n{flags}"
                    ),
                    title=f"{user.username}#{user.discriminator}",
                    url=f"https://discordapp.com/users/{user.id}",
                )
                .set_thumbnail(image=user.avatar_url)
                .set_footer(text=str(user.id), icon=user.default_avatar_url)
            )

    @decorators.command(greedy="name")
    async def lyrics(self, ctx: commands.Context, name: str) -> None:
        owner = (
            next(iter(self.application.team.members.values())).user if self.application.team else self.application.owner
        )
        async with aiohttp.ClientSession(
            headers={"User-Agent": f"Reinhard (id:{self.user}; owner:{owner.id})"}
        ) as session:
            response = await session.get("https://lyrics.tsu.sh/v1", params={"q": name})
            if response.status == 404:
                await ctx.message.safe_reply(content=f"Couldn't find the lyrics for `{name}`")
                return
            if response.status >= 500:
                await ctx.message.safe_reply(content=f"Failed to fetch lyrics due to server error {response.status}")
                return

            try:
                data = await response.json()
            except ValueError as exc:
                await ctx.message.safe_reply(content=f"Invalid data returned by server: ```python\n{exc}```")
            else:
                icon = data["song"].get("icon")
                title = data["song"]["full_title"]
                response_paginator = (
                    (
                        "",
                        embeds.Embed(description=page, color=constants.EMBED_COLOUR)
                        .set_footer(text=f"Page {index}")
                        .set_author(icon=icon, name=title),
                    )
                    for page, index in paginators.string_paginator(data["content"].splitlines() or ["..."])
                )
                content, embed = next(response_paginator)
                message = await ctx.message.safe_reply(content=content, embed=embed)
                await self.paginator_pool.register_message(
                    message=message,
                    paginator=paginators.ResponsePaginator(
                        generator=response_paginator, first_entry=(content, embed), authors=(ctx.message.author.id,)
                    ),
                )
