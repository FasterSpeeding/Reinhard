from __future__ import annotations

import time
import typing


class ExpiringList(list):  # Does sort work here?
    def __init__(self, seconds: int, *, origin: typing.Sequence[typing.Tuple[typing.Any, float]] = None) -> None:
        super().__init__(origin or ())
        self._expire_after = seconds

    def append(self, __object: typing.Any) -> None:
        self.garbage_collect()
        super().append((__object, time.perf_counter()))

    def copy(self) -> ExpiringList:
        self.garbage_collect()
        return ExpiringList(self._expire_after, origin=super().copy())

    def count(self, __value: typing.Any) -> int:
        self.garbage_collect()
        return sum(1 for (value, _) in super().__iter__() if value == __value)

    def extend(self, __iterable: typing.Iterable[typing.Any]) -> None:
        self.garbage_collect()
        if isinstance(__iterable, ExpiringList):
            super().extend(__iterable)
        else:
            super().extend((value, time.perf_counter()) for value in __iterable)

    def garbage_collect(self) -> None:
        now = time.perf_counter()
        to_remove = []
        for value in super().__iter__():
            if now - value[1] >= self._expire_after:
                to_remove.append(value)

        for value in to_remove:
            try:
                super().remove(value)
            except ValueError:
                continue

    def index(self, __value: typing.Any, __start: int = ..., __stop: int = ...) -> int:
        self.garbage_collect()
        for index in range(__start or 0, __stop or super().__len__()):
            try:
                if super().__getitem__(index)[0] == __value:
                    return index
            except IndexError:
                break
        raise ValueError(f"{__value:r} not found in list.")

    def insert(self, __index: int, __object: typing.Any) -> None:
        self.garbage_collect()
        super().insert(__index, (__object, time.perf_counter()))

    def pop(self, __index: int = ...) -> typing.Any:
        self.garbage_collect()
        return super().pop(__index)[0]

    def remove(self, __value: typing.Any) -> None:
        self.garbage_collect()
        for value in super().__iter__():
            if value[0] == __value:
                super().remove(value)
                break
        else:
            raise ValueError(f"{__value:r} not found in list.")

    def __contains__(self, item) -> bool:
        self.garbage_collect()
        return any(value == item for (value, _) in super().__iter__())

    def __getitem__(self, item) -> None:
        self.garbage_collect()
        return super().__getitem__(item)[0]

    def __iter__(self) -> typing.Iterable[typing.Any]:
        # recursive garbage collecting here is recursive somehow. Too bad.
        self.garbage_collect()
        return (value for (value, _) in super().__iter__())

    def __len__(self) -> int:
        self.garbage_collect()
        return super().__len__()

    def __setitem__(self, key, value) -> None:
        self.garbage_collect()
        super().__setitem__(key, (value, time.perf_counter()))


class ExpiringQueue(typing.Sequence):
    def __init__(self, seconds: int, *, origin: typing.Sequence[typing.Tuple[typing.Any, float]] = None) -> None:
        self._data = list(origin or ())
        self._expire_after = seconds
        #  TODO: max_length

    def append(self, __object: typing.Any) -> None:
        self.garbage_collect()
        self._data.append((__object, time.perf_counter()))

    def clear(self) -> None:
        self._data.clear()

    def copy(self) -> ExpiringQueue:
        self.garbage_collect()
        return ExpiringQueue(self._expire_after, origin=self._data.copy())

    def count(self, __value: typing.Any) -> int:
        self.garbage_collect()
        return sum(1 for (value, _) in self._data if value == __value)

    def extend(self, __iterable: typing.Iterable[typing.Any]) -> None:
        self.garbage_collect()
        if isinstance(__iterable, ExpiringQueue):
            self._data.extend(__iterable)
        else:
            self._data.extend((value, time.perf_counter()) for value in __iterable)

    def garbage_collect(self) -> None:
        now = time.perf_counter()
        # Is this fine?
        for (_, timestamp) in self._data:
            if now - timestamp < self._expire_after:
                break
            del self._data[0]

    def index(self, __value: typing.Any, __start: int = ..., __stop: int = ...) -> int:
        self.garbage_collect()
        for index in range(__start or 0, __stop or super().__len__()):
            try:
                if self._data[index][0] == __value:
                    return index
            except IndexError:
                break
        raise ValueError(f"{__value:r} not found in list.")

    def pop(self, __index: int = ...) -> typing.Any:
        self.garbage_collect()
        return self._data.pop(__index)[0]

    def remove(self, __value: typing.Any) -> None:
        self.garbage_collect()
        for value in self._data:
            if value[0] == __value:
                try:
                    self._data.remove(value)
                except ValueError:  # TODO: is this fine?
                    pass
                else:  # TODO: or else?
                    break
        else:
            raise ValueError(f"{__value:r} not found in list.")

    def __contains__(self, item) -> bool:
        self.garbage_collect()
        return any(value == item for (value, _) in self._data)

    def __getitem__(self, item) -> typing.Any:
        self.garbage_collect()
        return self._data[item][0]

    def __iter__(self) -> typing.Iterable[typing.Any]:
        # recursive garbage collecting here is recursive somehow. Too bad.
        self.garbage_collect()
        return (value for (value, _) in self._data)

    def __len__(self) -> int:
        self.garbage_collect()
        return len(self._data)

    def __repr__(self) -> str:
        return f"ExpiringQueue<{self._data!r}>"


class ExpiringDict(dict):
    def __init__(
        self,
        seconds: int,
        *,
        origin: typing.Union[
            typing.Mapping[typing.Hashable, typing.Tuple[typing.Any, float]],
            typing.Iterable[typing.Hashable, typing.Tuple[typing.Any, float]],
        ] = None,
    ) -> None:
        super().__init__(origin or ())
        self._expire_after = seconds

    def copy(self) -> ExpiringDict:
        self.garbage_collect()
        return ExpiringDict(self._expire_after, origin=super().copy())

    def fromkeys(self, __iterable: typing.Iterable[typing.Hashable]) -> ExpiringDict[typing.Hashable, typing.Any]:
        return ExpiringDict(
            seconds=self._expire_after, origin=((key, (None, time.perf_counter())) for key in __iterable)
        )

    def garbage_collect(self) -> None:
        now = time.perf_counter()
        for key, (_, timestamp) in tuple(super().items()):
            if now - timestamp < self._expire_after:
                break
            try:
                del self[key]
            except KeyError:
                continue

    def get(self, k: typing.Hashable, default: typing.Any = None) -> typing.Optional[typing.Any]:
        self.garbage_collect()
        if result := super().get(k):
            return result[0]
        return default

    def items(self) -> typing.Iterable[typing.Tuple[typing.Hashable, typing.Any]]:
        self.garbage_collect()
        return ((key, value) for (key, (value, _)) in super().items())

    def pop(self, k: typing.Hashable) -> typing.Any:
        self.garbage_collect()
        return super().pop(k)[0]

    def popitem(self) -> typing.Tuple[typing.Hashable, typing.Any]:
        self.garbage_collect()
        return super().popitem()[0]

    def setdefault(self, __key: typing.Hashable, __default: typing.Any = ...) -> typing.Any:
        self.garbage_collect()
        super().setdefault(__key, (__default, time.perf_counter()))

    def update(
        self, __m: typing.Optional[typing.Mapping[typing.Hashable, typing.Any]] = None, **kwargs: typing.Any
    ) -> None:
        self.garbage_collect()
        if isinstance(__m, dict) and not isinstance(__m, ExpiringDict):
            __m = ((key, (value, time.perf_counter())) for key, value in __m.items())
        elif not isinstance(__m, dict) and __m is not None:
            __m = ((key, (value, time.perf_counter())) for key, value in __m)
        if kwargs:
            kwargs = {key: (value, time.perf_counter()) for key, value in kwargs.items()}
        super().update(__m or (), **kwargs)

    def values(self) -> typing.Iterable[typing.Any]:
        self.garbage_collect()
        return (value for (value, _) in super().values())

    def __contains__(self, item: typing.Hashable) -> bool:
        self.garbage_collect()
        return super().__contains__(item)

    def __getitem__(self, item: typing.Hashable) -> typing.Optional[typing.Any]:
        self.garbage_collect()
        return super().__getitem__(item)[0]

    def __iter__(self) -> typing.Iterable[typing.Hashable]:
        self.garbage_collect()
        return super().__iter__()

    def __len__(self) -> int:
        self.garbage_collect()
        return super().__len__()

    def __setitem__(self, key: typing.Hashable, value: typing.Any) -> None:
        self.garbage_collect()
        super().__setitem__(key, (value, time.perf_counter()))
