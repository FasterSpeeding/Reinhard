from __future__ import annotations
import typing

from hikari.orm.models import members as _members
from hikari.orm.models import permissions as _permissions
from hikari.orm.models import users as _users


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

    def permission_check(self, ctx: command_client.Context) -> bool:
        required_perms = ctx.command.meta["perms"]
        return ctx.message.author.id == 115590097100865541  # TODO: this

    @command_client.command(meta={"perms": _permissions.BAN_MEMBERS})
    async def ban(self, ctx: command_client.Context, *members: typing.Union[_members.Member, _users.User]) -> None:
        await ctx.reply(content=str(members))

    @command_client.command(meta={"perms": _permissions.KICK_MEMBERS})
    async def kick(self, ctx: command_client.Context, *users: _members.Member) -> None:
        await ctx.reply(content=str(users))

    @command_client.command(meta={"perms": _permissions.MUTE_MEMBERS})
    async def mute(self, ctx: command_client.Context, *members: _members.Member) -> None:
        ...  # TODO: channel mute vs global and temp vers perm.
