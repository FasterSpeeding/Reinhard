from __future__ import annotations

import typing

from hikari.net import errors
from hikari.orm.models import permissions as _permissions
from hikari.orm.models import users as _users

from reinhard.util import command_client
from reinhard.util import command_hooks
from reinhard import sql

if typing.TYPE_CHECKING:
    from hikari import bases as _bases
    from hikari import guilds as _guilds

exports = ["ModerationCluster"]


class ModerationCluster(command_client.CommandCluster):  # TODO: state
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sql_scripts = sql.CachedScripts(pattern=".*star.*")
        self.current_user_id: typing.Optional[_bases.Snowflake] = None
        for command in self.commands:
            command.register_check(self.permission_check)
            command.hooks.on_error = command_hooks.error_hook

    async def load(self) -> None:
        self.current_user_id = (await self._components.rest.fetch_me()).id

    async def pre_execution(
        self, ctx: command_client.Context, **members: _guilds.GuildMember
    ) -> bool:  # TODO: state or not state
        if not ctx.message.guild_id:
            return False

        guild = await ctx.components.rest.fetch_guild(ctx.message.guild_id)
        author_member = ctx.message.member
        own_member = await ctx.components.rest.fetch_member(guild, self.current_user_id)
        target_member = await ctx.components.rest.fetch_member()
        await role_position_check

    async def role_position_check(
        self,
        author: _guilds.GuildMember,
        target_member: _guilds.GuildMember,
        own_member: _guilds.GuildMember,
        guild: _guilds.Guild,
    ) -> None:
        target_position = guild.roles[target_member.roles[0]].position if target_member.roles else -1
        own_position = guild.roles[own_member.roles[0]].position if own_member.roles else -1
        author_position = guild.roles[author.roles[0]].position if author.roles else -1
        if target_position >= own_position:
            raise command_client.CommandError("I cannot target this user.")
        if target_position >= author_position:
            raise command_client.CommandError("You cannot target this user.")

    @staticmethod
    def is_guild(ctx: command_client.Context) -> bool:
        return bool(ctx.message.guild_id)

    @staticmethod
    async def permission_check(ctx: command_client.Context) -> bool:
        required_perms = ctx.command.meta.get("perms", 0)
        current_perms = await ctx.fetch_permissions()

        return (current_perms & _permissions.Permission.ADMINISTRATOR == _permissions.Permission.ADMINISTRATOR) or (
            current_perms & required_perms
        ) == required_perms

        # for permission in _permissions.Permission.__members__.values():
        #    print(permission)
        #    print(ctx.message.author.permissions & permission == permission)

    @command_client.command(meta={"perms": _permissions.BAN_MEMBERS})
    async def ban(self, ctx: command_client.Context, *users: _guilds.GuildMember) -> None:
        result = ""
        for user in list({user.id: user for user in users}.values())[:25]:
            try:
                member = self._fabric.state_registry.get_mandatory_member_by_id(user, ctx.message.guild_id)
                if not member.is_resolved:
                    member = await member

                await ctx.fabric.http_adapter.ban_member(member)
                await self.role_position_check(ctx.message.author, member)
            except errors.NotFoundHTTPError as exc:
                user_repr = f"{user.username}#{user.discriminator}" if user.is_resolved else user.id
                result += f":red_circle: `{user_repr}`: {getattr(exc, 'message', exc)}\n"
            except (command_client.CommandError, errors.HTTPError) as exc:
                result += f":red_circle: `{member.username}#{member.discriminator}`: {getattr(exc, 'message', exc)}\n"
            else:
                result += f":green_circle: `{member.username}#{member.discriminator}`\n"
        await ctx.reply(content=result)

    @command_client.command(meta={"perms": _permissions.KICK_MEMBERS})
    async def kick(self, ctx: command_client.Context, *users: _guilds.GuildMember) -> None:
        await ctx.reply(content=str(users))

    @command_client.command(meta={"perms": _permissions.MUTE_MEMBERS})
    async def mute(self, ctx: command_client.Context, *members: _guilds.GuildMember) -> None:
        ...  # TODO: channel mute vs global and temp vers perm.
