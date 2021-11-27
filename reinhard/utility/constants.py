# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2021, Faster Speeding
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from __future__ import annotations

__all__ = ["AMARANTH_PINK", "embed_colour", "FAILED_COLOUR", "MAYA_BLUE", "PASS_COLOUR", "WHITE"]

import random
import typing

from hikari import colours

FAILED_COLOUR: typing.Final[colours.Colour] = colours.Colour(0xF04747)
"""Colour used to represent a failed execution/attempt."""

PASS_COLOUR: typing.Final[colours.Colour] = colours.Colour(0x43B581)
"""Colour used to represent a successful execution/attempt."""

MAYA_BLUE: typing.Final[colours.Colour] = colours.Colour(0x55CDFC)
WHITE: typing.Final[colours.Colour] = colours.Colour(0xFFFFFE)  # 0xFFFFFF is treated as no colour in embeds by Discord.
AMARANTH_PINK: typing.Final[colours.Colour] = colours.Colour(0xF7A8B8)


def embed_colour() -> colours.Colour:
    return random.choices((MAYA_BLUE, WHITE, AMARANTH_PINK), (2, 1, 2))[0]
