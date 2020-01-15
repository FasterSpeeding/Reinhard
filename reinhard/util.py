import functools
import re
import typing


from reinhard.command_client import CommandError


from hikari.internal_utilities import aio
from hikari.internal_utilities import containers


def get_snowflake(content: str) -> int:
    if re.fullmatch(r"<?[@#]?!?\d+>?", content):
        result = ""
        for char in content:
            if char in ("<", "@", "#", "!", ">"):
                continue
            result += char
        return int(result)
    raise CommandError("Invalid mention or ID supplied.")


def return_error_str(
    errors: typing.Union[Exception, typing.List[Exception]],
    errors_responses: typing.Optional[typing.MutableMapping[Exception, str]] = None,
):
    def decorator(func: aio.CoroutineFunctionT):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> typing.Optional[str]:
            try:
                return await func(*args, **kwargs)
            except errors as e:
                return (errors_responses or containers.EMPTY_DICT).get(type(e)) or str(e)
                # .format(error=str(e)) ?

        return wrapper

    return decorator
