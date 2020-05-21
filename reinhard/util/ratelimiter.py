from __future__ import annotations

import abc
import attr
import datetime
import difflib
import time
import typing

# from . import cache
from reinhard.util import cache

if typing.TYPE_CHECKING:
    from hikari import bases
    from hikari import messages
    from tanjun import commands


@attr.attrs(auto_attribs=True, eq=False, init=True, kw_only=True, slots=False)
class AbstractCall(abc.ABC):  # TODO: better name
    # date: datetime.datetime
    level: int = attr.attrib(default=1)  # TODO: is this safe?

    #    @property
    #    @abc.abstractmethod
    #    def expired(self) -> bool:
    #        ...

    @typing.overload
    @abc.abstractmethod
    def similarity_check(self, other: AbstractCall) -> int:
        ...

    @typing.overload
    @abc.abstractmethod
    def similarity_check(self, other: typing.Any) -> typing.Literal[0]:
        ...

    @abc.abstractmethod
    def similarity_check(self, other: AbstractCall) -> int:
        ...


@attr.attrs(auto_attribs=True, eq=False, init=False, kw_only=True, slots=True)
class MessageCall(AbstractCall):
    content: str

    def __init__(self, message: messages.Message) -> None:
        super().__init__()
        self.content = message.content

    def similarity_check(self, other: typing.Union[typing.Any, MessageCall]) -> int:
        if not isinstance(other, type(self)):
            return 0

        return round(difflib.SequenceMatcher(a=self.content, b=other.content).ratio() * 100)


@attr.attrs(auto_attribs=True, eq=False, init=False, kw_only=True, slots=True)
class CommandCall(AbstractCall):
    command: commands.AbstractCommand
    content: str

    def __init__(self, ctx: commands.Context) -> None:
        super().__init__()
        self.command = ctx.command
        self.content = ctx.message.content

    def similarity_check(self, other: AbstractCall) -> int:
        if not isinstance(other, type(self)):
            return 0

        similarity = round(difflib.SequenceMatcher(a=self.content, b=other.content).ratio() * 75)
        if self.command == other.command:
            similarity += 25

        return similarity  # Are these numbers good?


@attr.attrs(init=True, kw_only=True, slots=False)
class AbstractBucket(abc.ABC):
    calls: typing.MutableSequence[AbstractCall] = attr.attrib(eq=False)

    @abc.abstractmethod
    def add_call(self, call: AbstractCall) -> None:
        ...

    @property
    @abc.abstractmethod
    def expired(self) -> bool:
        ...

    @property
    @abc.abstractmethod
    def level(self) -> int:
        ...


@attr.attrs(eq=False, hash=True, init=False, slots=False)
class SimpleBucket(AbstractBucket):
    def __init__(self, expire_after: datetime.timedelta) -> None:
        super().__init__(calls=cache.ExpiringList(int(expire_after.total_seconds())))

    def add_call(self, call: AbstractCall) -> None:
        similarities = [other_call.similarity_check(call) for other_call in self.calls]
        similarities.sort()
        if not similarities:
            pass
        elif similarities[-1] >= 100:  # This shouldn't ever be greater than 100 but meh.
            call.level = 3
        elif similarities[-1] >= 60:  # TODO: make this dynamic
            call.level = 2

        self.calls.append(call)

    @property
    def expired(self) -> bool:
        return not self.calls

    @property
    def level(self) -> int:  # I think this could be a race condition hence the copy.
        return sum(call.level for call in self.calls.copy())


@attr.attrs(init=True, kw_only=True, slots=True)
class BucketPool:
    affinity: int = attr.attrib()
    buckets: typing.MutableMapping[bases.Snowflake, AbstractBucket] = attr.attrib(factory=dict)
    expire_after: datetime.timedelta = attr.attrib()

    def __init__(self, affinity: int, expire_after: datetime.timedelta) -> None:
        self.affinity = affinity
        self.buckets = {}
        self.expire_after = expire_after

    def _create_bucket(self) -> AbstractBucket:
        return SimpleBucket(expire_after=self.expire_after)

    def add_cool(self, entity: bases.Snowflake, call: AbstractCall) -> None:
        if entity not in self.buckets:
            self.buckets[entity] = self._create_bucket()
        self.buckets[entity].add_call(call)

    @property
    def is_empty(self) -> bool:
        return not self.buckets

    def get_level(self, entity: bases.Snowflake) -> int:
        if bucket := self.buckets.get(entity):
            return bucket.level
        return 0

    def garbage_collect(self) -> None:
        for entity, bucket in tuple(self.buckets.items()):
            if bucket.expired:
                del self.buckets[entity]


@attr.attrs(init=True, kw_only=True, slots=True)
class ComplexBucketPool:
    affinity: int = attr.attrib()
    expire_after: datetime.timedelta = attr.attrib()
    pools: typing.MutableMapping[bases.Snowflake, BucketPool] = attr.attrib(factory=dict)

    def _create_pool(self) -> BucketPool:
        return BucketPool(expire_after=self.expire_after, affinity=self.affinity)

    def get_or_create_pool(self, target: bases.Snowflake) -> BucketPool:
        if target not in self.pools:
            self.pools[target] = self._create_pool()
        return self.pools[target]

    def garbage_collect(self) -> None:  # TODO: naming
        for key, pool in tuple(self.pools.items()):
            if pool.is_empty:
                del self.pools[key]
