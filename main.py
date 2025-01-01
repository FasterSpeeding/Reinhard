# -*- coding: utf-8 -*-
# BSD 3-Clause License
#
# Copyright (c) 2020-2025, Faster Speeding
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

if __name__ == "__main__":
    try:
        import pyjion  # type: ignore

        pyjion.enable()  # type: ignore
        pyjion.config(threshold=30, pgc=True, level=2, debug=False, graph=False)  # type: ignore
        print("Running with pyjion")

    except ImportError:
        print("Running without pyjion")
        pass

    try:
        import uvloop  # type: ignore

        print("Running with uvloop")
        uvloop.install()  # type: ignore

    except ImportError:
        print("Running with standard asyncio loop")

    try:
        import alluka_rust

        import alluka
        patched = alluka.Client is alluka_rust.Client

    except ImportError:
        patched = False

    print(f"Running with {'Rust' if patched else 'Python'} Alluka implementation")

    import reinhard.cli
    reinhard.cli.main()
