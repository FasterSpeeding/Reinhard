from __future__ import annotations

import time
import typing


class ExpiringList(list):
    def __init__(self, seconds: int, *, origin: typing.Sequence[typing.Tuple[typing.Any, float]] = None) -> None:
        super().__init__(origin or ())
        self._expire_after = seconds

    insert = index = remove = None

    def append(self, __object: typing.Any) -> None:
        self.garbage_collect()
        super().append((__object, time.perf_counter()))

    def copy(self) -> ExpiringList:
        self.garbage_collect()  # TODO: ?
        return ExpiringList(self._expire_after, origin=super().copy())

    def extend(self, __iterable: typing.Iterable[typing.Any]) -> None:
        self.garbage_collect()
        super().extend(((value, time.perf_counter()) for value in __iterable))

    def garbage_collect(self) -> None:
        now = time.perf_counter()
        to_remove = []
        for value in super().__iter__():
            if now - value[1] < self._expire_after:
                break
            to_remove.append(value)

        for value in to_remove:
            try:
                super().remove(value)
            except ValueError:
                continue

    def pop(self, __index: int = ...) -> typing.Any:
        self.garbage_collect()
        return super().pop(__index)[1]

    def __contains__(self, item) -> bool:
        # calling garbage_collect here would overlap with the garbage_collect call in __iter__
        return any(value == item for (value, _) in super().__iter__())

    def __getitem__(self, item) -> None:
        self.garbage_collect()
        return super().__getitem__(item)[1]

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
        self.garbage_collect()  # TODO: ?
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
        if isinstance(__m, dict) and not isinstance(__m, ExpiringDict):
            __m = ((key, (value, time.perf_counter())) for key, value in __m.items())
        elif not isinstance(__m, dict):
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
