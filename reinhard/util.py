import re


from reinhard.command_client import CommandError


def get_snowflake(content: str) -> int:
    if re.fullmatch(r"<?[@#]?!?\d+>?", content):
        for to_replace in (("<", ""), ("@", ""), ("#", ""), ("!", ""), (">", "")):
            content = content.replace(*to_replace)
        return int(content)
    raise CommandError("Invalid mention or ID supplied.")
