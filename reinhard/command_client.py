from __future__ import annotations
import abc
import asyncio
import contextlib
import dataclasses
import enum
import importlib
import inspect
import logging
import typing


from hikari.internal_utilities import assertions
from hikari.internal_utilities import containers
from hikari.internal_utilities import loggers
from hikari.internal_utilities import unspecified
from hikari.orm.models import bases
from hikari.orm.models import media
from hikari.orm.models import permissions
from hikari.orm import client
from hikari import errors

if typing.TYPE_CHECKING:
    from hikari.internal_utilities import aio
    from hikari.internal_utilities import type_hints
    from hikari.orm.http import base_http_adapter
    from hikari.orm.models import embeds
    from hikari.orm.models import guilds
    from hikari.orm.models import messages
    from hikari.orm.state import base_registry
    from hikari.orm import fabric

SEND_MESSAGE_PERMISSIONS = permissions.VIEW_CHANNEL | permissions.SEND_MESSAGES
ATTACH_FILE_PERMISSIONS = SEND_MESSAGE_PERMISSIONS | permissions.ATTACH_FILES
CHARACTERS_TO_SANITIZE = {"@": ""}


def sanitize_content(content: str) -> str:
    return content  # TODO: This.


class Executable(abc.ABC):
    @abc.abstractmethod
    async def execute(self, message: messages.Message, content: str) -> bool:
        ...


class TriggerTypes(enum.Enum):
    PREFIX = enum.auto()
    MENTION = enum.auto()  # TODO: trigger commands with a mention


class PermissionError(errors.HikariError):
    __slots__ = ("missing_permissions",)

    missing_permissions: permissions.Permission

    def __init__(self, required_permissions: permissions.Permission, actual_permissions: permissions.Permission):
        pass
        # self.missing_permissions =
        # for permission in m


class Context:
    __slots__ = ("fabric", "command", "message", "module")

    fabric: fabric.Fabric

    #: The message that triggered this command.
    #:
    #: :type: :class: `hikari.orm.models.messages.Message`
    message: messages.Message

    #: The module this command was triggered by.
    #:
    #: :type: :class:`CommandModule`
    module: CommandModule

    #: The string prefix or mention that triggered this command.
    #:
    #: :type: :class:`str`
    trigger: str

    #: The type of trigger that triggered this command.
    #:
    #: :type: :class:`TriggerTypes`
    trigger_type: TriggerTypes

    def __init__(
        self,
        fabric_obj: fabric.Fabric,
        message: messages.Message,
        module: CommandModule,
        trigger: str,
        trigger_type: TriggerTypes,
    ):
        self.fabric = fabric_obj
        self.message = message
        self.module = module

    @property
    def http(self) -> base_http_adapter.BaseHTTPAdapter:
        return self.fabric.http_adapter

    @property
    def state(self) -> base_registry.BaseRegistry:
        return self.fabric.state_registry

    async def reply(
        self,
        *,
        content: type_hints.NotRequired[str] = unspecified.UNSPECIFIED,
        tts: bool = False,
        files: type_hints.NotRequired[typing.Collection[media.AbstractFile]] = unspecified.UNSPECIFIED,
        embed: type_hints.NotRequired[embeds.Embed] = unspecified.UNSPECIFIED,
        soft_send: bool = False,  # TODO: what was this?
        sanitize: bool = True,
    ) -> messages.Message:
        """Used to handle response length and permission checks for command responses."""
        # TODO: automatically sanitise somewhere?
        if content is not unspecified.UNSPECIFIED and len(content) > 2000:
            files = files or containers.EMPTY_SEQUENCE
            files.append(media.InMemoryFile("message.txt", bytes(content, "utf-8")))
            content = "This response is too large to send, see attached file."
        elif content is not unspecified.UNSPECIFIED:
            content = sanitize_content(content)

        # TODO: this needs to be easier to do on hikari's level.
        # if not files and not SEND_MESSAGE_PERMISSIONS or files and ATTACH_FILE_PERMISSIONS:
        #     raise PermissionError(ATTACH_FILE_PERMISSIONS if files else SEND_MESSAGE_PERMISSIONS)

        return await self.fabric.http_adapter.create_message(
            self.message.channel, content=content, tts=tts, embed=embed, files=files
        )


@dataclasses.dataclass()
class CommandClientOptions(client.client_options.ClientOptions, bases.MarshalMixin):
    access_levels: typing.MutableMapping[int, int] = dataclasses.field(default_factory=dict)
    # TODO: handle modules (plus maybe other stuff) here?


class CommandError(Exception):
    __slots__ = ("response",)

    #: The string response that the client should send in chat if it has send messages permission.
    #:
    #: :type: :class:`str`
    response: str

    def __init__(self, response: str):
        self.response = response

    def __str__(self):
        return self.response


class Command:
    __slots__ = ("_func", "_module", "level", "triggers")

    _func: aio.CoroutineFunctionT

    _module: typing.Optional[CommandModule]

    #: The user access level that'll be required to execute this command, defaults to 0.
    #:
    #: :type: :class:`int`
    level: int

    #: The triggers used to activate this command in chat along with a prefix.
    #:
    #: :type: :class:`typing.Tuple` of :class:`int`
    triggers: typing.Tuple[str]

    def __init__(
        self,
        func: typing.Optional[aio.CoroutineFunctionT] = None,
        trigger: typing.Optional[str] = None,
        *,
        aliases: typing.Optional[typing.List[str]] = None,
        level: int = 0,
        module: typing.Optional[CommandModule] = None,
    ) -> None:
        self._func = func
        self.level = level
        self._module = module
        if not trigger:
            trigger = self.generate_trigger()
        self.triggers = tuple(trig for trig in (trigger, *(aliases or containers.EMPTY_COLLECTION)) if trig is not None)

    def __repr__(self):
        return f"Command({'|'.join(self.triggers)})"

    def bind_module(self, module: CommandModule) -> None:  # TODO: depricate
        self._module = module

    async def execute(self, message: messages.Message, args: str) -> typing.Optional[str]:
        """
        Used to execute a command, catches any :class:`CommandErrors` and calls the module's error handler on error.

        Args:
            message:
                The :class:`hikari.orm.models.messages.Message` object to execute this command using.
            args:
                The string args that followed the triggering prefix and command alias to be parsed.

        Returns:
            An optional :class:`str` response to be sent in chat.
        """
        try:
            return await self._func(self._module, message, self.parse_args(args))
        except CommandError as e:
            # '@contextlib.suppress(PermissionError):
            # reply
            return str(e)
        except Exception as e:
            await self._module.handle_error(e, message)  # TODO: move
            raise e

    def generate_trigger(self) -> str:
        """Get a trigger for this command based on it's function's name."""
        return self.name.replace("_", " ")

    @property
    def name(self):
        """Get the name of this command."""
        return self._func.__name__

    def parse_args(self, args: str) -> typing.List[typing.Union[int, str]]:
        return args  # TODO: actually parse


def command(__arg=..., cls=Command, **kwargs):
    def decorator(coro_fn):
        return cls(coro_fn, **kwargs)

    return decorator if __arg is ... else decorator(__arg)


class CommandModule:
    __slots__ = ("command_client", "error_handler", "logger", "module_commands")

    #: The command client this module is loaded in.
    #:
    #: :type: :class:`CommandClient` or :class:`None`
    command_client: typing.Optional[CommandClient]

    error_handler: typing.Optional[aio.CoroutineFunctionT]

    #: The class wide logger.
    #:
    #: :type: :class:`logging.Logger`
    logger: logging.Logger

    #: A list of the commands that are loaded in this module.
    #:
    #: :type: :class:`typing.Sequence` of :class:`Command`
    module_commands: typing.List[Command]

    def __init__(self, command_client: CommandClient) -> None:
        super().__init__()  # TODO: ?
        self.logger = loggers.get_named_logger(self)
        self.bind_commands()
        self.command_client = command_client

    def bind_commands(self) -> None:
        """
        Loads any commands that are attached to this class into `module_commands`.

        Raises:
            ValueError:
                if the commands for this module have already been binded or if any duplicate triggers are found while
                loading commands.
        """
        assertions.assert_that(
            not getattr(self, "module_commands", None),
            f"Cannot bind commands in module '{self.__class__.__name__}' when commands have already been binded.",
        )
        self.module_commands = []
        for name, function in inspect.getmembers(self, predicate=lambda func: isinstance(func, Command)):
            function.bind_module(self)
            for trigger in function.triggers:
                if self.get_command(trigger)[0] is not None:
                    self.logger.warning(
                        f"Possible overlapping trigger '{trigger}' found in '{self.__class__.__name__}' module."
                    )
            self.module_commands.append(function)
        self.module_commands.sort(key=lambda comm: comm.name, reverse=True)

    def get_command(self, content: str) -> typing.Union[typing.Tuple[Command, str], typing.Tuple[None, None]]:
        """
        Get a command based on a message's content (minus prefix) from the loaded commands if any command triggers are
        found in the content.

        Args:
            content:
                The string content to try and find a command for (minus the triggering prefix).

        Returns:
            A :class:`typing.Tuple` of :class:`Command` object and the :class:`str` trigger that was matched if the
            command was found else a :class:`typing.Tuple` of :class:`None` and :class:`None`.
        """
        for command_obj in self.module_commands:
            for trigger in command_obj.triggers:
                if content.startswith(trigger):
                    return command_obj, trigger
        return None, None

    async def handle_error(self, error: BaseException, message: messages.Message) -> bool:
        error_handler = getattr(self, "error_handler", None)
        if error_handler is not None:
            await error_handler(error, message)
            return True
        return False

    def get_module_event_listeners(self) -> typing.Generator[typing.Tuple[str, aio.CoroutineFunctionT]]:
        """Get a generator of the event listeners attached to this module."""
        return (
            (name[3:], function)
            for name, function in inspect.getmembers(self, predicate=asyncio.iscoroutinefunction)
            if name.startswith("on_")
        )

    def register_command(self, func: aio.CoroutineFunctionT, trigger: str = None, *aliases: str) -> None:
        """
        Register a command in this module.

        Args:
            func:
                The Coroutine Function to be called when executing this command.
            trigger:
                The string that will be this command's main trigger.
            *aliases:
                More string triggers for this command.

        Raises:
            ValueError:
                If any of the triggers for this command are found on a loaded command.
        """
        command_obj = Command(func=func, module=self, trigger=trigger, aliases=list(aliases))
        for trigger in command_obj.triggers:
            if self.get_command(trigger) is not None:
                self.logger.warning(
                    f"Possible overlapping trigger '{trigger}' found in '{self.__class__.__name__}' module."
                )
        self.module_commands.append(command_obj)

    def unregister_command(self, command_obj: typing.Union[Command, str]):
        if isinstance(command_obj, str):
            command_obj = self.get_command(command_obj)
        elif not isinstance(command_obj, Command):
            raise ValueError("Command must be string command trigger or a 'Command' object.")

        try:
            self.module_commands.remove(command_obj)
        except ValueError:
            raise ValueError("Invalid command passed for this module.") from None


class CommandClient(client.Client, CommandModule):
    """
    The central client that all command modules will be binded to. This extends :class:`hikari.client.Client` and
    handles registering event listeners attached to the loaded modules and the listener(s) required for commands.

    Note:
        This inherits from :class:`CommandModule` and can act as an independent Command Module for small bots.
    """

    __slots__ = ("get_guild_prefix", "modules", "prefixes")

    get_guild_prefix: typing.Union[aio.CoroutineFunctionT, None]  # TODO: or normal method.
    # TODO: rename this to something singular

    #: The command modules that are loaded in this client.
    #:
    #: :type: :class:`typing.MutableMapping` of :class:`str` to :class:`CommandModule`
    modules: typing.MutableMapping[str, CommandModule]

    #: An array of this bot's global prefixes.
    #:
    #: :type: :class:`typing.List` of :class:`str`
    prefixes: typing.List[str]

    def __init__(
        self,
        prefixes: typing.List[str],
        *,
        modules: typing.List[str] = None,
        options: typing.Optional[CommandClientOptions] = None,
    ) -> None:
        super().__init__(options=options or CommandClientOptions())
        self.modules = {}
        self.load_modules(*(modules or containers.EMPTY_SEQUENCE))
        self.bind_commands()
        self.bind_listeners()
        self.prefixes = prefixes
        # TODO: built in help command.

    async def access_check(self, command_obj: Command, message: messages.Message) -> bool:
        """
        Used to check if a command can be accessed by the calling user and in the calling channel/guild.

        Args:
            command_obj:
                The :class:`Command` object to check access levels for.
            message:
                The :class:`messages.Message` object to check access levels for.

        Returns:
            A :class:`bool` representation of whether this command can be accessed.
        """
        return self._client_options.access_levels.get(message.author.id, 0) >= command_obj.level  # TODO: sql filter.

    def bind_listeners(self) -> None:
        """Used to add event listeners from all loaded command modules to hikari's internal event listener."""
        for module in (self, *self.modules.values()):
            for name, function in module.get_module_event_listeners():
                self.logger.warning(name)
                self.add_event(name, function)

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
        # message.channel shouldn't ever be unresolved.
        for prefix in await self._get_prefixes(
            (message.channel if message.channel.is_resolved else await message.channel).guild_id
        ):
            if message.content.startswith(prefix):
                trigger_prefix = prefix
                break
        return trigger_prefix

    def get_global_command(self, content: str) -> typing.Union[typing.Tuple[Command, str], typing.Tuple[None, None]]:
        """
        Used to get a command from on a messages's content (checks all loaded modules).

        Args:
            content:
                The :class:`str` content of the message (minus the prefix) to get a command from.

        Returns:
            A :class:`typing.Tuple` of the :class:`Command` object and the :class:`str` trigger that was matched if
            the command was found found, else a :class:`typing.Tuple` of :class:`None` and :class:`None`.
        """
        for module in (self, *self.modules.values()):
            command_obj, trigger = module.get_command(content)
            if command_obj:
                return command_obj, trigger
        return None, None

    async def _get_prefixes(self, guild: typing.Optional[guilds.GuildLikeT]) -> typing.List[str]:
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
            return self.prefixes

        if asyncio.iscoroutinefunction(self.get_guild_prefix):
            guild_prefix = await self.get_guild_prefix(int(guild))  # TODO: maybe don't
        else:
            guild_prefix = self.get_guild_prefix(int(guild))

        return [guild_prefix, *self.prefixes] if guild_prefix else self.prefixes

    def load_modules(self, *modules: str) -> None:
        """
        Used to load modules based on string paths.

        Args:
            *modules:
                The :class:`str` paths of modules to load (in the format of `root.dir.module`)
        """
        for module_path in modules:
            found = False
            module = importlib.import_module(module_path)
            for attr in dir(module):
                value = getattr(module, attr)
                if inspect.isclass(value) and issubclass(value, CommandModule) and value is not CommandModule:
                    self.modules[value.__class__.__name__] = value(self)
                    found = True
            if not found:
                raise ValueError(f"No valid 'CommandModule' derived class found in '{module_path}'.")

    async def on_message_create(self, message: messages.Message) -> None:
        """Handles command triggering based on message creation."""
        prefix = await self.check_prefix(message)  # TODO: maybe one day we won't have to await this.
        if not prefix:
            return

        command_args = message.content[len(prefix) :]
        command_obj, trigger = self.get_global_command(command_args)
        if not command_obj or not await self.access_check(command_obj, message):
            return

        command_args = command_args[len(trigger) + 1 :]
        # TODO: for now this is also a bit basic...
        result = await command_obj.execute(message, command_args)
        if isinstance(result, str):
            await self.respond(message, result)

    async def respond(self, message: messages.Message, content: str) -> None:  # TODO: depricate and rely on ctx.
        """Used to handle response length and permission checks for command responses."""
        # TODO: send message perm check, currently not easy to do with hikari.
        # TODO: automatically sanitise somewhere?
        files = unspecified.UNSPECIFIED
        if len(content) > 2000:
            files = [
                media.InMemoryFile("message.txt", bytes(content, "utf-8")),
            ]
            content = "This response is too large to send, see attached file."

        await self._fabric.http_adapter.create_message(message.channel, content=content, files=files)


__all__ = [
    "command",
    "Command",
    "CommandClient",
    "CommandClientOptions",
    "CommandError",
    "CommandModule",
]
