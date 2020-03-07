from __future__ import annotations
import typing

from hikari.net import errors
from hikari.orm.models import members as _members
from hikari.orm.models import permissions as _permissions
from hikari.orm.models import users as _users


from reinhard.util import basic as util
from reinhard.util import command_client
from reinhard import sql


exports = ["ModerationCluster"]


class ModerationCluster(command_client.CommandCluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.sql_scripts = sql.CachedScripts(pattern=".*star.*")
        self.add_cluster_event(command_client.CommandEvents.ERROR, self.client.on_error)
        for command in self.cluster_commands:
            command.register_check(self.permission_check)

    async def role_position_check(self, author: _members.Member, target_member: _members.Member) -> None:
        own_member = self._fabric.state_registry.get_mandatory_member_by_id(
            self._fabric.state_registry.me.id, target_member.guild.id
        )
        if not own_member.is_resolved:
            own_member = await own_member
        if not (guild := target_member.guild).is_resolved:
            guild = await guild

        target_postion = guild.roles[target_member.roles[0]].position if target_member.roles else -1
        own_position = guild.roles[own_member.roles[0]].position if own_member.roles else -1
        author_position = guild.roles[author.roles[0]].position if author.roles else -1
        if target_postion >= own_position:
            raise command_client.CommandError("I cannot target this user.")
        if target_postion >= author_position:
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
    async def ban(self, ctx: command_client.Context, *users: _users.User) -> None:
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
    async def kick(self, ctx: command_client.Context, *users: _members.Member) -> None:
        await ctx.reply(content=str(users))

    @command_client.command(meta={"perms": _permissions.MUTE_MEMBERS})
    async def mute(self, ctx: command_client.Context, *members: _members.Member) -> None:
        ...  # TODO: channel mute vs global and temp vers perm.
