# -*- coding: utf-8 -*-
# cython: language_level=3
# BSD 3-Clause License
#
# Copyright (c) 2020-2022, Faster Speeding
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

import pathlib

import nox

nox.options.sessions = ["reformat", "lint", "spell-check", "type-check", "test"]  # type: ignore
GENERAL_TARGETS = ["./noxfile.py", "./reinhard", "./tests"]
PYTHON_VERSIONS = ["3.9", "3.10"]  # TODO: @nox.session(python=["3.6", "3.7", "3.8"])?


def _try_find_option(session: nox.Session, name: str, *other_names: str, when_empty: str | None = None) -> str | None:
    args_iter = iter(session.posargs)
    names = {name, *other_names}

    for arg in args_iter:
        if arg in names:
            return next(args_iter, when_empty)


def install_requirements(session: nox.Session, *other_requirements: str, include_standard: bool = False) -> None:
    session.install("--upgrade", "wheel")

    if include_standard:
        other_requirements = ("-r", "requirements.txt", *other_requirements)

    session.install("--upgrade", "-r", "dev-requirements.txt", *other_requirements)


@nox.session(venv_backend="none")
def cleanup(session: nox.Session) -> None:
    import shutil

    for raw_path in ["./.nox", "./.pytest_cache", "./coverage_html"]:
        path = pathlib.Path(raw_path)
        try:
            shutil.rmtree(str(path.absolute()))

        except Exception as exc:
            session.warn(f"[ FAIL ] Failed to remove '{raw_path}': {exc!s}")

        else:
            session.log(f"[  OK  ] Removed '{raw_path}'")

    # Remove individual files
    for raw_path in ["./.coverage", "./coverage_html.xml"]:
        path = pathlib.Path(raw_path)
        try:
            path.unlink()

        except Exception as exc:
            session.warn(f"[ FAIL ] Failed to remove '{raw_path}': {exc!s}")

        else:
            session.log(f"[  OK  ] Removed '{raw_path}'")


@nox.session(reuse_venv=True)
def lint(session: nox.Session) -> None:
    install_requirements(session, include_standard=True)
    session.run("flake8", *GENERAL_TARGETS)


@nox.session(reuse_venv=True, name="spell-check")
def spell_check(session: nox.Session) -> None:
    install_requirements(session)  # include_standard_requirements=False
    session.run(
        "codespell",
        *GENERAL_TARGETS,
        ".flake8",
        ".gitignore",
        "LICENSE",
        "pyproject.toml",
        "README.md",
        "./github",
        "--ignore-words-list",
        "nd",
    )


@nox.session(reuse_venv=True)
def reformat(session: nox.Session) -> None:
    install_requirements(session)  # include_standard_requirements=False
    session.run("black", *GENERAL_TARGETS)
    session.run("isort", *GENERAL_TARGETS)


@nox.session(reuse_venv=True)
def test(session: nox.Session) -> None:
    install_requirements(session, include_standard=True)
    session.run("pytest")


@nox.session(name="test-coverage", reuse_venv=True)
def test_coverage(session: nox.Session) -> None:
    install_requirements(session, include_standard=True)
    session.run("pytest", "--cov=reinhard", "--cov-report", "html:coverage_html", "--cov-report", "xml:coverage.xml")


@nox.session(name="type-check", reuse_venv=True)
def type_check(session: nox.Session) -> None:
    install_requirements(session, "-r", "requirements.txt", "-r", "stub-requirements.txt", "-r", "nox-requirements.txt")

    if _try_find_option(session, "--force-env", when_empty="True"):
        session.env["PYRIGHT_PYTHON_GLOBAL_NODE"] = "off"

    session.run("python", "-m", "pyright", "--version")
    session.run("python", "-m", "pyright")
