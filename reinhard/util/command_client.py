from __future__ import annotations

__all__ = [
    "command",
    "Command",
    "CommandClient",
    "CommandClientOptions",
    "CommandError",
    "CommandCluster",
]

import abc
import asyncio
import contextlib
import enum
import importlib
import inspect
import logging
import traceback
import types
import typing


from hikari.clients import configs
from hikari.events import base as base_events
from hikari.events import message as message_events
from hikari.internal import assertions
from hikari.internal import marshaller
from hikari.internal import more_collections
from hikari import bases
from hikari import errors
from hikari import permissions
import attr


from reinhard.util import arg_parser

if typing.TYPE_CHECKING:
    from hikari.clients import components as _components
    from hikari.internal import more_typing
    from hikari.state import dispatchers as _dispatchers
    from hikari import messages

    CheckLikeT = typing.Callable[["Context"], typing.Union[bool, typing.Coroutine[typing.Any, typing.Any, bool]]]
    CommandFunctionT = typing.Callable[[...], more_typing.Coroutine[None]]

SEND_MESSAGE_PERMISSIONS = permissions.Permission.VIEW_CHANNEL | permissions.Permission.SEND_MESSAGES
ATTACH_FILE_PERMISSIONS = SEND_MESSAGE_PERMISSIONS | permissions.Permission.ATTACH_FILES

# TODO: use command hooks instead of specific stuff like get_guild_prefixes?
# Todo event dispatching?


class CommandEvents(enum.Enum):
    ERROR = "error"
    LOAD = "load"
    UNLOAD = "unload"

    def __str__(self) -> str:
        return self.value


class TriggerTypes(enum.Enum):
    PREFIX = enum.auto()
    MENTION = enum.auto()  # TODO: trigger commands with a mention


class HikariPermissionError(errors.HikariError):  # TODO: better name
    __slots__ = ("missing_permissions",)

    missing_permissions: permissions.Permission

    def __init__(
        self, required_permissions: permissions.Permission, actual_permissions: permissions.Permission
    ) -> None:
        pass
        # self.missing_permissions =
        # for permission in m


@attr.attrs(init=True, slots=True)
class Context:
    content: str = attr.attrib()

    components: _components.Components = attr.attrib()

    #: The message that triggered this command.
    #:
    #: :type: :class:`hikari.orm.models.messages.Message`
    message: messages.Message = attr.attrib()

    #: The string prefix or mention that triggered this command.
    #:
    #: :type: :class:`str`
    trigger: str = attr.attrib()

    #: The mention or prefix that triggered this event.
    #:
    #: :type: :class:`TriggerTypes`
    trigger_type: TriggerTypes = attr.attrib()

    #: The command alias that triggered this command.
    #:
    #: :type: :class:`str`
    triggering_name: str = attr.attrib(default=None)

    command: AbstractCommand = attr.attrib(default=None)

    def prune_content(self, length: int) -> None:
        self.content = self.content[length:]

    def set_command_trigger(self, trigger: str) -> None:
        self.triggering_name = trigger

    def set_command(self, command_obj: AbstractCommand) -> None:
        self.command = command_obj

    @property
    def cluster(self) -> AbstractCommandCluster:
        return self.command.cluster


HookLikeT = typing.Callable[[Context], typing.Coroutine[typing.Any, typing.Any, None]]


@attr.attrs(init=True, slots=True)
class CommandHooks:  # TODO: this
    pre_execution: typing.Callable[[Context, ...], typing.Coroutine[typing.Any, typing.Any, bool]] = attr.attrib(
        default=None
    )
    post_execution: HookLikeT = attr.attrib(default=None)
    on_error: typing.Callable[[Context, BaseException], typing.Coroutine[typing.Any, typing.Any, None]] = attr.attrib(
        default=None
    )
    on_success: HookLikeT = attr.attrib(default=None)
    on_ratelimit: HookLikeT = attr.attrib(default=None)  # TODO: implement?

    def set_pre_execution(
        self, hook: typing.Callable[[Context, ...], typing.Coroutine[typing.Any, typing.Any, bool]]
    ) -> typing.Callable[[Context, ...], typing.Coroutine[typing.Any, typing.Any, bool]]:
        assertions.assert_none(self.pre_execution, "Pre-execution hook already set.")
        self.pre_execution = hook
        return hook

    def set_post_execution(self, hook: HookLikeT) -> HookLikeT:  # TODO: better typing
        assertions.assert_none(self.post_execution, "Post-execution hook already set.")
        self.post_execution = hook
        return hook

    def set_on_error(
        self, hook: typing.Callable[[Context, BaseException], typing.Coroutine[typing.Any, typing.Any, None]]
    ) -> typing.Callable[[Context, BaseException], typing.Coroutine[typing.Any, typing.Any, None]]:
        assertions.assert_none(self.on_error, "On error hook already set.")
        self.on_error = hook
        return hook

    def set_on_success(self, hook: HookLikeT) -> HookLikeT:
        assertions.assert_none(self.on_success, "On success hook already set.")
        self.on_success = hook
        return hook


@marshaller.marshallable()
@attr.s(slots=True, kw_only=True)
class CommandClientOptions(configs.BotConfig):
    access_levels: typing.MutableMapping[bases.Snowflake, int] = marshaller.attrib(
        deserializer=lambda levels: {bases.Snowflake(sn): int(level) for sn, level in levels.items()}
    )
    prefixes: typing.List[str] = marshaller.attrib(deserializer=lambda prefixes: [str(prefix) for prefix in prefixes])
    # TODO: handle modules (plus maybe other stuff) here?


@attr.attrs(init=True, slots=True)
class CommandError(errors.HikariError):
    #: The string response that the client should send in chat if it has send messages permission.
    #:
    #: :type: :class:`str`
    response: str = attr.attrib()

    def __str__(self) -> str:
        return self.response


class CheckFail(Exception):
    ...  # TODO: this?


class Executable(abc.ABC):
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

    @abc.abstractmethod
    async def execute(self, ctx: Context) -> None:
        """
        Used to execute an entity based on a :class:`Context` object.

        Args:
            ctx:
                The :class:`Context` object to execute this with.
        """


@attr.attrs(init=True, slots=True)
class AbstractCommand(Executable, abc.ABC):

    _func: CommandFunctionT = attr.attrib()

    #: The triggers used to activate this command in chat along with a prefix.
    #:
    #: :type: :class:`typing.Tuple` of :class:`int`
    triggers: typing.Tuple[str] = attr.attrib()

    _cluster: typing.Optional[AbstractCommandCluster] = attr.attrib(default=None)

    meta: typing.Optional[typing.MutableMapping[typing.Any, typing.Any]] = attr.attrib(factory=dict)

    hooks: CommandHooks = attr.attrib(factory=CommandHooks)

    #: The user access level that'll be required to execute this command, defaults to 0.
    #:
    #: :type: :class:`int`
    level: int = attr.attrib(default=0)

    def bind_cluster(self, cluster: AbstractCommandCluster) -> None:
        # This ensures that the cluster will always be passed-through as `self`.
        self._func = types.MethodType(self._func, cluster)
        # This allows for calling the raw function as an attribute of the cluster.
        setattr(cluster, self._func.__name__, self._func)
        self._cluster = cluster

    @abc.abstractmethod
    def check_prefix(self, content: str) -> str:
        ...

    @abc.abstractmethod
    def check_prefix_from_context(self, ctx: Context) -> bool:
        ...

    @abc.abstractmethod
    def deregister_check(self, check: CheckLikeT) -> None:
        ...

    @abc.abstractmethod
    def register_check(self, check: CheckLikeT) -> None:
        ...

    @property
    def cluster(self) -> typing.Optional[AbstractCommandCluster]:
        return self._cluster

    @property
    def docstring(self) -> str:
        return inspect.getdoc(self._func)

    @property
    def function(self) -> CommandFunctionT:
        return self._func

    @property
    def name(self) -> str:
        """Get the name of this command."""
        return self._func.__name__

    @staticmethod
    def generate_trigger(function: typing.Optional[CommandFunctionT] = None) -> str:
        """Get a trigger for this command based on it's function's name."""
        return function.__name__.replace("_", " ")


@attr.attrs(init=True, slots=True)
class FailedCheck(StopIteration):
    checks: typing.Sequence[typing.Tuple[CheckLikeT, typing.Optional[BaseException]]]


class Command(AbstractCommand):
    __slots__ = ("_checks", "_cluster", "_func", "parser")

    _checks: typing.List[CheckLikeT]

    logger: logging.Logger

    parser: arg_parser.AbstractCommandParser

    def __init__(
        self,
        func: typing.Optional[CommandFunctionT] = None,
        trigger: typing.Optional[str] = None,
        *,
        aliases: typing.Optional[typing.List[str]] = None,
        hooks: typing.Optional[CommandHooks] = None,
        level: int = 0,
        meta: typing.Optional[typing.MutableMapping[typing.Any, typing.Any]] = None,
        cluster: typing.Optional[AbstractCommandCluster] = None,
        greedy: bool = False,
    ) -> None:
        super().__init__(
            func=func,
            hooks=hooks or CommandHooks(),
            level=level,
            meta=meta or {},
            triggers=tuple(
                trig
                for trig in (trigger or self.generate_trigger(func), *(aliases or more_collections.EMPTY_COLLECTION))
                if trig is not None
            ),
        )
        self.logger = logging.getLogger(type(self).__qualname__)
        self._checks = [self.check_prefix_from_context]
        self.parser = arg_parser.CommandParser(self._func, greedy=greedy)
        if cluster:
            self.bind_cluster(cluster)

    def __repr__(self) -> str:
        return f"Command({'|'.join(self.triggers)})"

    def bind_cluster(self, cluster: AbstractCommandCluster) -> None:
        super().bind_cluster(cluster)
        # Now that we know self will automatically be passed, we need to trim the parameters again.
        self.parser.trim_parameters(1)

    def deregister_check(self, check: CheckLikeT) -> None:
        try:
            self._checks.remove(check)
        except ValueError:
            raise ValueError("Command Check not found.")

    def register_check(self, check: CheckLikeT) -> None:
        self._checks.append(check)

    async def check(self, ctx: Context) -> None:
        failed: typing.Sequence[typing.Tuple[CheckLikeT, typing.Optional[Exception]]] = []
        ctx.set_command(self)  # TODO: is this the best way to do this?
        result = True
        for check in self._checks:
            try:
                result = check(ctx)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as exc:
                failed.append(check, exc)
            else:
                if not result:
                    failed.append(check, None)

        if failed:
            raise FailedCheck(failed)

    def check_prefix(self, content: str) -> str:
        for trigger in self.triggers:
            if content.startswith(trigger):
                return trigger

    def check_prefix_from_context(self, ctx: Context) -> bool:
        for trigger in self.triggers:
            if ctx.content.startswith(trigger):
                ctx.set_command_trigger(trigger)
                return True
        return False

    async def execute(self, ctx: Context) -> None:
        try:
            args, kwargs = await self.parser.parse(ctx)
            if self._trigger_pre_execution_hook(ctx, *args, **kwargs) is False:
                return
            await self._func(ctx, *args, **kwargs)
        except CommandError as exc:
            with contextlib.suppress(errors.HTTPError):  # TODO: better permission handling?
                response = str(exc)
                await ctx.message.reply(content=response if len(response) <= 2000 else response[:1997] + "...")
        except Exception as exc:
            await self._trigger_error_hook(ctx, exc)
            raise exc
        else:
            await self._trigger_on_success_hook(ctx)
        finally:
            await self._execute_post_execution_hook(ctx)

    async def _trigger_pre_execution_hook(self, ctx: Context, *args, **kwargs) -> bool:
        result = True
        if self.hooks.pre_execution:
            result = await self.hooks.pre_execution(ctx, *args, **kwargs)

        if self._cluster and self._cluster.hooks.pre_execution:  # TODO: does this matter?
            result = result and self._cluster.hooks.pre_execution(ctx, *args, **kwargs)  # TODO: for consistency?
        return result

    async def _trigger_error_hook(self, ctx: Context, exception: BaseException) -> None:
        if self.hooks.on_error:
            await self.hooks.on_error(ctx, exception)

        if self._cluster and self._cluster.hooks.on_error:
            await self._cluster.hooks.on_error(ctx, exception)

    async def _trigger_on_success_hook(self, ctx: Context) -> None:
        if self.hooks.on_success:
            await self.hooks.on_success(ctx)

        if self._cluster and self._cluster.hooks.on_success:
            await self._cluster.hooks.on_success(ctx)

    async def _execute_post_execution_hook(self, ctx: Context) -> None:
        if self.hooks.post_execution:
            await self.hooks.post_execution(ctx)

        if self._cluster and self._cluster.hooks.post_execution:
            await self._cluster.hooks.post_execution(ctx)


def command(
    __arg=..., cls: typing.Type[AbstractCommand] = Command, group: typing.Optional[str] = None, **kwargs
):  # TODO: handle groups...
    def decorator(coro_fn):
        return cls(coro_fn, **kwargs)

    return decorator if __arg is ... else decorator(__arg)


def event(event_: base_events.HikariEvent):
    def decorator(coro_fn):
        coro_fn.__event__ = event_
        return coro_fn

    return decorator


class CommandGroup(Executable):
    ...


class AbstractCommandCluster:  # TODO: Executable  TODO: proper type annotations
    def __init__(self, components: _components.Components, *, hooks: CommandHooks):
        self._components = components
        self.hooks = hooks or CommandHooks()

    @abc.abstractmethod
    async def get_command_from_context(self, ctx: Context) -> typing.AsyncIterator[AbstractCommand]:
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
    @typing.overload
    def register_command(self, func: AbstractCommand, bind: bool = False,) -> None:
        ...

    @abc.abstractmethod
    @typing.overload
    def register_command(
        self, func: CommandFunctionT, *aliases: str, trigger: typing.Optional[str] = None, bind: bool = False,
    ) -> None:
        ...

    @abc.abstractmethod
    def register_command(self, func, *aliases, trigger=None, bind=False) -> None:
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
    def unregister_command(self, command_obj: AbstractCommand) -> None:
        """
        Unregister a command in this cluster.

        Args:
            command_obj:
                The command object to remove.

        Raises:
            ValueError:
                If the passed command object wasn't found.
        """

    @abc.abstractmethod
    async def load(self) -> None:
        ...

    @abc.abstractmethod
    async def unload(self) -> None:
        ...


class CommandCluster(AbstractCommandCluster):
    __slots__ = ("_components", "logger", "commands", "hooks")

    #: The class wide logger.
    #:
    #: :type: :class:`logging.Logger`
    logger: logging.Logger

    #: A list of the commands that are loaded in this cluster.
    #:
    #: :type: :class:`typing.Sequence` of :class:`AbstractCommand`
    commands: typing.List[AbstractCommand]

    def __init__(self, components: _components.Components, *, hooks: typing.Optional[CommandHooks] = None) -> None:
        AbstractCommandCluster.__init__(self, components, hooks=hooks)
        self.logger = logging.getLogger(type(self).__qualname__)
        self.commands = []
        self.bind_commands()
        self.bind_listeners()

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
        return self._components.config.access_levels.get(message.author.id, 0) >= command_obj.level  # TODO: sql filter.

    def bind_commands(self) -> None:
        """
        Loads any commands that are attached to this class into `cluster_commands`.

        Raises:
            ValueError:
                if the commands for this cluster have already been binded or if any duplicate triggers are found while
                loading commands.
        """
        assertions.assert_that(  # TODO: overwrite commands?
            not self.commands,
            f"Cannot bind commands in cluster '{self.__class__.__name__}' when commands have already been binded.",
        )
        for name, command_obj in inspect.getmembers(self, predicate=lambda attr: isinstance(attr, AbstractCommand)):
            self.register_command(command_obj, bind=True)
            self.logger.debug(
                "Binded command %s in %s cluster.", command_obj.name, self.__class__.__name__,
            )
        self.commands.sort(key=lambda comm: comm.name, reverse=True)

    def bind_listeners(self) -> None:  # TODO: bind listeners from a specific cluster?
        """Used to add event listeners from all loaded command clusters to hikari's internal event listener."""
        for _, function in self.get_cluster_event_listeners():
            self.logger.debug(f"Registering {function.__event__} event listener for command client.")
            self._components.event_dispatcher.add_listener(function.__event__, function)

    async def get_command_from_context(self, ctx: Context) -> typing.AsyncIterator[AbstractCommand]:
        for command_obj in self.commands:
            try:
                await command_obj.check(ctx)
            except FailedCheck:
                continue
            else:
                if await self.access_check(command_obj, ctx.message):
                    yield command_obj

    def get_command_from_name(self, content: str) -> typing.Iterator[typing.Tuple[AbstractCommand, str]]:
        for command_obj in self.commands:
            if prefix := command_obj.check_prefix(content):
                yield command_obj, prefix

    def get_cluster_event_listeners(self) -> typing.Sequence[typing.Tuple[str, _dispatchers.EventCallbackT]]:
        """Get a generator of the event listeners attached to this cluster."""
        return inspect.getmembers(self, predicate=lambda obj: hasattr(obj, "__event__"))

    def register_command(
        self,
        func: typing.Union[CommandFunctionT, AbstractCommand],
        *aliases: str,
        trigger: typing.Optional[str] = None,
        bind: bool = False,
    ) -> None:
        if isinstance(func, AbstractCommand):
            command_obj = func
            if bind:
                command_obj.bind_cluster(self)
        else:
            command_obj = Command(func=func, cluster=self if bind else None, trigger=trigger, aliases=list(aliases))
        for trigger in command_obj.triggers:
            if list(self.get_command_from_name(trigger)):
                self.logger.warning(
                    "Possible overlapping trigger '%s' found in %s cluster.", trigger, self.__class__.__name__,
                )
        self.commands.append(command_obj)

    def unregister_command(self, command_obj: AbstractCommand) -> None:
        try:
            self.commands.remove(command_obj)
        except ValueError:
            raise ValueError("Invalid command passed for this cluster.") from None

    async def load(self) -> None:
        ...

    async def unload(self) -> None:
        ...


class AbstractCommandClient(AbstractCommandCluster, Executable, abc.ABC):
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


class CommandClient(AbstractCommandClient, CommandCluster):
    """
    The central client that all command clusters will be binded to. This extends :class:`hikari.client.Client` and
    handles registering event listeners attached to the loaded clusters and the listener(s) required for commands.

    Note:
        This inherits from :class:`CommandCluster` and can act as an independent Command Cluster for small bots.
    """

    # __slots__ = ("clusters",)

    _clusters: typing.Mapping[str, AbstractCommandCluster]

    def __init__(
        self,
        components: _components.Components,
        *,
        hooks: typing.Optional[CommandHooks] = None,
        modules: typing.List[str] = None,
    ) -> None:
        CommandCluster.__init__(self, components, hooks=hooks)
        self._clusters = {}
        self._started = False
        self.load_from_modules(*(modules or more_collections.EMPTY_SEQUENCE))

    async def load(self) -> None:
        await super().load()
        self.logger.debug("Starting up %s loaded clusters.", len(self._clusters) + 1)
        for cluster in self._clusters.values():
            self.logger.debug("Starting up %s cluster.", cluster.__class__.__name__)
            await cluster.load()
        self._started = True

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

    async def get_global_command_from_context(self, ctx: Context) -> typing.AsyncIterator[AbstractCommand]:
        for cluster in (self, *self._clusters.values()):
            async for command_obj in cluster.get_command_from_context(ctx):
                yield command_obj

    def get_global_command_from_name(self, content: str) -> typing.Iterator[typing.Tuple[AbstractCommand, str]]:
        yield from self.get_command_from_name(content)
        for cluster in (self, *self._clusters.values()):
            yield from cluster.get_command_from_name(content)

    async def _get_prefixes(self, guild: typing.Optional[bases.Snowflake]) -> typing.List[str]:
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
            return self._components.config.prefixes  # TODO: this

        guild_prefix = self.get_guild_prefix(guild)
        if asyncio.iscoroutine(guild_prefix):
            guild_prefix = await guild_prefix

        return [guild_prefix, *self._components.config.prefixes] if guild_prefix else self._components.config.prefixes

    def load_from_modules(self, *modules: str) -> None:
        for module_path in modules:
            module = importlib.import_module(module_path)
            module.setup(self)

    @event(message_events.MessageCreateEvent)
    async def on_message_create(self, message: messages.Message) -> None:
        """Handles command triggering based on message creation."""
        if not self._started:
            await self.load()

        prefix = await self.check_prefix(message)
        mention = None  # TODO: mention at end of message?
        if prefix or mention:
            command_args = message.content[len(prefix or mention) :]
        else:
            return

        ctx = Context(  # TODO: stateless vs stateful
            components=self._components,
            content=command_args,
            message=message,
            trigger=prefix or mention,
            trigger_type=TriggerTypes.PREFIX if prefix else TriggerTypes.MENTION,
        )
        async for command_obj in self.get_global_command_from_context(ctx):
            break
        else:
            command_obj = None

        if command_obj is None:
            return

        ctx.prune_content(len(ctx.triggering_name) + 1)  # TODO: no spaces?
        await command_obj.execute(ctx)

    async def register_cluster(
        self, cluster: typing.Union[AbstractCommandCluster, typing.Type[AbstractCommandCluster]]
    ) -> None:
        if inspect.isclass(cluster):
            cluster = cluster(self._components)
        else:
            cluster.bind_client(self)  # TODO
        await cluster.load()
        self._clusters[cluster.__class__.__name__] = cluster

    async def deregister_cluster(self, cluster: str) -> AbstractCommandCluster:
        cluster = self._clusters.pop(cluster)  # TODO: support the actual object?
        await cluster.unload()
        return cluster


class ReinhardCommandClient(CommandClient):
    """A custom command client with some reinhard modifications."""

    def _consume_client_loadable(self, loadable: typing.Any) -> bool:
        if inspect.isclass(loadable) and issubclass(loadable, AbstractCommandCluster):
            cluster = loadable(self._components)
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
