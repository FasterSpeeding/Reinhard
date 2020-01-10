from __future__ import annotations


import pydantic
import typing


class CustomModelBase(pydantic.BaseModel):
    def dict(
        self,
        *,
        include: typing.Union[
            pydantic.typing.AbstractSetIntStr, pydantic.typing.DictIntStrAny
        ] = None,
        exclude: typing.Union[
            pydantic.typing.AbstractSetIntStr, pydantic.typing.DictIntStrAny
        ] = None,
        by_alias: bool = False,
        skip_defaults: bool = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
    ) -> pydantic.typing.DictStrAny:
        return dict(
            (
                (key, value)
                for key, value in super()
                .dict(
                    include=include,
                    exclude=exclude,
                    by_alias=by_alias,
                    skip_defaults=skip_defaults,
                    exclude_unset=exclude_unset,
                    exclude_defaults=exclude_defaults,
                    exclude_none=exclude_none,
                )
                .items()
                if value is not None
            )
        )


class DatabaseConfig(CustomModelBase):
    password: str
    host: str = "localhost"
    user: str = "postgres"
    database: str = "postgres"
    port: int = 5432


class Config(CustomModelBase):
    database: DatabaseConfig
    prefixes: typing.List[str] = None
    token: str
