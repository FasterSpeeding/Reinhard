from __future__ import annotations

import random
import typing

from hikari import colours

FAILED_COLOUR: typing.Final[colours.Colour] = colours.Colour(0xF04747)
PASS_COLOUR: typing.Final[colours.Colour] = colours.Colour(0x43B581)

MAYA_BLUE: typing.Final[colours.Colour] = colours.Colour(0x55CDFC)
WHITE: typing.Final[colours.Colour] = colours.Colour(0xFFFFFE)  # 0xFFFFFF is treated as no colour in embeds by Discord.
AMARANTH_PINK: typing.Final[colours.Colour] = colours.Colour(0xF7A8B8)


def embed_colour() -> colours.Colour:
    return random.choices((MAYA_BLUE, WHITE, AMARANTH_PINK), (2, 1, 2))[0]
