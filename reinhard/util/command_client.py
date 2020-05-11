from __future__ import annotations

__all__ = [
    "command",
    "Command",
    "CommandClient",
    "CommandCluster",
]

import abc
import asyncio
import contextlib
import enum
import importlib
import inspect
import logging
import types
import typing

import attr
from hikari import bases
from hikari import errors as hikari_errors
from hikari import permissions
from hikari.events import message as message_events
from hikari.events import other as other_events
from hikari.internal import more_collections

from reinhard.util import parser
from reinhard.util import errors

if typing.TYPE_CHECKING:
    from hikari import messages
    from hikari.clients import components as _components
    from hikari.clients import shards as _shards
    from hikari.events import base as base_events
    from hikari.state import dispatchers as _dispatchers

    CheckLikeT = typing.Callable[["Context"], typing.Union[bool, typing.Coroutine[typing.Any, typing.Any, bool]]]
    CommandFunctionT = typing.Callable[[...], typing.Coroutine[typing.Any, typing.Any, None]]

SEND_MESSAGE_PERMISSIONS = permissions.Permission.VIEW_CHANNEL | permissions.Permission.SEND_MESSAGES
ATTACH_FILE_PERMISSIONS = SEND_MESSAGE_PERMISSIONS | permissions.Permission.ATTACH_FILES

# TODO: stuff like get_guild_prefixes?


class TriggerTypes(enum.Enum):
    PREFIX = enum.auto()
    MENTION = enum.auto()  # TODO: trigger commands with a mention


@attr.attrs(init=True, kw_only=True, slots=True)
class Context:
    content: str = attr.attrib()

    components: _components.Components = attr.attrib()

    message: messages.Message = attr.attrib()
    """The message that triggered this command."""

    trigger: str = attr.attrib()
    """The string prefix or mention that triggered this command."""

    trigger_type: TriggerTypes = attr.attrib()
    """The mention or prefix that triggered this event."""

    triggering_name: str = attr.attrib(default=None)
    """The command alias that triggered this command."""

    command: AbstractCommand = attr.attrib(default=None)

    @property
    def cluster(self) -> AbstractCommandCluster:
        return self.command.cluster

    def prune_content(self, length: int) -> None:
        self.content = self.content[length:]

    def set_command_trigger(self, trigger: str) -> None:
        self.triggering_name = trigger

    def set_command(self, command_obj: AbstractCommand) -> None:
        self.command = command_obj

    @property
    def shard(self) -> typing.Optional[_shards.ShardClient]:
        return self.components.shards.get(self.shard_id, None)

    @property
    def shard_id(self) -> int:
        return (self.message.guild_id >> 22) % self.components.shards[0].shard_count if self.message.guild_id else 0


HookLikeT = typing.Callable[[Context], typing.Coroutine[typing.Any, typing.Any, None]]


@attr.attrs(init=True, kw_only=True, slots=True)
class CommandHooks:  # TODO: this
    pre_execution: typing.Callable[[Context, ...], typing.Coroutine[typing.Any, typing.Any, bool]] = attr.attrib(
        default=None
    )
    post_execution: HookLikeT = attr.attrib(default=None)
    on_conversion_error: typing.Callable[
        [Context, errors.ConversionError], typing.Coroutine[typing.Any, typing.Any, typing.Any]
    ] = attr.attrib(default=None)
    on_error: typing.Callable[[Context, BaseException], typing.Coroutine[typing.Any, typing.Any, None]] = attr.attrib(
        default=None
    )
    on_success: HookLikeT = attr.attrib(default=None)
    on_ratelimit: HookLikeT = attr.attrib(default=None)  # TODO: implement?

    def set_pre_execution(
        self, hook: typing.Callable[[Context, ...], typing.Coroutine[typing.Any, typing.Any, bool]]
    ) -> typing.Callable[[Context, ...], typing.Coroutine[typing.Any, typing.Any, bool]]:
        if self.pre_execution:
            raise ValueError("Pre-execution hook already set.")  # TODO: value error?
        self.pre_execution = hook
        return hook

    def set_post_execution(self, hook: HookLikeT) -> HookLikeT:  # TODO: better typing
        if self.post_execution:
            raise ValueError("Post-execution hook already set.")
        self.post_execution = hook
        return hook

    def set_on_conversion_error(
        self,
        hook: typing.Callable[[Context, errors.ConversionError], typing.Coroutine[typing.Any, typing.Any, typing.Any]],
    ) -> typing.Callable[[Context, errors.ConversionError], typing.Coroutine[typing.Any, typing.Any, typing.Any]]:
        if self.on_conversion_error:
            raise ValueError("On conversion error hook already set.")
        self.on_conversion_error = hook
        return hook

    def set_on_error(
        self, hook: typing.Callable[[Context, BaseException], typing.Coroutine[typing.Any, typing.Any, None]]
    ) -> typing.Callable[[Context, BaseException], typing.Coroutine[typing.Any, typing.Any, None]]:
        if self.on_error:
            raise ValueError("On error hook already set.")
        self.on_error = hook
        return hook

    def set_on_success(self, hook: HookLikeT) -> HookLikeT:
        if self.on_success:
            raise ValueError("On success hook already set.")
        self.on_success = hook
        return hook

    async def trigger_pre_execution_hooks(
        self, ctx: Context, *args, extra_hooks: typing.Optional[typing.Sequence[CommandHooks]] = None, **kwargs,
    ) -> bool:
        result = True
        if self.pre_execution:
            result = await self.pre_execution(ctx, *args, **kwargs)

        for hook in extra_hooks or more_collections.EMPTY_SEQUENCE:
            if hook.pre_execution:  # TODO: does this matter?
                result = result and await hook.pre_execution(ctx, *args, **kwargs)  # TODO: for consistency
        return result

    async def trigger_on_conversion_error_hooks(
        self,
        ctx: Context,
        exception: errors.ConversionError,
        *,
        extra_hooks: typing.Optional[typing.Sequence[CommandHooks]] = None,
    ) -> None:
        if self.on_conversion_error:
            await self.on_conversion_error(ctx, exception)

        for hook in extra_hooks or more_collections.EMPTY_SEQUENCE:
            if hook.on_conversion_error:
                await hook.on_conversion_error(ctx, exception)

    async def trigger_error_hooks(
        self,
        ctx: Context,
        exception: BaseException,
        *,
        extra_hooks: typing.Optional[typing.Sequence[CommandHooks]] = None,
    ) -> None:
        if self.on_error:
            await self.on_error(ctx, exception)

        for hook in extra_hooks or more_collections.EMPTY_SEQUENCE:
            if hook.on_error:
                await hook.on_error(ctx, exception)

    async def trigger_on_success_hooks(
        self, ctx: Context, *, extra_hooks: typing.Optional[typing.Sequence[CommandHooks]] = None,
    ) -> None:
        if self.on_success:
            await self.on_success(ctx)

        for hook in extra_hooks or more_collections.EMPTY_SEQUENCE:
            if hook.on_success:
                await hook.on_success(ctx)

    async def trigger_post_execution_hooks(
        self, ctx: Context, *, extra_hooks: typing.Optional[typing.Sequence[CommandHooks]] = None,
    ) -> None:
        if self.post_execution:
            await self.post_execution(ctx)

        for hook in extra_hooks or more_collections.EMPTY_SEQUENCE:
            if hook.post_execution:
                await hook.post_execution(ctx)


class Executable(abc.ABC):
    @abc.abstractmethod
    async def execute(self, ctx: Context, *, hooks: typing.Optional[typing.Sequence[CommandHooks]] = None) -> bool:
        """
        Used to execute an entity based on a :class:`Context` object.

        Args:
            ctx:
                The :class:`Context` object to execute this with.
        """


class ExecutableCommand(Executable, abc.ABC):
    @abc.abstractmethod
    async def execute(
        self, ctx: Context, *, hooks: typing.Optional[typing.Sequence[CommandHooks]] = None
    ) -> typing.Literal[True]:
        """
        Used to execute an entity based on a :class:`Context` object.

        Args:
            ctx:
                The :class:`Context` object to execute this with.
        """

    @abc.abstractmethod
    async def check(self, ctx: Context) -> bool:
        """
        Used to check if this entity should be executed based on a Context.

        Args:
            ctx:
                The :class:`Context` object to check.

        Returns:
            The :class:`bool` of whether this executable is a match for the given context.
        """


@attr.attrs(init=True, kw_only=True)
class AbstractCommand(ExecutableCommand, abc.ABC):

    triggers: typing.Tuple[str, ...] = attr.attrib()
    """The triggers used to activate this command in chat along with a prefix."""

    meta: typing.MutableMapping[typing.Any, typing.Any] = attr.attrib(factory=dict)

    hooks: CommandHooks = attr.attrib(factory=CommandHooks)

    level: int = attr.attrib()
    """The user access level that'll be required to execute this command, defaults to 0."""

    parser: typing.Optional[parser.AbstractCommandParser]

    @abc.abstractmethod
    def __call__(self, *args, **kwargs) -> typing.Coroutine[typing.Any, typing.Any, typing.Any]:
        ...

    @abc.abstractmethod
    def bind_cluster(self, cluster: AbstractCommandCluster) -> None:
        ...

    @abc.abstractmethod
    def check_prefix(self, content: str) -> typing.Optional[str]:
        ...

    @abc.abstractmethod
    def check_prefix_from_context(self, ctx: Context) -> typing.Optional[str]:
        ...

    @property
    @abc.abstractmethod
    def cluster(self) -> typing.Optional[AbstractCommandCluster]:
        ...

    @abc.abstractmethod
    def deregister_check(self, check: CheckLikeT) -> None:
        ...

    @property
    @abc.abstractmethod
    def docstring(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @abc.abstractmethod
    def register_check(self, check: CheckLikeT) -> None:
        ...

    @abc.abstractmethod  # TODO: differentiate between command and command group.
    def _create_parser(
        self, func: typing.Callable[[...], typing.Coroutine[typing.Any, typing.Any, typing.Any]], **kwargs: typing.Any
    ) -> parser.AbstractCommandParser:
        ...


# TODO: be more consistent with "func", "function", etc etc
def generate_trigger(function: typing.Optional[CommandFunctionT] = None) -> str:
    """Get a trigger for this command based on it's function's name."""
    return function.__name__.replace("_", " ")


async def run_checks(ctx: Context, checks: typing.Sequence[CheckLikeT]) -> None:
    failed: typing.Sequence[typing.Tuple[CheckLikeT, typing.Optional[Exception]]] = []
    for check in checks:
        try:
            result = check(ctx)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as exc:
            failed.append((check, exc))
        else:
            if not result:
                failed.append((check, None))

    if failed:
        raise errors.FailedCheck(tuple(failed))


@attr.attrs(init=False, slots=True, repr=False)
class Command(AbstractCommand):
    _checks: typing.Sequence[CheckLikeT]

    _func: CommandFunctionT = attr.attrib()

    logger: logging.Logger

    _cluster: typing.Optional[AbstractCommandCluster] = attr.attrib(default=None)

    def __init__(
        self,
        func: typing.Optional[CommandFunctionT],
        trigger: typing.Optional[str] = None,
        /,
        *,
        aliases: typing.Optional[typing.Sequence[str]] = None,
        hooks: typing.Optional[CommandHooks] = None,
        level: int = 0,
        meta: typing.Optional[typing.MutableMapping[typing.Any, typing.Any]] = None,
        cluster: typing.Optional[AbstractCommandCluster] = None,
        greedy: typing.Optional[str] = None,
    ) -> None:
        if trigger is None:
            trigger = generate_trigger(func)
        super().__init__(
            hooks=hooks or CommandHooks(),
            level=level,
            meta=meta or {},
            triggers=tuple(
                trig for trig in (trigger, *(aliases or more_collections.EMPTY_COLLECTION)) if trig is not None
            ),
        )
        self.logger = logging.getLogger(type(self).__qualname__)
        self._checks = []
        self._func = func
        self.parser = self._create_parser(self._func, greedy=greedy)
        if cluster:
            self.bind_cluster(cluster)

    def __call__(self, *args, **kwargs) -> typing.Coroutine[typing.Any, typing.Any, typing.Any]:
        return self._func(*args, **kwargs)

    def __repr__(self) -> str:
        return f"Command({'|'.join(self.triggers)})"

    def bind_cluster(self, cluster: AbstractCommandCluster) -> None:
        # This ensures that the cluster will always be passed-through as `self`.
        self._func = types.MethodType(self._func, cluster)
        self._cluster = cluster
        # Now that we know self will automatically be passed, we need to trim the parameters again.
        self.parser.trim_parameters(1)
        # Before the parser can be used, we need to resolve it's converters and check them against the bot's declared
        # gateway intents.
        self.parser.components_hook(cluster.components)

    async def check(self, ctx: Context) -> None:
        return await run_checks(ctx, self._checks)

    def check_prefix(self, content: str) -> typing.Optional[str]:
        for trigger in self.triggers:
            if content.startswith(trigger):
                return trigger
        return None

    def check_prefix_from_context(self, ctx: Context) -> typing.Optional[str]:
        return self.check_prefix(ctx.content)

    @property
    def cluster(self) -> typing.Optional[AbstractCommandCluster]:
        return self._cluster

    def deregister_check(self, check: CheckLikeT) -> None:
        try:
            self._checks.remove(check)
        except ValueError:
            raise ValueError("Command Check not found.")

    @property
    def docstring(self) -> str:
        return inspect.getdoc(self._func)

    async def execute(self, ctx: Context, *, hooks: typing.Optional[typing.Sequence[CommandHooks]] = None) -> bool:
        ctx.set_command(self)
        if self.parser:
            try:
                args, kwargs = self.parser.parse(ctx)
            except errors.ConversionError as exc:
                await self.hooks.trigger_on_conversion_error_hooks(ctx, exc, extra_hooks=hooks)
                self.logger.debug("Command %s raised a Conversion Error: %s", self, exc)
                return True
        else:
            args, kwargs = more_collections.EMPTY_SEQUENCE, more_collections.EMPTY_DICT

        try:
            if await self.hooks.trigger_pre_execution_hooks(ctx, *args, **kwargs, extra_hooks=hooks) is False:
                return True
            await self._func(ctx, *args, **kwargs)
        except errors.CommandError as exc:
            with contextlib.suppress(hikari_errors.HTTPError):  # TODO: better permission handling?
                response = str(exc)
                await ctx.message.reply(content=response if len(response) <= 2000 else response[:1997] + "...")
        except Exception as exc:
            await self.hooks.trigger_error_hooks(ctx, exc, extra_hooks=hooks)
            raise exc
        else:
            await self.hooks.trigger_on_success_hooks(ctx, extra_hooks=hooks)
        finally:
            await self.hooks.trigger_post_execution_hooks(ctx, extra_hooks=hooks)

        return True  # TODO: necessary?

    @property
    def name(self) -> str:
        """Get the name of this command."""
        return self._func.__name__

    def register_check(self, check: CheckLikeT) -> None:
        self._checks.append(check)

    def _create_parser(
        self, func: typing.Callable[[...], typing.Coroutine[typing.Any, typing.Any, typing.Any]], **kwargs: typing.Any
    ) -> parser.AbstractCommandParser:
        return parser.CommandParser(func=func, **kwargs)


class CommandGroup(AbstractCommand):
    _cluster: typing.Optional[AbstractCommandCluster] = attr.attrib(default=None)

    _checks: typing.Sequence[CheckLikeT]

    commands: typing.Sequence[AbstractCommand]

    logger: logging.Logger

    master_command: typing.Optional[AbstractCommand]

    def __init__(
        self,
        name: typing.Optional[str],
        *,
        master_command: typing.Optional[AbstractCommand] = None,
        # ? aliases: typing.Optional[typing.Sequence[str]] = None,
        hooks: typing.Optional[CommandHooks] = None,
        level: int = 0,
        meta: typing.Optional[typing.MutableMapping[typing.Any, typing.Any]] = None,
        cluster: typing.Optional[AbstractCommandCluster] = None,
    ) -> None:
        super().__init__(
            triggers=(name,), meta=meta or {}, hooks=hooks or CommandHooks(), level=level,
        )
        self._checks = []
        self._cluster = cluster
        self.commands = []
        self.logger = logging.getLogger(type(self).__qualname__)
        self.master_command = master_command

    def __call__(self, *args, **kwargs) -> typing.Coroutine[typing.Any, typing.Any, typing.Any]:
        if self.master_command:
            return self.master_command()
        raise TypeError("Command group without top-level command is not callable.")

    def bind_cluster(self, cluster: AbstractCommandCluster) -> None:
        self._cluster = cluster
        if self.master_command:
            self.master_command.bind_cluster(cluster)
        for command_obj in self.commands:
            command_obj.bind_cluster(cluster)

    async def check(self, ctx: Context) -> None:
        return await run_checks(ctx, self._checks)

    def check_prefix(self, content: str) -> typing.Optional[str]:
        if content.startswith(self.name):
            return self.name
        return None

    def check_prefix_from_context(self, ctx: Context) -> typing.Optional[str]:
        return self.check_prefix(ctx.content)

    @property
    def cluster(self) -> typing.Optional[AbstractCommandCluster]:
        return self._cluster

    def deregister_check(self, check: CheckLikeT) -> None:
        try:
            self._checks.remove(check)
        except ValueError:
            raise ValueError("Command Check not found.")

    @property
    def docstring(self) -> str:
        return inspect.getdoc(self)

    async def execute(
        self, ctx: Context, *, hooks: typing.Optional[typing.Sequence[CommandHooks]] = None
    ) -> typing.Literal[True]:
        hooks = hooks or []
        hooks.append(self.hooks)
        for command_obj in self.commands:
            if await command_obj.check(ctx):
                await command_obj.execute(ctx, hooks=hooks)
                break
        else:
            if self.master_command and await self.master_command.check(ctx):
                await self.master_command.execute(ctx, hooks=hooks)
        return True

    @property
    def name(self) -> str:
        return self.triggers[0]

    def register_check(self, check: CheckLikeT) -> None:
        self._checks.append(check)

    def set_master_command(self, command_obj: AbstractCommand) -> AbstractCommand:
        self.master_command = command_obj
        return command_obj


def command(__arg=..., *, cls: typing.Type[AbstractCommand] = Command, **kwargs):
    def decorator(coro_fn):
        return cls(coro_fn, **kwargs)

    return decorator if __arg is ... else decorator(__arg)


def event(event_: base_events.HikariEvent):  # TODO: typing annotation support
    def decorator(coro_fn):
        coro_fn.__event__ = event_
        return coro_fn

    return decorator


def group(
    name: str,
    *,
    group_class: typing.Type[AbstractCommand] = CommandGroup,
    command_class: typing.Type[AbstractCommand] = Command,
    **kwargs,
):  # TODO: test this
    def decorator(coro_fn):
        return group_class(name=name, master_command=command_class(coro_fn, name=""), **kwargs)

    return decorator


@attr.attrs(init=True, kw_only=True)
class AbstractCommandCluster(Executable):  # TODO: Executable  TODO: proper type annotations
    client: CommandClient = attr.attrib()

    components: _components.Components = attr.attrib()

    hooks: CommandHooks = attr.attrib(factory=CommandHooks)

    started: bool = attr.attrib()

    @abc.abstractmethod
    async def load(self) -> None:
        ...

    @abc.abstractmethod
    async def unload(self) -> None:
        ...

    # @abc.abstractmethod
    # def bind_client(self, client: CommandClient) -> None:  # TODO: This?
    #     ...

    @abc.abstractmethod
    def get_cluster_event_listeners(self) -> typing.Sequence[typing.Tuple[str, _dispatchers.EventCallbackT]]:
        ...

    @abc.abstractmethod
    async def get_command_from_context(self, ctx: Context) -> typing.AsyncIterator[typing.Tuple[AbstractCommand, str]]:
        ...

    @abc.abstractmethod
    def get_command_from_name(self, content: str) -> typing.Iterator[typing.Tuple[AbstractCommand, str]]:
        """
        Get a command based on a message's content (minus prefix) from the loaded commands if any command triggers are
        found in the content.

        Args:
            content:
                The string content to try and find a command for (minus the triggering prefix).

        Returns:
            A :class:`typing.AsyncIterator` of a :class:`typing.Tuple` of a :class:`AbstractCommand`
            derived object and the :class:`str` trigger that was matched.
        """

    @abc.abstractmethod
    def register_command(self, command_obj: AbstractCommand, bind: bool = False) -> None:
        """
        Register a command in this cluster.

        Args:
            func:
                The Coroutine Function to be called when executing this command.
            *aliases:
                More string triggers for this command.
            trigger:
                The string that will be this command's main trigger.
            bind:
                If this command should be binded to the cluster. Meaning that
                self will be passed to it and it will be added as an attribute.
        """

    @abc.abstractmethod
    def deregister_command(self, command_obj: AbstractCommand) -> None:
        """
        Unregister a command in this cluster.

        Args:
            command_obj:
                The command object to remove.

        Raises:
            ValueError:
                If the passed command object wasn't found.
        """


class CommandCluster(AbstractCommandCluster):

    commands: typing.Sequence[AbstractCommand]
    """A list of the commands that are loaded in this cluster."""

    logger: logging.Logger
    """The class wide logger."""

    def __init__(
        self, client: CommandClient, components: _components.Components, *, hooks: typing.Optional[CommandHooks] = None
    ) -> None:
        AbstractCommandCluster.__init__(
            self, client=client, components=components, hooks=hooks or CommandHooks(), started=False
        )
        self.logger = logging.getLogger(type(self).__qualname__)
        self.commands = []
        self.bind_commands()
        self.bind_listeners()

    async def load(self) -> None:
        ...

    async def unload(self) -> None:
        ...

    async def access_check(self, command_obj: AbstractCommand, message: messages.Message) -> bool:
        """
        Used to check if a command can be accessed by the calling user and in the calling channel/guild.

        Args:
            command_obj:
                The :class:`AbstractCommand` derived object to check access levels for.
            message:
                The :class:`messages.Message` object to check access levels for.

        Returns:
            A :class:`bool` representation of whether this command can be accessed.
        """
        return self.components.config.access_levels.get(message.author.id, 0) >= command_obj.level  # TODO: sql filter.

    def bind_commands(self) -> None:
        """
        Loads any commands that are attached to this class into `cluster_commands`.

        Raises:
            ValueError:
                if the commands for this cluster have already been binded or if any duplicate triggers are found while
                loading commands.
        """
        if self.commands:  # TODO: overwrite commands?
            raise ValueError(
                "Cannot bind commands in cluster '{self.__class__.__name__}' when commands have already been binded."
            )
        for name, command_obj in inspect.getmembers(self, predicate=lambda attr: isinstance(attr, AbstractCommand)):
            self.register_command(command_obj, bind=True)
            self.logger.debug(
                "Binded command %s in %s cluster.", command_obj.name, self.__class__.__name__,
            )
        self.commands.sort(key=lambda comm: comm.name, reverse=True)  # TODO: why was this reversed again?

    def bind_listeners(self) -> None:
        """Used to add event listeners from all loaded command clusters to hikari's internal event listener."""
        for _, function in self.get_cluster_event_listeners():
            self.logger.debug(f"Registering {function.__event__} event listener for command client.")
            self.components.event_dispatcher.add_listener(function.__event__, function)

    def get_cluster_event_listeners(self) -> typing.Sequence[typing.Tuple[str, _dispatchers.EventCallbackT]]:
        """Get a generator of the event listeners attached to this cluster."""
        return inspect.getmembers(self, predicate=lambda obj: hasattr(obj, "__event__"))

    async def execute(self, ctx: Context, *, hooks: typing.Optional[typing.Sequence[CommandHooks]] = None) -> bool:
        async for command_obj, trigger in self.get_command_from_context(ctx):
            ctx.set_command_trigger(trigger)
            ctx.prune_content(len(trigger) + 1)  # TODO: no space? also here?
            hooks = hooks or []
            hooks.append(self.hooks)
            await command_obj.execute(ctx, hooks=hooks)
            return True
        return False

    async def get_command_from_context(self, ctx: Context) -> typing.AsyncIterator[typing.Tuple[AbstractCommand, str]]:
        for command_obj in self.commands:
            if (trigger := command_obj.check_prefix_from_context(ctx)) is None:
                continue

            try:
                await command_obj.check(ctx)
            except errors.FailedCheck:
                continue
            else:
                if await self.access_check(command_obj, ctx.message):
                    yield command_obj, trigger

    def get_command_from_name(self, content: str) -> typing.Iterator[typing.Tuple[AbstractCommand, str]]:
        for command_obj in self.commands:
            if prefix := command_obj.check_prefix(content):
                yield command_obj, prefix

    def register_command(self, command_obj: AbstractCommand, *, bind: bool = False) -> None:  # TODO: decorator?
        if bind:
            command_obj.bind_cluster(self)
        for trigger in command_obj.triggers:
            if list(self.get_command_from_name(trigger)):
                self.logger.warning(
                    "Possible overlapping trigger '%s' found in %s cluster.", trigger, self.__class__.__name__,
                )
        self.commands.append(command_obj)

    def deregister_command(self, command_obj: AbstractCommand) -> None:
        try:
            self.commands.remove(command_obj)
        except ValueError:
            raise ValueError("Invalid command passed for this cluster.") from None


class AbstractCommandClient(AbstractCommandCluster, abc.ABC):
    @abc.abstractmethod
    async def deregister_cluster(self, cluster: str) -> AbstractCommandCluster:
        ...

    @abc.abstractmethod
    async def get_global_command_from_context(self, ctx: Context) -> typing.AsyncIterator[AbstractCommand]:
        """
        Used to get a command from on a messages create event's context.

        Args:
            ctx:
                The :class:`Context` for this message create event.

        Returns:
            An async iterator of :class:`AbstractCommand` derived objects that matched this context.
        """

    @abc.abstractmethod
    def get_global_command_from_name(self, content: str) -> typing.Iterator[typing.Tuple[AbstractCommand, str]]:
        """
        Used to get a command from on a string.

        Args:
            content:
                The :class:`str` (without any prefixes) to get a command from.

        Returns:
            A :class:`typing.Iterator` of :class:`typing.Tuple` of matching
            :class:`AbstractCommand` derived objects and the :class:`str` trigger that was matched.
        """

    @abc.abstractmethod
    def load_from_modules(self, *modules: str) -> None:
        """
        Used to load modules based on string paths.

        Args:
            *modules:
                The :class:`str` paths of modules to load from (in the format of `root.dir.module`)
        """

    @abc.abstractmethod
    async def register_cluster(
        self, cluster: typing.Union[AbstractCommandCluster, typing.Type[AbstractCommandCluster]]
    ) -> None:
        ...


class CommandClient(AbstractCommandClient, CommandCluster):
    """
    The central client that all command clusters will be binded to. This extends :class:`hikari.client.Client` and
    handles registering event listeners attached to the loaded clusters and the listener(s) required for commands.

    Note:
        This inherits from :class:`CommandCluster` and can act as an independent Command Cluster for small bots.
    """

    _clusters: typing.Mapping[str, AbstractCommandCluster]

    def __init__(
        self,
        components: _components.Components,
        *,
        hooks: typing.Optional[CommandHooks] = None,
        modules: typing.Sequence[str] = None,
    ) -> None:
        CommandCluster.__init__(self, client=self, components=components, hooks=hooks)
        self._clusters = {}
        self.load_from_modules(*(modules or more_collections.EMPTY_SEQUENCE))

    async def load(self) -> None:
        if not self.started:
            self.logger.debug("Starting up %s cluster.", self.__class__.__name__)
            await super().load()
        for cluster in self._clusters.values():
            if cluster.started:
                continue
            self.logger.debug("Starting up %s cluster.", cluster.__class__.__name__)
            await cluster.load()

    async def check_prefix(self, message: messages.Message) -> typing.Optional[str]:
        """
        Used to check if a message's content match any currently registered prefix (including any prefixes registered
        for the guild if this is being called from one.

        Args:
            message:
                The :class:`messages.Message` object that we're checking for a prefix in it's content.

        Returns:
            A :class:`str` representation of the triggering prefix if found, else :class:`None`
        """
        trigger_prefix = None
        for prefix in await self._get_prefixes(message.guild_id):
            if message.content.startswith(prefix):
                trigger_prefix = prefix
                break
        return trigger_prefix

    async def deregister_cluster(self, cluster: str) -> AbstractCommandCluster:
        cluster = self._clusters.pop(cluster)  # TODO: support the actual object?
        await cluster.unload()
        return cluster

    async def get_global_command_from_context(self, ctx: Context) -> typing.AsyncIterator[AbstractCommand]:
        for cluster in (self, *self._clusters.values()):
            async for command_obj in cluster.get_command_from_context(ctx):
                yield command_obj

    def get_global_command_from_name(self, content: str) -> typing.Iterator[typing.Tuple[AbstractCommand, str]]:
        yield from self.get_command_from_name(content)
        for cluster in (self, *self._clusters.values()):
            yield from cluster.get_command_from_name(content)

    async def _get_prefixes(self, guild: typing.Optional[bases.Snowflake]) -> typing.Sequence[str]:
        """
        Used to get the registered global prefixes and a guild's prefix from the function `get_guild_prefix` if this is
        being called from a guild and `get_guild_prefix` has been implemented on this object.

        Args:
            guild:
                The object or ID of the guild to check or :class:`None`.

        Returns:
            An :class:`typing.Sequence` of :class:`str` representation of the applicable prefixes.
        """
        if guild is None or not hasattr(self, "get_guild_prefix"):
            return self.components.config.prefixes  # TODO: this

        guild_prefix = self.get_guild_prefix(guild)  # TODO: implement
        if asyncio.iscoroutine(guild_prefix):
            guild_prefix = await guild_prefix

        return [guild_prefix, *self.components.config.prefixes] if guild_prefix else self.components.config.prefixes

    def load_from_modules(self, *modules: str) -> None:
        for module_path in modules:
            module = importlib.import_module(module_path)
            module.setup(self)

    @event(message_events.MessageCreateEvent)
    async def on_message_create(self, message: message_events.MessageCreateEvent) -> None:
        """Handles command triggering based on message creation."""
        prefix = await self.check_prefix(message)
        mention = None  # TODO: mention at end of message?
        if prefix or mention:
            command_args = message.content[len(prefix or mention) :]
        else:
            return

        ctx = Context(
            components=self.components,
            content=command_args,
            message=message,
            trigger=prefix or mention,
            trigger_type=TriggerTypes.PREFIX if prefix else TriggerTypes.MENTION,
        )
        for cluster in (self, *self._clusters.values()):
            if await cluster.execute(ctx):
                break

    @event(other_events.ReadyEvent)
    async def on_ready(self, _: other_events.ReadyEvent) -> None:
        if not self.started:
            await self.load()

    async def register_cluster(
        self, cluster: typing.Union[AbstractCommandCluster, typing.Type[AbstractCommandCluster]]
    ) -> None:
        if inspect.isclass(cluster):
            cluster = cluster(self, self.components)
        #  TODO: bind client?
        await cluster.load()
        self._clusters[cluster.__class__.__name__] = cluster


class ReinhardCommandClient(CommandClient):
    """A custom command client with some reinhard modifications."""

    def _consume_client_loadable(self, loadable: typing.Any) -> bool:
        if inspect.isclass(loadable) and issubclass(loadable, AbstractCommandCluster):
            cluster = loadable(self, self.components)
            self._clusters[cluster.__class__.__name__] = cluster
        elif isinstance(loadable, AbstractCommand):  # TODO: or executable?
            self.register_command(loadable)
        elif callable(loadable):
            loadable(self)
        else:
            return False
        return True

    def load_from_modules(self, *modules: str) -> None:
        for module_path in modules:
            module = importlib.import_module(module_path)
            exports = getattr(module, "exports", more_collections.EMPTY_SEQUENCE)
            for item in exports:
                try:
                    item = getattr(module, item)
                except AttributeError as exc:
                    raise RuntimeError(f"`{item}` export not found in `{module_path}` module.") from exc

                if not self._consume_client_loadable(item):
                    self.logger.warning(
                        "Invalid export `%s` found in `%s.exports`", item.__class__.__name__, module_path
                    )

            if not exports:
                self.logger.warning("No exports found in %s", module_path)
