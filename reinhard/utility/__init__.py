# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2023, Faster Speeding
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
    "AIOHTTPStatusHandler",
    "AMARANTH_PINK",
    "ClientCredentialsOauth2",
    "DELETE_CUSTOM_ID",
    "DELETE_EMOJI",
    "FAILED_COLOUR",
    "FILE_EMOJI",
    "FetchedResource",
    "MAYA_BLUE",
    "PASS_COLOUR",
    "SessionManager",
    "WHITE",
    "YoutubeDownloader",
    "add_file_button",
    "basic",
    "basic_name_grid",
    "chunk",
    "command_hooks",
    "constants",
    "delete_row",
    "delete_row_from_authors",
    "dependencies",
    "embed_colour",
    "embed_iterator",
    "make_delete_id",
    "make_paginator",
    "on_error",
    "on_parser_error",
    "prettify_date",
    "prettify_index",
    "raise_error",
    "rest",
    "ytdl",
]

from . import basic
from . import command_hooks
from . import constants
from . import dependencies
from . import rest
from . import ytdl
from .basic import add_file_button
from .basic import basic_name_grid
from .basic import chunk
from .basic import delete_row
from .basic import delete_row_from_authors
from .basic import embed_iterator
from .basic import make_paginator
from .basic import prettify_date
from .basic import prettify_index
from .basic import raise_error
from .command_hooks import on_error
from .command_hooks import on_parser_error
from .constants import AMARANTH_PINK
from .constants import DELETE_CUSTOM_ID
from .constants import DELETE_EMOJI
from .constants import FAILED_COLOUR
from .constants import FILE_EMOJI
from .constants import MAYA_BLUE
from .constants import PASS_COLOUR
from .constants import WHITE
from .constants import embed_colour
from .constants import make_delete_id
from .dependencies import SessionManager
from .rest import AIOHTTPStatusHandler
from .rest import ClientCredentialsOauth2
from .rest import FetchedResource
from .ytdl import YoutubeDownloader
