from __future__ import annotations
import dataclasses
import inspect
import typing


from hikari import client
from hikari.internal_utilities import aio
from hikari.internal_utilities import assertions
from hikari.internal_utilities import containers
from hikari.orm.models import guilds
from hikari.orm.models import messages


@dataclasses.dataclass()
class CommandsClientOptions(client.client_options.ClientOptions):
    ...


class Command:
    __slots__ = ("func", "level", "module", "triggers")
    func: aio.CoroutineFunctionT
    level: typing.Optional[int]
    module: typing.Optional[CommandModule]
    triggers: typing.Tuple[str]

    def __init__(
        self,
        func: typing.Optional[aio.CoroutineFunctionT] = None,
        *,
        aliases: typing.Optional[typing.List[str]] = None,
        level: int = 0,
        module: typing.Optional[CommandModule] = None,
        trigger: typing.Optional[str] = None,
    ) -> None:
        self.func = func
        self.level = level
        self.module = module
        if self.func and not trigger:
            trigger = self.generate_trigger()
        self.triggers = tuple(
            trig
            for trig in (trigger, *(aliases or containers.EMPTY_COLLECTION))
            if trig is not None
        )

    def __call__(self, func: aio.CoroutineFunctionT) -> Command:
        self.func = func
        if not self.triggers:
            self.triggers = (self.generate_trigger(),)
        return self

    def bind_module(self, module: CommandModule) -> None:
        self.module = module

    def generate_trigger(self) -> str:
        return self.func.__name__.replace("_", " ")


class CommandModule:
    __slots__ = ("command_client", "error_handler", "module_commands")
    command_client: typing.Optional[CommandClient]
    module_commands: typing.List[Command]
    error_handler: typing.Optional[aio.CoroutineFunctionT]

    def __init__(self, command_client: CommandClient) -> None:
        self.bind_commands()
        self.command_client = command_client

    def bind_commands(self) -> None:
        assertions.assert_that(
            not getattr(self, "module_commands", None),
            f"Cannot bind commands in module '{self.__class__.__name__}' when commands have already been binded.",
        )
        self.module_commands = []
        for name, function in inspect.getmembers(
            self, predicate=lambda func: isinstance(func, Command)
        ):
            function.bind_module(self)
            for trigger in function.triggers:
                assertions.assert_that(
                    self.get_command(trigger) is None,
                    f"Cannot initialise module '{self.__class__.__name__}' with duplicated command trigger '{trigger}'.",
                )
            self.module_commands.append(function)

    async def handle_error(
        self, error: BaseException, message: messages.Message
    ) -> bool:
        error_handler = getattr(self, "error_handler", None)
        if error_handler is not None:
            await error_handler(error, message)
            return True
        return False

    def get_command(self, content: str) -> typing.Optional[Command]:
        for command in self.module_commands:
            for trigger in command.triggers:
                if content.startswith(trigger):
                    return command

    def register_command(
        self,
        func: aio.CoroutineFunctionT,
        trigger: str = None,
        aliases: typing.List[str] = None,
    ) -> None:
        command_obj = Command(func=func, module=self, trigger=trigger, aliases=aliases)
        for trigger in command_obj.triggers:
            assertions.assert_that(
                self.get_command(trigger) is None,
                f"Command trigger '{trigger}' already registered in '{self.__class__.__name__}' module.",
            )
        self.module_commands.append(command_obj)


class CommandClient(client.Client, CommandModule):
    __slots__ = ("get_prefixes", "modules", "prefixes")
    modules: typing.MutableMapping[str, CommandModule]
    get_prefixes: typing.Optional[aio.CoroutineFunctionT]  # TODO: or normal method.
    prefixes: typing.List[str]

    def __init__(
        self,
        prefixes: typing.List[str],
        token: str,
        *,
        modules: typing.List[str] = None,
        options: typing.Optional[CommandsClientOptions] = None,
    ) -> None:
        super().__init__(token=token, options=options)
        self.bind_commands()
        self.bind_listeners()
        self.load_modules(*(modules or containers.EMPTY_SEQUENCE))
        self.prefixes = prefixes

    def bind_listeners(self) -> None:
        for name, function in inspect.getmembers(
            self, predicate=inspect.iscoroutinefunction
        ):
            if name.startswith("on_"):
                self.add_event(name[3:], function)

    async def check_prefix(self, message: messages.Message) -> typing.Optional[str]:
        trigger_prefix = None
        for prefix in await self._get_prefixes(message.guild_id):
            if message.content.startswith(prefix):
                trigger_prefix = prefix
                break
        return trigger_prefix

    def get_global_command(self, content: str) -> typing.Optional[Command]:
        for module in [self, *self.modules]:
            command = module.get_command(content)
            if command:
                return command

    async def _get_prefixes(
        self, guild: typing.Optional[guilds.GuildLikeT]
    ) -> typing.List[str]:
        if guild is None or not hasattr(self, "get_prefixes"):
            return self.prefixes

        if inspect.iscoroutinefunction(self.get_prefixes):
            guild_prefix = await self.get_prefixes(int(guild))  # TODO: maybe don't
        else:
            guild_prefix = self.get_prefixes(int(guild))

        return [guild_prefix, *self.prefixes]

    def load_modules(self, *modules: typing.Type[CommandModule]) -> None:
        self.modules = {
            module.__class__.__name__: module(self) for module in modules
        }  # TODO: This so that modules is a string not the Modules themselves

    async def on_message_create(self, message: messages.Message) -> bool:
        prefix = await self.check_prefix(
            message
        )  # TODO: maybe one day we won't have to await this.
        if not prefix:
            return False

        command_args = message.content[len(prefix) :]
        command = self.get_global_command(command_args)
        if not command:
            return False

        command_args = command_args[len(command.func.__name__) :]
        #  TODO: for now this is also a bit basic...
        try:
            result = await command.func(self, message, command_args)
            if isinstance(result, str):
                await self._fabric.http_api.create_message(
                    str(message.channel_id), content=result
                )  # TODO: automatically a file response.
        except Exception as e:
            await command.module.handle_error(e, message) or await self.handle_error(
                e, message
            )
            raise e
        return True
