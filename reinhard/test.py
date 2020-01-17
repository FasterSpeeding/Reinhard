import typing


def basic_arg_parsers(content: str) -> typing.Iterable[str]:
    last_space: int = -1
    spaces_found_while_quoting: typing.List[int] = []
    last_quote: typing.Optional[int] = None
    for i, char in enumerate(content + " "):
        if char == " " and i - last_space > 1:
            if last_quote:
                spaces_found_while_quoting.append(i)
                continue
            else:
                yield content[last_space + 1 : i]
                last_space = i
        elif char in ('"', "'"):
            if last_quote is None:
                last_quote = i
                spaces_found_while_quoting.append(last_space)
            elif content[last_quote] == char:
                yield content[last_quote + 1 : i]
                last_space = i
                spaces_found_while_quoting.clear()
                last_quote = None
    if last_quote:
        iterable = enumerate(spaces_found_while_quoting)
        next(iterable)
        for i, index in iterable:
            yield content[spaces_found_while_quoting[i - 1] + 1 : index]


#  TODO: handle when the quotes aren't finished.
#  TODO: handle automatic conversion.


if __name__ == "__main__":
    print(list(basic_arg_parsers("""I 'am "a test.""")))
    print(list(basic_arg_parsers("I will 'defeat.")))
    print(list(basic_arg_parsers("""I.""")))
    print(list(basic_arg_parsers("""I am `going to` die""")))
