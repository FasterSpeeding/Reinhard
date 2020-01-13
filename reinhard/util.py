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


def return_error_str_factory(
    errors: typing.Union[Exception, typing.List[Exception]],
    errors_responses: typing.Optional[typing.MutableMapping[Exception, str]] = None,
):
    def return_error_str_func_binder(func: aio.CoroutineFunctionT):
        async def return_error_str(*args, **kwargs) -> typing.Optional[str]:
            try:
                return await func(*args, **kwargs)
            except errors as e:
                return (errors_responses or containers.EMPTY_DICT).get(type(e)) or str(e)
                # .format(error=str(e)) ?

        # Hack-around to allow compatibility with the `Command` class.
        return_error_str.__name__ = func.__name__

        return return_error_str

    return return_error_str_func_binder
