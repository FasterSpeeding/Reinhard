from __future__ import annotations

import abc
import asyncio
import datetime
import logging
import traceback
import typing

import attr
from hikari import emojis
from hikari import errors
from hikari import events

if typing.TYPE_CHECKING:
    from hikari import bases
    from hikari import embeds
    from hikari import messages
    from hikari.clients import components as hikari_components


DELETE_AND_END = object()
END = object()


@attr.attrs(init=True, kw_only=True, repr=True, slots=True)
class AbstractResponsePaginator(abc.ABC):
    authors: typing.Sequence[bases.Snowflake] = attr.attrib(factory=list)

    enabled_triggers: typing.Tuple[str, ...] = attr.attrib(factory=list)

    last_triggered: datetime.datetime = attr.attrib(factory=datetime.datetime.now)

    locked: bool = attr.attrib(default=False)

    @abc.abstractmethod
    async def register_message(self, message: messages.Message) -> None:  # TODO: ???
        ...

    @abc.abstractmethod
    async def on_reaction_modify(self, emoji: emojis.Emoji, user_id: bases.Snowflake) -> typing.Optional[typing.Any]:
        ...

    @abc.abstractmethod
    async def deregister_message(self) -> None:
        ...

    @property
    @abc.abstractmethod
    def expired(self) -> bool:
        ...


@attr.attrs(init=False, kw_only=True, repr=True, slots=True)
class ResponsePaginator(AbstractResponsePaginator):
    _buffer: typing.MutableSequence[typing.Tuple[str, embeds.Embed]] = attr.attrib()

    _emoji_mapping: typing.MutableMapping[
        typing.Union[bases.Snowflake, str], typing.Callable[[], typing.Any]
    ] = attr.attrib()

    _generator: typing.Optional[typing.Iterator[typing.Tuple[str, embeds.Embed]]] = attr.attrib()

    _index: int = attr.attrib()

    message: typing.Optional[messages.Message] = attr.attrib()

    timeout: datetime.timedelta = attr.attrib()

    def __init__(
        self,
        first_entry: typing.Tuple[str, embeds.Embed],
        generator: typing.Iterator[typing.Tuple[str, embeds.Embed]],
        *,
        authors: typing.Optional[typing.Sequence[bases.Snowflake]],
        enabled_triggers: typing.Tuple[str, ...] = (
            "\N{BLACK LEFT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}",
            "\N{BLACK SQUARE FOR STOP}\N{VARIATION SELECTOR-16}",
            "\N{BLACK RIGHT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}",
        ),
        timeout: typing.Optional[datetime.timedelta] = None,
    ) -> None:
        super().__init__(authors=authors or [], enabled_triggers=enabled_triggers)
        self._buffer = [first_entry]
        self._emoji_mapping = {
            "\N{BLACK LEFT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}": self.previous,
            "\N{BLACK SQUARE FOR STOP}\N{VARIATION SELECTOR-16}": self.on_disable,
            "\N{BLACK RIGHT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}": self.next,
            "\N{SKULL AND CROSSBONES}\N{VARIATION SELECTOR-16}": self.last,
        }
        self._generator = generator
        self._index = 0
        self.message = None
        self.timeout = timeout or datetime.timedelta(seconds=15)

    def next(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        if len(self._buffer) > self._index + 1:
            self._index += 1
            return self._buffer[self._index]

        if self._generator:
            try:
                embed = next(self._generator)
                self._index += 1
                self._buffer.append(embed)
                return embed
            except StopIteration:
                self._generator = None
                return None
        return None

    def previous(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        if self._index <= 0:
            return None

        self._index -= 1
        return self._buffer[self._index]

    def first(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        if self._index == 0:
            return None
        return self._buffer[0]

    def last(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        if self._generator:
            self.locked = True
            self._buffer.extend(self._generator)
        self.locked = False
        if self._buffer:
            return self._buffer[-1]
        return None

    async def register_message(self, message: messages.Message) -> None:  # TODO: ???
        self.message = message
        for emoji in self.enabled_triggers:
            await message.add_reaction(emoji)

    async def on_reaction_modify(self, emoji: emojis.Emoji, user_id: bases.Snowflake) -> typing.Optional[typing.Any]:
        if self.expired:
            return END

        if self.message is None or self.authors and user_id not in self.authors or self.locked:
            return

        emoji = emoji.name if isinstance(emoji, emojis.UnicodeEmoji) else emoji.id
        if emoji not in self.enabled_triggers or (method := self._emoji_mapping.get(emoji)):
            result = method()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                if result is END or result is DELETE_AND_END:
                    return END
                self.last_triggered = datetime.datetime.now()
                await self.message.safe_edit(content=result[0], embed=result[1])  # TODO: safe or normal edit?

    def on_disable(self) -> typing.Any:
        if message := self.message:
            self.message = None
            asyncio.create_task(self._delete_message(message))
        return END

    async def deregister_message(self) -> None:
        if message := self.message:
            self.message = None
            for emoji in self.enabled_triggers:
                try:
                    await message.remove_reaction(emoji)
                except errors.HTTPError:
                    ...

    @property
    def expired(self) -> bool:
        return self.timeout < datetime.datetime.now() - self.last_triggered

    @staticmethod
    async def _delete_message(message: messages.Message) -> None:
        try:
            await message.delete()
        except (errors.NotFound, errors.Forbidden):  # TODO: better permission handling.
            ...


class AsyncResponsePaginator(ResponsePaginator):
    _emoji_mapping: typing.MutableMapping[
        str, typing.Callable[[], typing.Coroutine[typing.Any, typing.Any, typing.Any]]
    ]
    _generator: typing.Optional[typing.AsyncIterator[typing.Tuple[str, embeds.Embed]]]

    def __init__(
        self,
        first_entry: typing.Tuple[str, embeds.Embed],
        generator: typing.AsyncIterator[typing.Tuple[str, embeds.Embed]],
        *,
        authors: typing.Optional[typing.Sequence[bases.Snowflake]] = None,
        timeout: typing.Optional[datetime.timedelta] = None,
    ) -> None:
        super().__init__(first_entry, generator, authors=authors, timeout=timeout)

    async def next(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        if len(self._buffer) < self._index + 1:
            self._index += 1
            return self._buffer[self._index]
        if self._generator:
            async for result in self._generator:
                self._index += 1
                self._buffer.append(result)
                return result
            else:
                self._generator = None
                return None
        return None

    async def previous(self) -> typing.Optional[embeds.Embed]:
        return super().previous()

    async def last(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        self.locked = True
        if self._generator:
            async for embed in self._generator:
                self._buffer.append(embed)
        self._generator = None
        if self._buffer:
            self.locked = False
            self._index = len(self._buffer) - 1
            return self._buffer[-1]
        return None

    async def first(self) -> typing.Optional[typing.Tuple[str, embeds.Embed]]:
        return super().first()

    async def on_disable(self) -> typing.Any:
        return super().on_disable()


@attr.attrs(init=False, repr=True, slots=True)
class PaginatorPool:
    blacklist: typing.MutableSequence[bases.Snowflake] = attr.attrib()

    _components: hikari_components.Components = attr.attrib()

    garbage_collect_task: typing.Optional[asyncio.Task] = attr.attrib()

    listeners: typing.MutableMapping[bases.Snowflake, AbstractResponsePaginator] = attr.attrib()

    logger: logging.Logger = attr.attrib()

    def __init__(self, components: hikari_components.Components) -> None:
        self.blacklist = []
        self._components = components
        components.event_dispatcher.add_listener(events.MessageReactionAddEvent, self.on_reaction_modify)
        components.event_dispatcher.add_listener(events.MessageReactionRemoveEvent, self.on_reaction_modify)
        self.garbage_collect_task = None
        self.listeners = {}
        self.logger = logging.getLogger(type(self).__qualname__)

    async def register_message(self, message: messages.Message, paginator: AbstractResponsePaginator) -> None:
        if self.garbage_collect_task is None:
            self.garbage_collect_task = asyncio.create_task(self.garbage_collect())
            self.blacklist.append((await self._components.rest.fetch_me()).id)  # TODO: State?
        self.listeners[message.id] = paginator
        await paginator.register_message(message)

    async def on_reaction_modify(
        self, event: typing.Union[events.MessageReactionAddEvent, events.MessageReactionRemoveEvent]
    ) -> None:
        if event.user_id in self.blacklist:
            return

        if listener := self.listeners.get(event.message_id):
            result = await listener.on_reaction_modify(event.emoji, user_id=event.user_id)
            if result is END:
                del self.listeners[event.message_id]
                await listener.deregister_message()

    async def garbage_collect(self):
        while True:
            self.logger.debug("performing embed paginator garbage collection pass.")
            try:
                for listener_id, listener in tuple(self.listeners.items()):
                    if listener.expired and listener_id in self.listeners and not listener.locked:
                        del self.listeners[listener_id]
                        await listener.deregister_message()  # TODO: asyncio.create_task?
            except Exception as exc:
                self.logger.warning("Failed to garbage collect embed paginator:\n  - %s", exc)
                traceback.print_exc()
            await asyncio.sleep(5)  # TODO: is this good?


def string_paginator(
    lines: typing.Iterable[str], *, char_limit: int = 2000, line_limit: int = 25, wrapper: str = "{}"
) -> typing.Iterator[typing.Tuple[str, int]]:  # Iterator or iterable?
    page_number = 0
    page = []
    for line in lines:
        if page and sum(len(pline) + 1 for pline in page) + len(line) > char_limit or len(page) + 1 > line_limit:
            page_number += 1
            yield wrapper.format("\n".join(page)), page_number
            page.clear()

        while len(line) >= char_limit:
            page_number += 1
            yield wrapper.format(line[:char_limit]), page_number
            line = line[char_limit:]

        if line:
            page.append(line)

    if page:
        yield wrapper.format("\n".join(page)), page_number + 1
