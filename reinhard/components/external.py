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
"""Commands used to interact with external APIs."""
from __future__ import annotations

__all__: list[str] = ["load_external"]

import datetime
import enum
import hashlib
import logging
import time
import typing
import urllib.parse
from collections import abc as collections
from typing import Annotated

import aiohttp
import alluka
import hikari
import tanjun
import yuyo
from tanchan import doc_parse
from tanjun.annotations import Bool
from tanjun.annotations import Flag
from tanjun.annotations import Greedy
from tanjun.annotations import Str
from tanjun.annotations import str_field

from .. import config as config_
from .. import utility

if typing.TYPE_CHECKING:
    from typing_extensions import Self

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
    __slots__ = ("_author", "_session", "_buffer", "_next_page_token", "_parameters")

    def __init__(
        self, author: hikari.Snowflakeish, session: aiohttp.ClientSession, parameters: dict[str, str | int]
    ) -> None:
        self._author = author
        self._session = session
        self._buffer: list[dict[str, typing.Any]] = []
        self._next_page_token: str | None = ""
        self._parameters = parameters

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> tuple[str, hikari.UndefinedType]:
        if not self._next_page_token and self._next_page_token is not None:
            retry = yuyo.Backoff(max_retries=5)
            error_manager = utility.AIOHTTPStatusHandler(self._author, retry, break_on=[404])

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
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError):
                raise

            self._next_page_token = data.get("nextPageToken")
            # TODO: only store urls?
            self._buffer.extend(data["items"])

        if not self._buffer:
            raise StopAsyncIteration

        while self._buffer:
            page = self._buffer.pop(0)
            if response_type := YOUTUBE_TYPES.get(page["id"]["kind"].lower()):
                return f"{response_type[1]}{page['id'][response_type[0]]}", hikari.UNDEFINED

        kind: str = page["id"]["kind"]  # pyright: ignore[reportUnboundVariable]
        raise RuntimeError(f"Got unexpected 'kind' from youtube {kind}")


class SpotifyPaginator(collections.AsyncIterator[tuple[str, hikari.UndefinedType]]):
    __slots__ = ("_acquire_authorization", "_author", "_session", "_buffer", "_offset", "_parameters")

    _limit: typing.Final[int] = 50

    def __init__(
        self,
        author: hikari.Snowflakeish,
        acquire_authorization: collections.Callable[[aiohttp.ClientSession], collections.Awaitable[str]],
        session: aiohttp.ClientSession,
        parameters: dict[str, str | int],
    ) -> None:
        self._acquire_authorization = acquire_authorization
        self._author = author
        self._session = session
        self._buffer: list[dict[str, typing.Any]] = []
        self._offset: int | None = 0
        self._parameters = parameters

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> tuple[str, hikari.UndefinedType]:
        if not self._buffer and self._offset is not None:
            retry = yuyo.Backoff(max_retries=5)
            resource_type = self._parameters["type"]
            assert isinstance(resource_type, str)
            error_manager = utility.AIOHTTPStatusHandler(
                self._author, retry, on_404=utility.raise_error(None, StopAsyncIteration)
            )
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
                raise tanjun.CommandError(
                    f"Couldn't fetch {resource_type} in time", component=utility.delete_row_from_authors(self._author)
                ) from None

            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError):
                raise

            # TODO: only store urls?
            self._buffer.extend(data[resource_type + "s"]["items"])

        if not self._buffer:
            self._offset = None
            raise StopAsyncIteration

        return (self._buffer.pop(0)["external_urls"]["spotify"], hikari.UNDEFINED)


class YtOrder(str, enum.Enum):
    Relevance = "relevance"
    Date = "date"
    Title = "title"
    Video_count = "videoCount"
    View_count = "viewCount"


class YtResource(str, enum.Enum):
    Video = "video"
    Channel = "channel"
    Playlist = "playlist"


def yt_check(_: tanjun.abc.Context, tokens: alluka.Injected[config_.Tokens]) -> bool:
    return tokens.google is not None


# TODO: should different resource types be split between different sub commands?
@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.with_check(yt_check, follow_wrapped=True)
@tanjun.as_message_command("youtube", "yt")
@doc_parse.as_slash_command()
async def youtube(
    ctx: tanjun.abc.Context,
    session: alluka.Injected[aiohttp.ClientSession],
    tokens: alluka.Injected[config_.Tokens],
    component_client: alluka.Injected[yuyo.ComponentClient],
    query: Annotated[Str, Greedy()],
    resource_type: YtResource = str_field(
        choices=YtResource.__members__,
        converters=YtResource,  # pyright: ignore[reportGeneralTypeIssues]
        slash_name="type",
        message_names=["--type", "-t"],
        default=YtResource.Video,
    ),
    region: Annotated[Str | None, Flag(aliases=["-r"])] = None,
    language: Annotated[Str | None, Flag(aliases=["-l"])] = None,
    order: YtOrder = str_field(
        choices=YtOrder.__members__,
        converters=YtOrder,  # pyright: ignore[reportGeneralTypeIssues]
        default=YtOrder.Relevance,
    ),
    safe_search: Bool | None = None,
) -> None:
    """Search for a resource on youtube.

    Parameters
    ----------
    query
        Query string to search for a resource by.
    resource_type
        The type of resource to search for. Defaults to video.
    region
        The ISO 3166-1 code of the region to search for results in.
    language
        The ISO 639-1 two letter identifier of the language to limit search to.
    order
        The order to return results in. Defaults to relevance.
    safe_search
        Whether safe search should be enabled or not.
        The default for this is based on the current channel.
    """
    assert tokens.google is not None
    if safe_search is not False:
        channel = None
        if ctx.cache:
            channel = ctx.cache.get_guild_channel(ctx.channel_id) or ctx.cache.get_thread(ctx.channel_id)

        # TODO: handle retires
        channel = channel or await ctx.rest.fetch_channel(ctx.channel_id)
        if isinstance(channel, hikari.PermissibleGuildChannel):
            channel_is_nsfw = channel.is_nsfw

        elif isinstance(channel, hikari.GuildThreadChannel):
            parent_channel = ctx.cache.get_guild_channel(channel.id) if ctx.cache else None
            parent_channel = parent_channel or await ctx.rest.fetch_channel(channel.parent_id)
            assert isinstance(parent_channel, hikari.PermissibleGuildChannel)
            channel_is_nsfw = parent_channel.is_nsfw

        else:
            _LOGGER.warning("Unexpected channel type in youtube of %r", type(channel))
            channel_is_nsfw = False

        if safe_search is None:
            safe_search = not channel_is_nsfw

        elif not safe_search and not channel_is_nsfw:
            raise tanjun.CommandError("Cannot disable safe search in a sfw channel", component=utility.delete_row(ctx))

    parameters: dict[str, str | int] = {
        "key": tokens.google,
        "maxResults": 50,
        "order": order.value,
        "part": "snippet",
        "q": query,
        "safeSearch": "strict" if safe_search else "none",
        "type": resource_type.value,
    }

    if region is not None:
        parameters["regionCode"] = region

    if language is not None:
        parameters["relevanceLanguage"] = language

    paginator = utility.make_paginator(YoutubePaginator(ctx.author.id, session, parameters), author=ctx.author)
    try:
        first_response = await paginator.get_next_entry()

    except RuntimeError as exc:
        raise tanjun.CommandError(str(exc), component=utility.delete_row(ctx)) from None

    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
        _LOGGER.exception("Youtube returned invalid data", exc_info=exc)
        await ctx.respond(content="Youtube returned invalid data.", component=utility.delete_row(ctx))
        raise

    else:
        if not first_response:
            # data["pageInfo"]["totalResults"] will not reliably be `0` when no data is returned and they don't use 404
            # for that so we'll just check to see if nothing is being returned.
            raise tanjun.CommandError(f"Couldn't find `{query}`.", component=utility.delete_row(ctx))

        message = await ctx.respond(**first_response.to_kwargs(), components=paginator.rows, ensure_result=True)
        component_client.register_executor(paginator, message=message)


# This API is currently dead (always returning 5xxs)
# @utility.with_parameter_doc("--source | -s", "The optional argument of a show's title.")
# @utility.with_command_doc("Get a random cute anime image.")
# @tanjun.with_option("source", "--source", "-s", default=None)
# @tanjun.as_message_command("moe")  # TODO: https://lewd.bowsette.pictures/api/request
async def moe_command(
    ctx: tanjun.abc.Context, session: alluka.Injected[aiohttp.ClientSession], source: str | None = None
) -> None:
    params = {}
    if source is not None:
        params["source"] = source

    retry = yuyo.Backoff(max_retries=5)
    error_manager = utility.AIOHTTPStatusHandler(
        ctx.author.id,
        retry,
        on_404=f"Couldn't find source `{source[:1970]}`" if source is not None else "couldn't access api",
    )
    async for _ in retry:
        with error_manager:
            response = await session.get("http://api.cutegirls.moe/json", params=params)
            response.raise_for_status()
            break

    else:
        raise tanjun.CommandError("Couldn't get an image in time", component=utility.delete_row(ctx)) from None

    try:
        data = (await response.json())["data"]
    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, LookupError, ValueError):
        await ctx.respond(content="Image API returned invalid data.", component=utility.delete_row(ctx))
        raise

    await ctx.respond(
        content=f"{data['image']} (source {data.get('source') or 'unknown'})", component=utility.delete_row(ctx)
    )


async def query_nekos_life(
    ctx: tanjun.abc.Context, endpoint: str, response_key: str, session: alluka.Injected[aiohttp.ClientSession]
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
        raise tanjun.CommandError("Query not found.", component=utility.delete_row(ctx)) from None

    if status_code >= 500 or data is None or response_key not in data:
        raise tanjun.CommandError(
            "Unable to fetch image at the moment due to server error or malformed response.",
            component=utility.delete_row(ctx),
        ) from None

    if status_code >= 300:
        raise tanjun.CommandError(
            f"Unable to fetch image due to unexpected error {status_code}", component=utility.delete_row(ctx)
        ) from None

    result = data[response_key]
    assert isinstance(result, str)
    return result


def _build_spotify_auth(
    config: alluka.Injected[config_.Tokens], ctx: alluka.Injected[tanjun.abc.Context]
) -> utility.ClientCredentialsOauth2:
    if not config.spotify_id or not config.spotify_secret:
        raise tanjun.MissingDependencyError("Missing spotify secret and/or client id", None)

    return utility.ClientCredentialsOauth2(
        ctx.author.id, "https://accounts.spotify.com/api/token", config.spotify_id, config.spotify_secret
    )


class SpotifyType(str, enum.Enum):
    Track = "track"
    Album = "album"
    Artist = "artist"
    Playlist = "playlist"


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("spotify")
@doc_parse.as_slash_command()
async def spotify(
    ctx: tanjun.abc.Context,
    *,
    query: Str,
    session: alluka.Injected[aiohttp.ClientSession],
    component_client: alluka.Injected[yuyo.ComponentClient],
    spotify_auth: Annotated[utility.ClientCredentialsOauth2, tanjun.cached_inject(_build_spotify_auth)],
    resource_type: SpotifyType = str_field(
        converters=SpotifyType,  # pyright: ignore[reportGeneralTypeIssues]
        choices=SpotifyType.__members__,
        default=SpotifyType.Track,
        message_names=["--type", "-t"],
        slash_name="type",
    ),
) -> None:
    """Search for a resource on spotify.

    Parameters
    ----------
    query
        The string query to search by.
    resource_type
        Type of resource to search for. Defaults to track.
    """
    paginator = utility.make_paginator(
        SpotifyPaginator(
            ctx.author.id, spotify_auth.acquire_token, session, {"query": query, "type": resource_type.value}
        ),
        author=ctx.author,
    )

    try:
        first_response = await paginator.get_next_entry()

    except RuntimeError as exc:
        raise tanjun.CommandError(str(exc), component=utility.delete_row(ctx)) from None

    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
        _LOGGER.exception("Spotify returned invalid data", exc_info=exc)
        await ctx.respond(content="Spotify returned invalid data.", component=utility.delete_row(ctx))
        raise

    else:
        if not first_response:
            raise tanjun.CommandError(
                f"Couldn't find {resource_type.value}", component=utility.delete_row(ctx)
            ) from None

        message = await ctx.respond(**first_response.to_kwargs(), components=paginator.rows, ensure_result=True)
        component_client.register_executor(paginator, message=message)


@tanjun.annotations.with_annotated_args
@tanjun.with_owner_check
@tanjun.as_message_command("ytdl")
async def ytdl_command(
    ctx: tanjun.abc.Context,
    *,
    url: urllib.parse.ParseResult = str_field(converters=tanjun.conversion.parse_url),
    session: alluka.Injected[aiohttp.ClientSession],
    config: alluka.Injected[config_.PTFConfig],
    ytdl_client: Annotated[utility.YoutubeDownloader, tanjun.cached_inject(utility.YoutubeDownloader.spawn)],
) -> None:
    auth = aiohttp.BasicAuth(config.username, config.password)

    # Download video
    path, _ = await ytdl_client.download(url.geturl())
    filename = urllib.parse.quote(path.name)

    try:
        # Create Message
        response = await session.post(
            config.message_service + "/messages", json={"title": f"Reinhard upload {time.time()}"}, auth=auth
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


async def _fetch_hashes(session: alluka.Injected[aiohttp.ClientSession]) -> set[str]:
    # Original list.
    response = await session.get("https://cdn.discordapp.com/bad-domains/hashes.json")
    response.raise_for_status()
    # Used by the client, longer list.
    other_response = await session.get("https://cdn.discordapp.com/bad-domains/updated_hashes.json")
    other_response.raise_for_status()
    hashes = set(await response.json())
    hashes.update(await other_response.json())
    return hashes


domain_hashes = tanjun.cached_inject(_fetch_hashes, expire_after=datetime.timedelta(hours=12))


@doc_parse.with_annotated_args(follow_wrapped=True)
@tanjun.as_message_command("check_domain", "check domain")
@doc_parse.as_slash_command()
async def check_domain(
    ctx: tanjun.abc.Context,
    *,
    url: urllib.parse.ParseResult = str_field(converters=tanjun.conversion.parse_url),
    bad_domains: Annotated[set[str], domain_hashes],
) -> None:
    """Check whether a domain is on Discord's "bad" domain list.

    Parameters
    ----------
    url
        The domain to check.
    """
    if url.netloc:
        domain = url.netloc

    else:
        domain = url.path.split("/", 1)[0]

    base_domain = ".".join(domain.rsplit(".", 2)[1:])
    domain_hash = hashlib.sha256(domain.encode("utf-8")).hexdigest()
    if base_domain != domain:
        base_domain_hash = hashlib.sha256(base_domain.encode("utf-8")).hexdigest()
    else:
        base_domain_hash = b"@"  # This will always return False as @ isn't a valid hex char

    if domain_hash in bad_domains or base_domain_hash in bad_domains:
        await ctx.respond(
            content="\N{LARGE RED SQUARE} Domain is on the bad domains list.", component=utility.delete_row(ctx)
        )
    else:
        await ctx.respond(
            content="\N{LARGE YELLOW SQUARE} Domain is not on the bad domains list.", component=utility.delete_row(ctx)
        )


load_external = tanjun.Component(name="external").load_from_scope().make_loader()
