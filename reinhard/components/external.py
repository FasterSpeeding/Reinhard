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
"""Commands used to interact with external APIs."""
from __future__ import annotations

__all__: list[str] = ["external_component", "load_external"]

import collections.abc as collections
import logging
import time
import typing
import urllib.parse

import aiohttp
import hikari
import tanjun
import yuyo

from .. import config as config_
from .. import utility

YOUTUBE_TYPES = {
    "youtube#video": ("videoId", "https://youtube.com/watch?v="),
    "youtube#channel": ("channelId", "https://www.youtube.com/channel/"),
    "youtube#playlist": ("playlistId", "https://www.youtube.com/playlist?list="),
}
CONTENT_TYPE_HEADER = "Content-Type"
RETRY_AFTER_HEADER = "Retry-After"
USER_AGENT_HEADER = "User-Agent"
_LOGGER = logging.getLogger("hikari.reinhard.external")
SPOTIFY_RESOURCE_TYPES = ("track", "album", "artist", "playlist")


class YoutubePaginator(collections.AsyncIterator[tuple[str, hikari.UndefinedType]]):
    __slots__ = ("_session", "_buffer", "_next_page_token", "_parameters")

    def __init__(
        self,
        session: aiohttp.ClientSession,
        parameters: dict[str, str | int],
    ) -> None:
        self._session = session
        self._buffer: list[dict[str, typing.Any]] = []
        self._next_page_token: str | None = ""
        self._parameters = parameters

    def __aiter__(self) -> YoutubePaginator:
        return self

    async def __anext__(self) -> tuple[str, hikari.UndefinedType]:
        if not self._next_page_token and self._next_page_token is not None:
            retry = yuyo.Backoff(max_retries=5)
            error_manager = utility.AIOHTTPStatusHandler(retry, break_on=(404,))

            parameters = self._parameters.copy()
            parameters["pageToken"] = self._next_page_token
            async for _ in retry:
                with error_manager:
                    response = await self._session.get(
                        "https://www.googleapis.com/youtube/v3/search", params=parameters
                    )
                    response.raise_for_status()
                    break

            else:
                if retry.is_depleted:
                    raise RuntimeError(f"Youtube request passed max_retries with params:\n {parameters!r}") from None

                raise StopAsyncIteration from None

            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
                raise exc

            self._next_page_token = data.get("nextPageToken")
            # TODO: only store urls?
            self._buffer.extend(data["items"])

        if not self._buffer:
            raise StopAsyncIteration

        while self._buffer:
            page = self._buffer.pop(0)
            if response_type := YOUTUBE_TYPES.get(page["id"]["kind"].lower()):
                return f"{response_type[1]}{page['id'][response_type[0]]}", hikari.UNDEFINED

        raise RuntimeError(f"Got unexpected 'kind' from youtube {page['id']['kind']}")  # type: ignore


class SpotifyPaginator(collections.AsyncIterator[tuple[str, hikari.UndefinedType]]):
    __slots__ = (
        "_acquire_authorization",
        "_session",
        "_buffer",
        "_offset",
        "_parameters",
    )

    _limit: typing.Final[int] = 50

    def __init__(
        self,
        acquire_authorization: collections.Callable[[aiohttp.ClientSession], collections.Awaitable[str]],
        session: aiohttp.ClientSession,
        parameters: dict[str, str | int],
    ) -> None:
        self._acquire_authorization = acquire_authorization
        self._session = session
        self._buffer: list[dict[str, typing.Any]] = []
        self._offset: int | None = 0
        self._parameters = parameters

    def __aiter__(self) -> SpotifyPaginator:
        return self

    async def __anext__(self) -> tuple[str, hikari.UndefinedType]:
        if not self._buffer and self._offset is not None:
            retry = yuyo.Backoff(max_retries=5)
            resource_type = self._parameters["type"]
            assert isinstance(resource_type, str)
            error_manager = utility.AIOHTTPStatusHandler(retry, on_404=utility.raise_error(None, StopAsyncIteration))
            parameters = self._parameters.copy()
            parameters["offset"] = self._offset
            self._offset += self._limit

            async for _ in retry:
                with error_manager:
                    response = await self._session.get(
                        "https://api.spotify.com/v1/search",
                        params=parameters,
                        headers={"Authorization": await self._acquire_authorization(self._session)},
                    )
                    response.raise_for_status()
                    break

            else:
                raise tanjun.CommandError(f"Couldn't fetch {resource_type} in time") from None

            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
                raise exc

            # TODO: only store urls?
            self._buffer.extend(data[resource_type + "s"]["items"])

        if not self._buffer:
            self._offset = None
            raise StopAsyncIteration

        return (self._buffer.pop(0)["external_urls"]["spotify"], hikari.UNDEFINED)


external_component = tanjun.Component(strict=True)


@external_component.with_slash_command
@tanjun.with_str_slash_option("query", "Query string (e.g. name) to search a song by.")
@tanjun.as_slash_command("lyrics", "Get a song's lyrics.")
async def lyrics_command(
    ctx: tanjun.abc.Context,
    query: str,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    component_client: yuyo.ComponentClient = tanjun.injected(type=yuyo.ComponentClient),
) -> None:
    """Get a song's lyrics.

    Arguments:
        * query: Greedy query string (e.g. name) to search a song by.
    """
    retry = yuyo.Backoff(max_retries=5)
    error_manager = utility.AIOHTTPStatusHandler(retry, on_404=f"Couldn't find the lyrics for `{query[:1960]}`")
    async for _ in retry:
        with error_manager:
            response = await session.get("https://evan.lol/lyrics/search/top", params={"q": query})
            response.raise_for_status()
            break

    else:
        raise tanjun.CommandError("Couldn't get the lyrics in time") from None

    try:
        data = await response.json()
    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
        hikari_error_manager = utility.HikariErrorManager(retry, break_on=(hikari.NotFoundError, hikari.ForbiddenError))
        await hikari_error_manager.try_respond(ctx, content="Invalid data returned by server.")

        _LOGGER.exception(
            "Received unexpected data from lyrics.tsu.sh of type %s\n %s",
            response.headers.get(CONTENT_TYPE_HEADER, "unknown"),
            await response.text(),
            exc_info=exc,
        )
        raise tanjun.CommandError("Failed to receive lyrics")

    icon: str | None = None
    if "album" in data and (icon_data := data["album"]["icon"]):
        icon = icon_data.get("url")

    title = data["name"]

    if artists := data["artists"]:
        title += " - " + " | ".join((a["name"] for a in artists))

    pages = (
        (
            hikari.UNDEFINED,
            hikari.Embed(description=page, colour=utility.embed_colour())
            .set_footer(text=f"Page {index + 1}")
            .set_author(icon=icon, name=title),
        )
        for page, index in yuyo.sync_paginate_string(iter(data["lyrics"].splitlines() or ["..."]))
    )
    response_paginator = yuyo.ComponentPaginator(
        pages,
        authors=(ctx.author.id,),
        triggers=(
            yuyo.pagination.LEFT_DOUBLE_TRIANGLE,
            yuyo.pagination.LEFT_TRIANGLE,
            yuyo.pagination.STOP_SQUARE,
            yuyo.pagination.RIGHT_TRIANGLE,
            yuyo.pagination.RIGHT_DOUBLE_TRIANGLE,
        ),
    )
    first_response = await response_paginator.get_next_entry()
    assert first_response
    content, embed = first_response
    message = await ctx.respond(content=content, embed=embed, component=response_paginator, ensure_result=True)
    component_client.add_executor(message, response_paginator)


@external_component.with_slash_command
@tanjun.with_bool_slash_option(
    "safe_search",
    "Whether safe search should be enabled or not. The default for this is based on the current channel.",
    default=None,
)
@tanjun.with_str_slash_option(
    "order",
    "The order to return results in. Defaults to relevance.",
    choices=("date", "relevance", "title", "videoCount", "viewCount"),
    default="relevance",
)
@tanjun.with_str_slash_option(
    "language", "The ISO 639-1 two letter identifier of the language to limit search to.", default=None
)
@tanjun.with_str_slash_option("region", "The ISO 3166-1 code of the region to search for results in.", default=None)
# TODO: should different resource types be split between different sub commands?
@tanjun.with_str_slash_option(
    "resource_type",
    "The type of resource to search for. Defaults to video.",
    choices=("channel", "playlist", "video"),
    default="video",
)
@tanjun.with_str_slash_option("query", "Query string to search for a resource by.")
@tanjun.as_slash_command("youtube", "Search for a resource on youtube.")
async def youtube_command(
    ctx: tanjun.abc.Context,
    query: str,
    resource_type: str,
    region: str | None,
    language: str | None,
    order: str,
    safe_search: bool | None,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    tokens: config_.Tokens = tanjun.injected(type=config_.Tokens),
    component_client: yuyo.ComponentClient = tanjun.injected(type=yuyo.ComponentClient),
) -> None:
    """Search for a resource on youtube.

    Arguments:
        * query: Greedy query string to search for a resource by.

    Options:
        * safe search (--safe, -s, --safe-search): whether safe search should be enabled or not.
            By default this will be decided based on the current channel's nsfw status and this cannot be set to
            `false` for a channel that's not nsfw.
        * order (-o, --order): The order to return results in.
            This can be one of "date", "relevance", "title", "videoCount" or "viewCount" and defaults to "relevance".
        * language (-l, --language): The ISO 639-1 two letter identifier of the language to limit search to.
        * region (-r, --region): The ISO 3166-1 code of the region to search for results in.
        * resource type (--type, -t): The type of resource to search for.
            This can be one of "channel", "playlist" or "video" and defaults to "video".
    """
    assert tokens.google is not None
    if safe_search is not False:
        channel: hikari.PartialChannel | None
        if ctx.cache and (channel := ctx.cache.get_guild_channel(ctx.channel_id)):
            channel_is_nsfw = channel.is_nsfw

        else:
            # TODO: handle retires
            channel = await ctx.rest.fetch_channel(ctx.channel_id)
            channel_is_nsfw = channel.is_nsfw if isinstance(channel, hikari.GuildChannel) else False

        if safe_search is None:
            safe_search = not channel_is_nsfw

        elif not safe_search and not channel_is_nsfw:
            raise tanjun.CommandError("Cannot disable safe search in a sfw channel")

    parameters: dict[str, str | int] = {
        "key": tokens.google,
        "maxResults": 50,
        "order": order,
        "part": "snippet",
        "q": query,
        "safeSearch": "strict" if safe_search else "none",  # TODO: channel.nsfw
        "type": resource_type,
    }

    if region is not None:
        parameters["regionCode"] = region

    if language is not None:
        parameters["relevanceLanguage"] = language

    response_paginator = yuyo.ComponentPaginator(YoutubePaginator(session, parameters), authors=[ctx.author.id])
    try:
        if not (first_response := await response_paginator.get_next_entry()):
            # data["pageInfo"]["totalResults"] will not reliably be `0` when no data is returned and they don't use 404
            # for that so we'll just check to see if nothing is being returned.
            raise tanjun.CommandError(f"Couldn't find `{query}`.")

    except RuntimeError as exc:
        raise tanjun.CommandError(str(exc)) from None

    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
        _LOGGER.exception("Youtube returned invalid data", exc_info=exc)
        error_manager = utility.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
        await error_manager.try_respond(ctx, content="Youtube returned invalid data.")
        raise

    else:
        content, embed = first_response
        message = await ctx.respond(content, embed=embed, component=response_paginator, ensure_result=True)
        component_client.add_executor(message, response_paginator)


@youtube_command.with_check
def _youtube_token_check(_: tanjun.abc.Context, tokens: config_.Tokens = tanjun.injected(type=config_.Tokens)) -> bool:
    return tokens.google is not None


# This API is currently dead (always returning 5xxs)
# @external_component.with_message_command
# @utility.with_parameter_doc("--source | -s", "The optional argument of a show's title.")
# @utility.with_command_doc("Get a random cute anime image.")
# @tanjun.with_option("source", "--source", "-s", default=None)
# @tanjun.with_parser
# @tanjun.as_message_command("moe")  # TODO: https://lewd.bowsette.pictures/api/request
async def moe_command(
    ctx: tanjun.abc.Context,
    source: str | None = None,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
) -> None:
    params = {}
    if source is not None:
        params["source"] = source

    retry = yuyo.Backoff(max_retries=5)
    error_manager = utility.AIOHTTPStatusHandler(
        retry, on_404=f"Couldn't find source `{source[:1970]}`" if source is not None else "couldn't access api"
    )
    async for _ in retry:
        with error_manager:
            response = await session.get("http://api.cutegirls.moe/json", params=params)
            response.raise_for_status()
            break

    else:
        raise tanjun.CommandError("Couldn't get an image in time") from None

    hikari_error_manager = utility.HikariErrorManager(retry, break_on=(hikari.NotFoundError, hikari.ForbiddenError))

    try:
        data = (await response.json())["data"]
    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, LookupError, ValueError) as exc:
        await hikari_error_manager.try_respond(ctx, content="Image API returned invalid data.")
        raise exc

    await hikari_error_manager.try_respond(ctx, content=f"{data['image']} (source {data.get('source') or 'unknown'})")


async def query_nekos_life(
    endpoint: str,
    response_key: str,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
) -> str:
    # TODO: retries
    response = await session.get(url="https://nekos.life/api/v2" + endpoint)

    try:
        data = await response.json()
    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError):
        data = None

    # Ok so here's a fun fact, whoever designed this api seems to have decided that it'd be appropriate to
    # return error status codes in the json body under the "msg" key while leaving the response as a 200 OK
    # (e.g. a 200 with the json payload '{"msg": "404"}') so here we have to try to get the response code from
    # the json payload (if available) and then fall back to the actual status code.
    # We cannot consistently rely on this behaviour either as any internal server errors will likely return an
    # actual 5xx response.
    try:
        status_code = int(data["msg"])  # type: ignore
    except (LookupError, ValueError, TypeError):
        status_code = response.status

    if status_code == 404:
        raise tanjun.CommandError("Query not found.") from None

    if status_code >= 500 or data is None or response_key not in data:
        raise tanjun.CommandError(
            "Unable to fetch image at the moment due to server error or malformed response."
        ) from None

    if status_code >= 300:
        raise tanjun.CommandError(f"Unable to fetch image due to unexpected error {status_code}") from None

    result = data[response_key]
    assert isinstance(result, str)
    return result


def _build_spotify_auth(
    config: config_.Tokens = tanjun.injected(type=config_.Tokens),
) -> utility.ClientCredentialsOauth2:
    if not config.spotify_id or not config.spotify_secret:
        raise tanjun.MissingDependencyError("Missing spotify secret and/or client id")

    return utility.ClientCredentialsOauth2(
        "https://accounts.spotify.com/api/token", config.spotify_id, config.spotify_secret
    )


# TODO: add valid options for Options maybe?
@external_component.with_slash_command
@tanjun.with_str_slash_option(
    "resource_type",
    "Type of resource to search for. Defaults to track.",
    choices=("track", "album", "artist", "playlist"),
    default="track",
)
@tanjun.with_str_slash_option("query", "The string query to search by.")
@tanjun.as_slash_command("spotify", "Search for a resource on spotify.")
async def spotify_command(
    ctx: tanjun.abc.Context,
    query: str,
    resource_type: str,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    component_client: yuyo.ComponentClient = tanjun.injected(type=yuyo.ComponentClient),
    spotify_auth: utility.ClientCredentialsOauth2 = tanjun.injected(
        callback=tanjun.cache_callback(_build_spotify_auth)
    ),
) -> None:
    """Search for a resource on spotify.

    Arguments:
        * query: The greedy string query to search by.

    Options:
        * resource_type:
            Type of resource to search for. This can be one of "track", "album", "artist" or "playlist" and defaults
            to track.
    """
    resource_type = resource_type.lower()
    if resource_type not in SPOTIFY_RESOURCE_TYPES:
        raise tanjun.CommandError(f"{resource_type!r} is not a valid resource type")

    response_paginator = yuyo.ComponentPaginator(
        SpotifyPaginator(spotify_auth.acquire_token, session, {"query": query, "type": resource_type}),
        authors=[ctx.author.id],
    )

    try:
        if not (first_response := await response_paginator.get_next_entry()):
            raise tanjun.CommandError(f"Couldn't find {resource_type}") from None

    except RuntimeError as exc:
        raise tanjun.CommandError(str(exc)) from None

    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
        _LOGGER.exception("Spotify returned invalid data", exc_info=exc)
        error_manager = utility.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
        await error_manager.try_respond(ctx, content="Spotify returned invalid data.")
        raise

    else:
        content, embed = first_response
        message = await ctx.respond(content, embed=embed, component=response_paginator, ensure_result=True)
        component_client.add_executor(message, response_paginator)


@external_component.with_message_command
@tanjun.with_owner_check
@tanjun.with_argument("url", converters=urllib.parse.ParseResult)
@tanjun.with_parser
@tanjun.as_message_command("ytdl")
async def ytdl_command(
    ctx: tanjun.abc.Context,
    url: urllib.parse.ParseResult,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    config: config_.PTFConfig = tanjun.injected(type=config_.PTFConfig),
    ytdl_client: utility.YoutubeDownloader = tanjun.injected(
        callback=tanjun.cache_callback(utility.YoutubeDownloader.spawn)
    ),
) -> None:
    auth = aiohttp.BasicAuth(config.username, config.password)

    # Download video
    path, _ = await ytdl_client.download(url.geturl())
    filename = urllib.parse.quote(path.name)

    try:
        # Create Message
        response = await session.post(
            config.message_service + "/messages",
            json={"title": f"Reinhard upload {time.time()}"},
            auth=auth,
        )
        response.raise_for_status()
        message_id = (await response.json())["id"]

        # Create message link
        response = await session.post(f"{config.auth_service}/messages/{message_id}/links", json={}, auth=auth)
        response.raise_for_status()
        link_token = (await response.json())["token"]

        with path.open("rb") as file:
            response = await session.put(
                f"{config.file_service}/messages/{message_id}/files/{filename}", auth=auth, data=file
            )

        response.raise_for_status()
        file_path = (await response.json())["shareable_link"].format(link_token=link_token)

    finally:
        path.unlink(missing_ok=True)

    await ctx.respond(content=file_path)


@tanjun.as_loader
def load_external(cli: tanjun.abc.Client, /) -> None:
    cli.add_component(external_component.copy())
