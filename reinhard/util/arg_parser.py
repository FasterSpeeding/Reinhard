import typing


QUOTE_SEPARATORS = ('"', "'")


def basic_arg_parsers(content: str) -> typing.Iterable[str]:
    last_space: int = -1
    spaces_found_while_quoting: typing.List[int] = []
    last_quote: typing.Optional[int] = None
    i: int = -1
    while i < len(content):
        i += 1
        char = content[i] if i != len(content) else " "
        if char == " " and i - last_space > 1:
            if last_quote:
                spaces_found_while_quoting.append(i)
                continue
            else:
                yield content[last_space + 1 : i]
                last_space = i
        elif char in QUOTE_SEPARATORS: # and content[i -  1] != "\\":
            if last_quote is None:
                last_quote = i
                spaces_found_while_quoting.append(last_space)
            elif content[last_quote] == char:
                yield content[last_quote + 1 : i]
                last_space = i
                spaces_found_while_quoting.clear()
                last_quote = None
    if last_quote:
        i = 1
        while i < len(spaces_found_while_quoting):
            yield content[spaces_found_while_quoting[i - 1] + 1 : spaces_found_while_quoting[i]]
            spaces_found_while_quoting.pop(i - 1)


# TODO: handle automatic conversion.


if __name__ == "__main__":
    print(list(basic_arg_parsers("""I 'am "a test.""")))
    print(list(basic_arg_parsers("I will 'defeat.")))
    print(list(basic_arg_parsers("I will 'defeat the magnitude baby.")))
    print(list(basic_arg_parsers("""I.""")))
    print(list(basic_arg_parsers("""I am `going to` die""")))
    print(list(basic_arg_parsers("""I am `going "to` die""")))
    print(list(basic_arg_parsers("""""")))
