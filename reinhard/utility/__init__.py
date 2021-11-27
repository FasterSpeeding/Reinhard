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

__all__: list[str] = [
    # basic.py
    "basic",
    "basic_name_grid",
    "chunk",
    "DELETE_CUSTOM_ID",
    "delete_button_callback",
    "delete_row",
    "delete_row_multiple_authors",
    "embed_iterator",
    "prettify_date",
    "prettify_index",
    "raise_error",
    # command_hooks.py
    "command_hooks",
    "on_error",
    "on_parser_error",
    # constants.py
    "constants",
    "AMARANTH_PINK",
    "embed_colour",
    "FAILED_COLOUR",
    "MAYA_BLUE",
    "PASS_COLOUR",
    "WHITE",
    # dependencies.py
    "dependencies",
    "SessionManager",
    # rest.py
    "rest",
    "AIOHTTPStatusHandler",
    "ClientCredentialsOauth2",
    "FetchedResource",
    # ytdl.py
    "ytdl",
    "YoutubeDownloader",
]

from . import basic
from . import command_hooks
from . import constants
from . import dependencies
from . import rest
from . import ytdl
from .basic import *
from .command_hooks import *
from .constants import *
from .dependencies import *
from .rest import *
from .ytdl import *
