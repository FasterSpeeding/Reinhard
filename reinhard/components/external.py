from __future__ import annotations

__all__: typing.Sequence[str] = ["external_component"]

import asyncio
import datetime
import logging
import time
import typing
import urllib.parse

import aiohttp
import hikari
import sphobjinv  # type: ignore[import]
import tanjun
import yuyo
from hikari import traits

from .. import config as config_
from ..util import basic as basic_util
from ..util import constants
from ..util import help as help_util
from ..util import rest_manager
from ..util import ytdl

_ValueT = typing.TypeVar("_ValueT")

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
HIKARI_IO = "https://hikari-py.github.io/hikari"


class YoutubePaginator(typing.AsyncIterator[typing.Tuple[str, hikari.UndefinedType]]):
    __slots__ = ("_session", "_buffer", "_next_page_token", "_parameters")

    def __init__(
        self,
        session: aiohttp.ClientSession,
        parameters: typing.Dict[str, typing.Union[str, int]],
    ) -> None:
        self._session = session
        self._buffer: typing.List[typing.Dict[str, typing.Any]] = []
        self._next_page_token: typing.Optional[str] = ""
        self._parameters = parameters

    def __aiter__(self) -> YoutubePaginator:
        return self

    async def __anext__(self) -> typing.Tuple[str, hikari.UndefinedType]:
        if not self._next_page_token and self._next_page_token is not None:
            retry = yuyo.Backoff(max_retries=5)
            error_manager = rest_manager.AIOHTTPStatusHandler(retry, break_on=(404,))

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

        raise RuntimeError(f"Got unexpected 'kind' from youtube {page['id']['kind']}")


class SpotifyPaginator(typing.AsyncIterator[typing.Tuple[str, hikari.UndefinedType]]):
    __slots__: typing.Sequence[str] = (
        "_acquire_authorization",
        "_session",
        "_buffer",
        "_offset",
        "_parameters",
    )

    _limit: typing.Final[int] = 50

    def __init__(
        self,
        acquire_authorization: typing.Callable[[aiohttp.ClientSession], typing.Awaitable[str]],
        session: aiohttp.ClientSession,
        parameters: typing.Dict[str, typing.Union[str, int]],
    ) -> None:
        self._acquire_authorization = acquire_authorization
        self._session = session
        self._buffer: typing.List[typing.Dict[str, typing.Any]] = []
        self._offset: typing.Optional[int] = 0
        self._parameters = parameters

    def __aiter__(self) -> SpotifyPaginator:
        return self

    async def __anext__(self) -> typing.Tuple[str, hikari.UndefinedType]:
        if not self._buffer and self._offset is not None:
            retry = yuyo.Backoff(max_retries=5)
            resource_type = self._parameters["type"]
            assert isinstance(resource_type, str)
            error_manager = rest_manager.AIOHTTPStatusHandler(
                retry, on_404=basic_util.raise_error(None, StopAsyncIteration)
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


class ClientCredentialsOauth2:
    __slots__: typing.Sequence[str] = ("_authorization", "_expire_at", "_path", "_prefix", "_token")

    def __init__(self, path: str, client_id: str, client_secret: str, *, prefix: str = "Bearer ") -> None:
        self._authorization = aiohttp.BasicAuth(client_id, client_secret)
        self._expire_at = 0
        self._path = path
        self._prefix = prefix
        self._token: typing.Optional[str] = None

    @property
    def _expired(self) -> bool:
        return time.time() >= self._expire_at

    async def acquire_token(self, session: aiohttp.ClientSession) -> str:
        if self._token and not self._expired:
            return self._token

        response = await session.post(self._path, data={"grant_type": "client_credentials"}, auth=self._authorization)

        if 200 <= response.status < 300:
            try:
                data = await response.json()
                expire = round(time.time()) + data["expires_in"] - 120
                token = data["access_token"]

            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError, KeyError, TypeError) as exc:
                _LOGGER.exception(
                    "Couldn't decode or handle client credentials response received from %s: %r",
                    self._path,
                    await response.text(),
                    exc_info=exc,
                )

            else:
                self._expire_at = expire
                self._token = f"{self._prefix} {token}"
                return self._token

        else:
            _LOGGER.warning(
                "Received %r from %s while trying to authenticate as client credentials",
                response.status,
                self._path,
            )
        raise tanjun.CommandError("Couldn't authenticate")

    @classmethod
    def spotify(cls, config: config_.Tokens = tanjun.injected(type=config_.Tokens)) -> ClientCredentialsOauth2:
        if not config.spotify_id or not config.spotify_secret:
            raise tanjun.MissingDependencyError("Missing spotify secret and/or client id")

        return cls("https://accounts.spotify.com/api/token", config.spotify_id, config.spotify_secret)


class CachedResource(typing.Generic[_ValueT]):
    __slots__: typing.Sequence[str] = (
        "_authorization",
        "_data",
        "_expire_after",
        "_headers",
        "_parse_data",
        "_path",
        "_time",
    )

    def __init__(
        self,
        path: str,
        expire_after: datetime.timedelta,
        parse_data: typing.Callable[[bytes], _ValueT],
        *,
        authorization: typing.Optional[aiohttp.BasicAuth] = None,
        headers: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> None:
        self._authorization = authorization
        self._data: typing.Optional[_ValueT] = None
        self._expire_after = expire_after.total_seconds()
        self._headers = headers
        self._parse_data = parse_data
        self._path = path
        self._time = 0.0

    @property
    def _expired(self) -> bool:
        return time.perf_counter() - self._time >= self._expire_after

    async def acquire_resource(self, session: aiohttp.ClientSession) -> _ValueT:
        if self._data and not self._expired:
            return self._data

        response = await session.get(self._path)
        # TODO: better handling
        response.raise_for_status()
        self._data = self._parse_data(await response.read())
        return self._data


def make_doc_fetcher() -> CachedResource[sphobjinv.Inventory]:
    return CachedResource(HIKARI_IO + "/objects.inv", datetime.timedelta(hours=12), sphobjinv.Inventory)


external_component = tanjun.Component()
help_util.with_docs(
    external_component, "External API commands", "A utility component used for getting data from 3rd party APIs."
)


@external_component.with_message_command
@tanjun.with_greedy_argument("query")
@tanjun.with_parser
@tanjun.as_message_command("lyrics")
async def lyrics_command(
    ctx: tanjun.traits.MessageContext,
    query: str,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    paginator_pool: yuyo.PaginatorPool = tanjun.injected(type=yuyo.PaginatorPool),
    rest_service: traits.RESTAware = tanjun.injected(type=traits.RESTAware),
) -> None:
    """Get a song's lyrics.

    Arguments:
        * query: Greedy query string (e.g. name) to search a song by.
    """
    retry = yuyo.Backoff(max_retries=5)
    error_manager = rest_manager.AIOHTTPStatusHandler(retry, on_404=f"Couldn't find the lyrics for `{query[:1960]}`")
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
        hikari_error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari.NotFoundError, hikari.ForbiddenError)
        )
        await hikari_error_manager.try_respond(ctx, content="Invalid data returned by server.")

        _LOGGER.exception(
            "Received unexpected data from lyrics.tsu.sh of type %s\n %s",
            response.headers.get(CONTENT_TYPE_HEADER, "unknown"),
            await response.text(),
            exc_info=exc,
        )
        raise tanjun.CommandError("Failed to receive lyrics")

    icon: typing.Optional[str] = None
    if "album" in data and (icon_data := data["album"]["icon"]):
        icon = icon_data.get("url")

    title = data["name"]

    if artists := data["artists"]:
        title += " - " + " | ".join((a["name"] for a in artists))

    pages = (
        (
            hikari.UNDEFINED,
            hikari.Embed(description=page, colour=constants.embed_colour())
            .set_footer(text=f"Page {index + 1}")
            .set_author(icon=icon, name=title),
        )
        for page, index in yuyo.string_paginator(iter(data["lyrics"].splitlines() or ["..."]))
    )
    response_paginator = yuyo.Paginator(
        rest_service,
        ctx.channel_id,
        pages,
        authors=(ctx.author.id,),
        triggers=(
            yuyo.paginaton.LEFT_DOUBLE_TRIANGLE,
            yuyo.paginaton.LEFT_TRIANGLE,
            yuyo.paginaton.STOP_SQUARE,
            yuyo.paginaton.RIGHT_TRIANGLE,
            yuyo.paginaton.RIGHT_DOUBLE_TRIANGLE,
        ),
    )
    message = await response_paginator.open()
    paginator_pool.add_paginator(message, response_paginator)


@external_component.with_message_command
@tanjun.with_option("safe_search", "--safe", "-s", "--safe-search", converters=bool, default=None)
@tanjun.with_option("order", "-o", "--order", default="relevance")
@tanjun.with_option("language", "-l", "--language", default=None)
@tanjun.with_option("region", "-r", "--region", default=None)
# TODO: should different resource types be split between different sub commands?
@tanjun.with_option("resource_type", "--type", "-t", default="video")
@tanjun.with_greedy_argument("query")
@tanjun.with_parser
@tanjun.as_message_command("youtube", "yt")
async def youtube_command(
    ctx: tanjun.traits.MessageContext,
    query: str,
    resource_type: str,
    region: typing.Optional[str],
    language: typing.Optional[str],
    order: str,
    safe_search: typing.Optional[bool],
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    tokens: config_.Tokens = tanjun.injected(type=config_.Tokens),
    paginator_pool: yuyo.PaginatorPool = tanjun.injected(type=yuyo.PaginatorPool),
    rest_service: traits.RESTAware = tanjun.injected(type=traits.RESTAware),
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
        channel: typing.Optional[hikari.PartialChannel]
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

    resource_type = resource_type.lower()
    if resource_type not in ("channel", "playlist", "video"):
        raise tanjun.CommandError("Resource type must be one of 'channel', 'playist' or 'video'.")

    parameters: typing.Dict[str, typing.Union[str, int]] = {
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

    response_paginator = yuyo.Paginator(
        rest_service,
        ctx.channel_id,
        YoutubePaginator(session, parameters),
        authors=[ctx.author.id],
    )
    try:
        message = await response_paginator.open()

    except RuntimeError as exc:
        raise tanjun.CommandError(str(exc)) from None

    except ValueError:
        raise tanjun.CommandError(f"Couldn't find `{query}`.") from None
        # data["pageInfo"]["totalResults"] will not reliably be `0` when no data is returned and they don't use 404
        # for that so we'll just check to see if nothing is being returned.

    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
        _LOGGER.exception("Youtube returned invalid data", exc_info=exc)
        error_manager = rest_manager.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
        await error_manager.try_respond(ctx, content="Youtube returned invalid data.")
        raise

    else:
        paginator_pool.add_paginator(message, response_paginator)


@youtube_command.with_check
def _youtube_token_check(
    _: tanjun.traits.MessageContext, tokens: config_.Tokens = tanjun.injected(type=config_.Tokens)
) -> bool:
    return tokens.google is not None


# This API is currently dead (always returning 5xxs)
# @external_component.with_message_command
# @help_util.with_parameter_doc("--source | -s", "The optional argument of a show's title.")
# @help_util.with_command_doc("Get a random cute anime image.")
# @tanjun.with_option("source", "--source", "-s", default=None)
# @tanjun.with_parser
# @tanjun.as_message_command("moe")  # TODO: https://lewd.bowsette.pictures/api/request
async def moe_command(
    ctx: tanjun.traits.MessageContext,
    source: typing.Optional[str] = None,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
) -> None:
    params = {}
    if source is not None:
        params["source"] = source

    retry = yuyo.Backoff(max_retries=5)
    error_manager = rest_manager.AIOHTTPStatusHandler(
        retry, on_404=f"Couldn't find source `{source[:1970]}`" if source is not None else "couldn't access api"
    )
    async for _ in retry:
        with error_manager:
            response = await session.get("http://api.cutegirls.moe/json", params=params)
            response.raise_for_status()
            break

    else:
        raise tanjun.CommandError("Couldn't get an image in time") from None

    hikari_error_manager = rest_manager.HikariErrorManager(
        retry, break_on=(hikari.NotFoundError, hikari.ForbiddenError)
    )

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
        status_code = int(data["msg"])
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


# TODO: add valid options for Options maybe?
@external_component.with_message_command
@tanjun.with_option("resource_type", "--type", "-t", default="track")
@tanjun.with_greedy_argument("query")
@tanjun.with_parser
@tanjun.as_message_command("spotify")
async def spotify_command(
    ctx: tanjun.traits.MessageContext,
    query: str,
    resource_type: str,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    paginator_pool: yuyo.PaginatorPool = tanjun.injected(type=yuyo.PaginatorPool),
    spotify_auth: ClientCredentialsOauth2 = tanjun.injected(
        callback=tanjun.cache_callback(ClientCredentialsOauth2.spotify)
    ),
    rest_service: traits.RESTAware = tanjun.injected(type=traits.RESTAware),
) -> None:
    """Search for a resource on spotify.

    Arguments:
        * query: The greedy string query to search by.

    Options:
        * resource type (--type, -t):
            Type of resource to search for. This can be one of "track", "album", "artist" or "playlist" and defaults
            to track.
    """
    resource_type = resource_type.lower()
    if resource_type not in SPOTIFY_RESOURCE_TYPES:
        raise tanjun.CommandError(f"{resource_type!r} is not a valid resource type")

    response_paginator = yuyo.Paginator(
        rest_service,
        ctx.channel_id,
        SpotifyPaginator(spotify_auth.acquire_token, session, {"query": query, "type": resource_type}),
        authors=[ctx.author.id],
    )
    try:
        message = await response_paginator.open()

    except RuntimeError as exc:
        raise tanjun.CommandError(str(exc)) from None

    except ValueError:
        raise tanjun.CommandError(f"Couldn't find {resource_type}.") from None

    except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
        _LOGGER.exception("Spotify returned invalid data", exc_info=exc)
        error_manager = rest_manager.HikariErrorManager(break_on=(hikari.NotFoundError, hikari.ForbiddenError))
        await error_manager.try_respond(ctx, content="Spotify returned invalid data.")
        raise

    else:
        paginator_pool.add_paginator(message, response_paginator)


@external_component.with_message_command
@tanjun.with_greedy_argument("path", default=None)
@tanjun.with_parser
@tanjun.as_message_command("docs")
async def docs_command(
    ctx: tanjun.traits.MessageContext,
    path: typing.Optional[str],
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    doc_fetcher: CachedResource[sphobjinv.Inventory] = tanjun.injected(
        callback=tanjun.cache_callback(make_doc_fetcher)
    ),
) -> None:
    """Search Hikari's documentation.

    Arguments
        * path: Optional argument to query Hikari's documentation by.
    """
    error_manager = rest_manager.HikariErrorManager(break_on=(hikari.ForbiddenError, hikari.NotFoundError))

    if not path:
        await error_manager.try_respond(ctx, content=HIKARI_IO + "/hikari/index.html")

    else:
        path = path.replace(" ", "_")
        inventory = await doc_fetcher.acquire_resource(session)
        description: typing.List[str] = []
        # TODO: this line blocks for 2 seconds
        entries: typing.Iterator[typing.Tuple[str, int, int]] = iter(
            inventory.suggest(path, thresh=70, with_index=True, with_score=True)
        )

        for result, _ in zip(entries, range(10)):
            sphinx_object: sphobjinv.DataObjStr = inventory.objects[result[2]]
            description.append(f"[{sphinx_object.name}]({HIKARI_IO}/{sphinx_object.uri_expanded})")

        embed = hikari.Embed(
            description="\n".join(description) if description else "No results found.",
            color=constants.embed_colour(),
        )
        await error_manager.try_respond(ctx, embed=embed)


@external_component.with_message_command
@tanjun.with_owner_check
@tanjun.with_argument("url", converters=urllib.parse.ParseResult)
@tanjun.with_parser
@tanjun.as_message_command("ytdl")
async def ytdl_command(
    ctx: tanjun.traits.MessageContext,
    url: urllib.parse.ParseResult,
    session: aiohttp.ClientSession = tanjun.injected(type=aiohttp.ClientSession),
    config: config_.PTFConfig = tanjun.injected(type=config_.PTFConfig),
    ytdl_client: ytdl.YoutubeDownloader = tanjun.injected(callback=tanjun.cache_callback(ytdl.YoutubeDownloader.spawn)),
) -> None:
    auth = aiohttp.BasicAuth(config.username, config.password)

    # Download video
    path, data = await ytdl_client.download(url.geturl())
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

    await ctx.message.respond(content=file_path)


@external_component.with_interaction_command
@tanjun.as_interaction_command("test", "Just a testing command, ignore me", default_to_ephemeral=True)
async def test_command(ctx: tanjun.traits.Context) -> None:
    await asyncio.sleep(5)
    await ctx.respond("gay")
    await ctx.respond("no u")


@tanjun.as_loader
def load_component(cli: tanjun.traits.Client, /) -> None:
    cli.add_component(external_component.copy())
