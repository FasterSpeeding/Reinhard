from __future__ import annotations

import time
import typing

KeyT = typing.TypeVar("KeyT", bound=typing.Hashable)
ValueT = typing.TypeVar("ValueT")


class ExpiringQueue(typing.MutableSequence[ValueT]):
    __slots__: typing.Sequence[str] = ("_data", "_expire_after")

    def __init__(
        self, seconds: int, /, *, origin: typing.Optional[typing.Sequence[typing.Tuple[ValueT, float]]] = None
    ) -> None:
        self._data = list(origin or ())
        self._expire_after = seconds
        #  TODO: max_length

    def __contains__(self, value: ValueT, /) -> bool:
        return any(value == v for (v, _) in self._data)

    def __delitem__(self, index: typing.Union[slice, int], /) -> None:
        try:
            del self._data[index]
        finally:
            self.gc()

    def __getitem__(self, index: int, /) -> ValueT:
        return self._data[index][0]

    def __iter__(self) -> typing.Iterable[ValueT]:
        return (value for (value, _) in self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setitem__(self, index: typing.Union[int, slice], value: ValueT) -> None:
        self._data[index] = value
        self.gc()

    def __repr__(self) -> str:
        return f"ExpiringQueue<{self._data!r}>"

    def copy(self) -> ExpiringQueue:
        self.gc()
        return ExpiringQueue(self._expire_after, origin=self._data.copy())

    def freeze(self) -> typing.Sequence[ValueT]:
        self.gc()
        return [value for (value, _) in self._data]

    def gc(self) -> None:
        now = time.perf_counter()
        # Is this fine?
        for (_, timestamp) in self._data:
            if now - timestamp < self._expire_after:
                break
            del self._data[0]

    def insert(self, index: int, value: ValueT, /) -> None:
        self.gc()
        self._data.insert(index, (value, time.perf_counter()))


class ExpiringDict(typing.MutableMapping[KeyT, ValueT]):
    __slots__: typing.Sequence[str] = ("_data", "_expire_after")

    def __init__(
        self,
        seconds: int,
        /,
        *,
        origin: typing.Union[
            typing.Mapping[KeyT, typing.Tuple[ValueT, float]], typing.Iterable[KeyT, typing.Tuple[ValueT, float]], None
        ] = None,
    ) -> None:
        self._data = dict(origin) if origin else {}
        self._expire_after = seconds

    def __setitem__(self, key: KeyT, value: ValueT, /) -> None:
        self._data[key] = value
        self.gc()

    def __delitem__(self, key: KeyT, /) -> None:
        try:
            del self._data[key]
        finally:
            self.gc()

    def __getitem__(self, key: KeyT, /) -> ValueT:
        return self._data[key]

    def __len__(self) -> int:
        return len(self)

    def __iter__(self) -> typing.Iterator[KeyT]:
        return iter(self._data)

    def __repr__(self) -> str:
        return f"ExpiringDict<{self._data!r}>"

    def copy(self) -> ExpiringDict:
        self.gc()
        return ExpiringDict(self._expire_after, origin=self._data.copy())

    def freeze(self) -> typing.Mapping[KeyT, ValueT]:
        self.gc()
        return {key: value for key, (_, value) in self._data.items()}

    def gc(self) -> None:
        now = time.perf_counter()
        for key, (_, timestamp) in tuple(self._data.items()):
            if now - timestamp < self._expire_after:
                break
            try:
                del self[key]
            except KeyError:
                continue
