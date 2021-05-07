from __future__ import annotations

import abc
import datetime
import difflib
import typing

# from . import cache
from ..util import cache

if typing.TYPE_CHECKING:
    from hikari import messages
    from hikari import snowflakes
    from tanjun import traits


class AbstractCall(abc.ABC):  # TODO: better name
    __slots__: typing.Sequence[str] = ()

    # date: datetime.datetime

    #    @property
    #    @abc.abstractmethod
    #    def expired(self) -> bool:
    #        ...

    @property
    @abc.abstractmethod
    def level(self) -> int:
        raise NotImplementedError

    @level.setter
    def level(self, level: int) -> None:
        raise NotImplementedError

    @typing.overload
    @abc.abstractmethod
    def similarity_check(self, other: AbstractCall) -> int:
        raise NotImplementedError

    @typing.overload
    @abc.abstractmethod
    def similarity_check(self, other: typing.Any) -> typing.Literal[0]:
        raise NotImplementedError

    @abc.abstractmethod
    def similarity_check(self, other: AbstractCall) -> int:
        raise NotImplementedError


class MessageCall(AbstractCall):
    __slots__: typing.Sequence[str] = ("content", "level")

    def __init__(self, message: messages.Message) -> None:
        if message.content is None:
            raise ValueError("Cannot initiate a message call for a message with no content")

        self.content = message.content
        self.level = 1

    def similarity_check(self, other: typing.Union[typing.Any, MessageCall]) -> int:
        if not isinstance(other, type(self)):
            return 0

        return round(difflib.SequenceMatcher(a=self.content, b=other.content).ratio() * 100)


class CommandCall(AbstractCall):
    __slots__: typing.Sequence[str] = ("command", "content", "level")

    def __init__(self, ctx: traits.Context) -> None:
        self.command = ctx.command
        self.content = ctx.message.content
        self.level = 1

    def similarity_check(self, other: AbstractCall) -> int:
        if not isinstance(other, type(self)):
            return 0

        similarity = round(difflib.SequenceMatcher(a=self.content, b=other.content).ratio() * 75)
        if self.command == other.command:
            similarity += 25

        return similarity  # Are these numbers good?


class AbstractBucket(abc.ABC):
    __slots__: typing.Sequence[str] = ()

    @property
    @abc.abstractmethod
    def calls(self) -> typing.MutableSequence[AbstractCall]:
        raise NotImplementedError

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


class SimpleBucket(AbstractBucket):
    __slots__: typing.Sequence[str] = ("_calls",)

    def __init__(self, expire_after: datetime.timedelta) -> None:
        self._calls = cache.ExpiringQueue(int(expire_after.total_seconds()))

    def add_call(self, call: AbstractCall) -> None:
        similarities = [other_call.similarity_check(call) for other_call in self.calls]
        similarities.sort()
        if not similarities:
            pass
        elif similarities[-1] >= 100:  # This shouldn't ever be greater than 100 but meh.
            call.level = 3
        elif similarities[-1] >= 60:  # TODO: make this dynamic
            call.level = 2

        self._calls.append(call)

    @property
    def calls(self) -> typing.MutableSequence[AbstractCall]:
        return self._calls

    @property
    def expired(self) -> bool:
        return not self._calls

    @property
    def level(self) -> int:  # I think this could be a race condition hence the copy.
        return sum(call.level for call in self._calls.copy())


class BucketPool:
    __slots__: typing.Sequence[str] = ("affinity", "buckets", "expire_after")

    def __init__(self, affinity: int, expire_after: datetime.timedelta) -> None:
        self.affinity = affinity
        self.buckets: typing.MutableMapping[snowflakes.Snowflake, AbstractBucket] = {}
        self.expire_after = expire_after

    def _create_bucket(self) -> AbstractBucket:
        return SimpleBucket(expire_after=self.expire_after)

    def add_cool(self, entity: snowflakes.Snowflake, call: AbstractCall) -> None:
        if entity not in self.buckets:
            self.buckets[entity] = self._create_bucket()
        self.buckets[entity].add_call(call)

    @property
    def is_empty(self) -> bool:
        return not self.buckets

    def get_level(self, entity: snowflakes.Snowflake) -> int:
        if bucket := self.buckets.get(entity):
            return bucket.level
        return 0

    def garbage_collect(self) -> None:
        for entity, bucket in tuple(self.buckets.items()):
            if bucket.expired:
                del self.buckets[entity]


class ComplexBucketPool:
    __slots__: typing.Sequence[str] = ("affinity", "expire_after", "pools")

    def __init__(self, affinity: int, expire_after: datetime.timedelta) -> None:
        self.affinity = affinity
        self.expire_after = expire_after
        self.pools: typing.MutableMapping[snowflakes.Snowflake, BucketPool] = {}

    def _create_pool(self) -> BucketPool:
        return BucketPool(expire_after=self.expire_after, affinity=self.affinity)

    def get_or_create_pool(self, target: snowflakes.Snowflake) -> BucketPool:
        if target not in self.pools:
            self.pools[target] = self._create_pool()
        return self.pools[target]

    def garbage_collect(self) -> None:  # TODO: naming
        for key, pool in tuple(self.pools.items()):
            if pool.is_empty:
                del self.pools[key]
