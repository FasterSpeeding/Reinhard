from __future__ import annotations

__all__: typing.Sequence[str] = ["ExternalComponent"]

import datetime
import logging
import time
import typing

import aiohttp
import sphobjinv  # type: ignore[import]
from hikari import channels
from hikari import embeds
from hikari import errors as hikari_errors
from hikari import undefined
from tanjun import components
from tanjun import errors as tanjun_errors
from tanjun import parsing
from yuyo import backoff
from yuyo import paginaton

from ..util import basic as basic_util
from ..util import constants
from ..util import rest_manager

if typing.TYPE_CHECKING:
    from hikari import config as hikari_config
    from tanjun import traits as tanjun_traits

    from .. import config

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


def create_client_session(
    http_settings: hikari_config.HTTPSettings,
    raise_for_status: bool,
    trust_env: bool,
    headers: typing.Optional[typing.Mapping[str, str]] = None,
    ws_response_cls: typing.Type[aiohttp.ClientWebSocketResponse] = aiohttp.ClientWebSocketResponse,
) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers=headers,
        raise_for_status=raise_for_status,
        timeout=aiohttp.ClientTimeout(
            connect=http_settings.timeouts.acquire_and_connect,
            sock_connect=http_settings.timeouts.request_socket_connect,
            sock_read=http_settings.timeouts.request_socket_read,
            total=http_settings.timeouts.total,
        ),
        trust_env=trust_env,
        version=aiohttp.HttpVersion11,
        ws_response_class=ws_response_cls,
    )


class YoutubePaginator(typing.AsyncIterator[typing.Tuple[str, undefined.UndefinedType]]):
    __slots__ = ("_acquire_session", "_buffer", "_next_page_token", "_parameters")

    def __init__(
        self,
        acquire_session: typing.Callable[[], aiohttp.ClientSession],
        parameters: typing.Dict[str, typing.Union[str, int]],
    ) -> None:
        self._acquire_session = acquire_session
        self._buffer: typing.List[typing.Dict[str, typing.Any]] = []
        self._next_page_token: typing.Optional[str] = ""
        self._parameters = parameters

    def __aiter__(self) -> YoutubePaginator:
        return self

    async def __anext__(self) -> typing.Tuple[str, undefined.UndefinedType]:
        if not self._next_page_token and self._next_page_token is not None:
            retry = backoff.Backoff(max_retries=5)
            error_manager = rest_manager.AIOHTTPStatusHandler(retry, break_on=(404,))

            parameters = self._parameters.copy()
            parameters["pageToken"] = self._next_page_token
            session = self._acquire_session()
            async for _ in retry:
                with error_manager:
                    response = await session.get("https://www.googleapis.com/youtube/v3/search", params=parameters)
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
                return f"{response_type[1]}{page['id'][response_type[0]]}", undefined.UNDEFINED

        raise RuntimeError(f"Got unexpected 'kind' from youtube {page['id']['kind']}")


class SpotifyPaginator(typing.AsyncIterator[typing.Tuple[str, undefined.UndefinedType]]):
    __slots__: typing.Sequence[str] = (
        "_acquire_authorization",
        "_acquire_session",
        "_buffer",
        "_offset",
        "_parameters",
    )

    _limit: typing.Final[int] = 50

    def __init__(
        self,
        acquire_authorization: typing.Callable[[aiohttp.ClientSession], typing.Awaitable[str]],
        acquire_session: typing.Callable[[], aiohttp.ClientSession],
        parameters: typing.Dict[str, typing.Union[str, int]],
    ) -> None:
        self._acquire_authorization = acquire_authorization
        self._acquire_session = acquire_session
        self._buffer: typing.List[typing.Dict[str, typing.Any]] = []
        self._offset: typing.Optional[int] = 0
        self._parameters = parameters

    def __aiter__(self) -> SpotifyPaginator:
        return self

    async def __anext__(self) -> typing.Tuple[str, undefined.UndefinedType]:
        if not self._buffer and self._offset is not None:
            retry = backoff.Backoff(max_retries=5)
            resource_type = self._parameters["type"]
            assert isinstance(resource_type, str)
            error_manager = rest_manager.AIOHTTPStatusHandler(
                retry, on_404=basic_util.raise_error(None, StopAsyncIteration)
            )
            parameters = self._parameters.copy()
            parameters["offset"] = self._offset
            self._offset += self._limit

            session = self._acquire_session()
            async for _ in retry:
                with error_manager:
                    response = await session.get(
                        "https://api.spotify.com/v1/search",
                        params=parameters,
                        headers={"Authorization": await self._acquire_authorization(session)},
                    )
                    response.raise_for_status()
                    break

            else:
                raise tanjun_errors.CommandError(f"Couldn't fetch {resource_type} in time") from None

            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
                raise exc

            # TODO: only store urls?
            self._buffer.extend(data[resource_type + "s"]["items"])

        if not self._buffer:
            self._offset = None
            raise StopAsyncIteration

        return (self._buffer.pop(0)["external_urls"]["spotify"], undefined.UNDEFINED)


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
        raise tanjun_errors.CommandError("Couldn't authenticate")


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


class ExternalComponent(components.Component):
    """A utility used for getting data from 3rd party APIs."""

    __slots__: typing.Sequence[str] = (
        "_client_session",
        "_doc_fetcher",
        "_http_settings",
        "paginator_pool",
        "proxy_setting",
        "_tokens",
        "user_agent",
    )

    def __init__(
        self,
        http_settings: hikari_config.HTTPSettings,
        proxy_settings: hikari_config.ProxySettings,
        tokens: config.Tokens,
        *,
        hooks: typing.Optional[tanjun_traits.Hooks] = None,
    ) -> None:
        super().__init__(hooks=hooks)
        self._client_session: typing.Optional[aiohttp.ClientSession] = None
        self._doc_fetcher = CachedResource(
            HIKARI_IO + "/objects.inv", datetime.timedelta(hours=12), sphobjinv.Inventory
        )
        self._http_settings = http_settings
        self._proxy_settings = proxy_settings
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None

        self._spotify_auth: typing.Optional[ClientCredentialsOauth2] = None
        if tokens.spotify_id is not None and tokens.spotify_secret is not None:
            self._spotify_auth = ClientCredentialsOauth2(
                "https://accounts.spotify.com/api/token", tokens.spotify_id, tokens.spotify_secret
            )

        self._tokens = tokens
        self.user_agent = ""

    def _acquire_session(self) -> aiohttp.ClientSession:
        if self._client_session is None:
            self._client_session = create_client_session(
                headers={USER_AGENT_HEADER: self.user_agent},
                http_settings=self._http_settings,
                raise_for_status=False,
                trust_env=self._proxy_settings.trust_env,
            )
            _LOGGER.log(logging.DEBUG, "acquired new aiohttp client session")

        return self._client_session

    def bind_client(self, client: tanjun_traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest_service, client.event_service)

    async def close(self) -> None:
        await super().close()
        if self.paginator_pool is not None:
            await self.paginator_pool.close()

        if self._client_session:
            await self._client_session.close()
            self._client_session = None

    async def open(self) -> None:
        if self.client is None or self.paginator_pool is None:
            raise RuntimeError("Cannot open this component without binding a client.")

        retry = backoff.Backoff(max_retries=4)
        error_manger = rest_manager.HikariErrorManager(retry)
        async for _ in retry:
            with error_manger:
                application = await self.client.rest_service.rest.fetch_application()
                break

        else:
            application = await self.client.rest_service.rest.fetch_application()

        owner_id = application.team.owner_id if application.team else application.owner.id
        retry.reset()

        async for _ in retry:
            with error_manger:
                me = await self.client.rest_service.rest.fetch_my_user()
                break

        else:
            me = await self.client.rest_service.rest.fetch_my_user()

        self.user_agent = f"Reinhard discord bot (id:{me.id}; owner:{owner_id})"
        await self.paginator_pool.open()
        await super().open()

    @parsing.with_greedy_argument("query")
    @parsing.with_parser
    @components.as_command("lyrics")
    async def lyrics(self, ctx: tanjun_traits.Context, query: str) -> None:
        """Get a song's lyrics.

        Arguments:
            * query: Greedy query string (e.g. name) to search a song by.
        """
        session = self._acquire_session()
        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.AIOHTTPStatusHandler(
            retry, on_404=f"Couldn't find the lyrics for `{query[:1960]}`"
        )
        async for _ in retry:
            with error_manager:
                response = await session.get("https://evan.lol/lyrics/search/top", params={"q": query})
                response.raise_for_status()
                break

        else:
            raise tanjun_errors.CommandError("Couldn't get the lyrics in time") from None

        try:
            data = await response.json()
        except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
            hikari_error_manager = rest_manager.HikariErrorManager(
                retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
            )
            await hikari_error_manager.try_respond(ctx, content="Invalid data returned by server.")

            _LOGGER.exception(
                "Received unexpected data from lyrics.tsu.sh of type %s\n %s",
                response.headers.get(CONTENT_TYPE_HEADER, "unknown"),
                await response.text(),
                exc_info=exc,
            )
            raise tanjun_errors.CommandError("Failed to receive lyrics")

        icon: typing.Optional[str] = None
        if "album" in data and (icon_data := data["album"]["icon"]):
            icon = icon_data.get("url")

        title = data["name"]

        if artists := data["artists"]:
            title += " - " + " | ".join((a["name"] for a in artists))

        pages = (
            (
                undefined.UNDEFINED,
                embeds.Embed(description=page, colour=constants.embed_colour())
                .set_footer(text=f"Page {index + 1}")
                .set_author(icon=icon, name=title),
            )
            async for page, index in paginaton.string_paginator(iter(data["lyrics"].splitlines() or ["..."]))
        )
        response_paginator = paginaton.Paginator(
            ctx.rest_service,
            ctx.message.channel_id,
            pages,
            authors=(ctx.message.author.id,),
            triggers=(
                paginaton.LEFT_DOUBLE_TRIANGLE,
                paginaton.LEFT_TRIANGLE,
                paginaton.STOP_SQUARE,
                paginaton.RIGHT_TRIANGLE,
                paginaton.RIGHT_DOUBLE_TRIANGLE,
            ),
        )
        message = await response_paginator.open()
        assert self.paginator_pool is not None
        self.paginator_pool.add_paginator(message, response_paginator)

    @parsing.with_option("safe_search", "--safe", "-s", "--safe-search", converters=bool, default=None)
    @parsing.with_option("order", "-o", "--order", default="relevance")
    @parsing.with_option("language", "-l", "--language", default=None)
    @parsing.with_option("region", "-r", "--region", default=None)
    # TODO: should different resource types be split between different sub commands?
    @parsing.with_option("resource_type", "--type", "-t", default="video")
    @parsing.with_greedy_argument("")
    @parsing.with_parser
    @components.as_command("youtube", "yt")
    async def youtube(
        self,
        ctx: tanjun_traits.Context,
        query: str,
        resource_type: str,
        region: typing.Optional[str],
        language: typing.Optional[str],
        order: str,
        safe_search: typing.Optional[bool],
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
        if safe_search is not False:
            channel: typing.Optional[channels.GuildChannel] = None

            if ctx.cache_service:
                channel = ctx.cache_service.cache.get_guild_channel(ctx.message.channel_id)

            if not channel:
                # TODO: handle retires
                result = await ctx.rest_service.rest.fetch_channel(ctx.message.channel_id)
                assert isinstance(result, channels.GuildChannel)
                channel = result

            if safe_search is None:
                safe_search = not channel.is_nsfw

            elif not safe_search and not channel.is_nsfw:
                raise tanjun_errors.CommandError("Cannot disable safe search in a sfw channel")

        resource_type = resource_type.lower()
        if resource_type not in ("channel", "playlist", "video"):
            raise tanjun_errors.CommandError("Resource type must be one of 'channel', 'playist' or 'video'.")

        assert self._tokens.google is not None
        parameters: typing.Dict[str, typing.Union[str, int]] = {
            "key": self._tokens.google,
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

        response_paginator = paginaton.Paginator(
            ctx.rest_service,
            ctx.message.channel_id,
            YoutubePaginator(self._acquire_session, parameters),
            authors=[ctx.message.author.id],
        )
        try:
            message = await response_paginator.open()
            assert message is not None

        except RuntimeError as exc:
            raise tanjun_errors.CommandError(str(exc)) from None

        except ValueError:
            raise tanjun_errors.CommandError(f"Couldn't find `{query}`.") from None
            # data["pageInfo"]["totalResults"] will not reliably be `0` when no data is returned and they don't use 404
            # for that so we'll just check to see if nothing is being returned.

        except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
            _LOGGER.exception("Youtube returned invalid data", exc_info=exc)
            error_manager = rest_manager.HikariErrorManager(
                break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
            )
            await error_manager.try_respond(ctx, content="Youtube returned invalid data.")
            raise

        else:
            assert self.paginator_pool is not None
            self.paginator_pool.add_paginator(message, response_paginator)

    @youtube.with_check
    def _youtube_token_check(self, _: tanjun_traits.Context) -> bool:
        return self._tokens.google is not None

    # This API is currently dead (always returning 5xxs)
    # @help_util.with_parameter_doc("--source | -s", "The optional argument of a show's title.")
    # @help_util.with_command_doc("Get a random cute anime image.")
    # @parsing.with_option("source", "--source", "-s", default=None)
    # @parsing.with_parser
    # @components.as_command("moe")  # TODO: https://lewd.bowsette.pictures/api/request
    async def moe(self, ctx: tanjun_traits.Context, source: typing.Optional[str] = None) -> None:
        params = {}
        if source is not None:
            params["source"] = source

        retry = backoff.Backoff(max_retries=5)
        error_manager = rest_manager.AIOHTTPStatusHandler(
            retry, on_404=f"Couldn't find source `{source[:1970]}`" if source is not None else "couldn't access api"
        )
        session = self._acquire_session()
        async for _ in retry:
            with error_manager:
                response = await session.get("http://api.cutegirls.moe/json", params=params)
                response.raise_for_status()
                break

        else:
            raise tanjun_errors.CommandError("Couldn't get an image in time") from None

        hikari_error_manager = rest_manager.HikariErrorManager(
            retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
        )

        try:
            data = (await response.json())["data"]
        except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, LookupError, ValueError) as exc:
            await hikari_error_manager.try_respond(ctx, content="Image API returned invalid data.")
            raise exc

        await hikari_error_manager.try_respond(
            ctx, content=f"{data['image']} (source {data.get('source') or 'unknown'})"
        )

    async def query_nekos_life(self, endpoint: str, response_key: str, **kwargs: typing.Any) -> str:
        session = self._acquire_session()
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
            raise tanjun_errors.CommandError("Query not found.") from None

        if status_code >= 500 or data is None or response_key not in data:
            raise tanjun_errors.CommandError(
                "Unable to fetch image at the moment due to server error or malformed response."
            ) from None

        if status_code >= 300:
            raise tanjun_errors.CommandError(f"Unable to fetch image due to unexpected error {status_code}") from None

        result = data[response_key]
        assert isinstance(result, str)
        return result

    # TODO: add valid options for Options maybe?
    @parsing.with_option("resource_type", "--type", "-t", default="track")
    @parsing.with_greedy_argument("query")
    @parsing.with_parser
    @components.as_command("spotify")
    async def spotify(self, ctx: tanjun_traits.Context, query: str, resource_type: str) -> None:
        """Search for a resource on spotify.

        Arguments:
            * query: The greedy string query to search by.

        Options:
            * resource type (--type, -t):
                Type of resource to search for. This can be one of "track", "album", "artist" or "playlist" and defaults
                to track.
        """
        assert self._spotify_auth

        resource_type = resource_type.lower()
        if resource_type not in SPOTIFY_RESOURCE_TYPES:
            raise tanjun_errors.CommandError(f"{resource_type!r} is not a valid resource type")

        response_paginator = paginaton.Paginator(
            ctx.rest_service,
            ctx.message.channel_id,
            SpotifyPaginator(
                self._spotify_auth.acquire_token, self._acquire_session, {"query": query, "type": resource_type}
            ),
            authors=[ctx.message.author.id],
        )
        try:
            message = await response_paginator.open()
            assert message is not None

        except RuntimeError as exc:
            raise tanjun_errors.CommandError(str(exc)) from None

        except ValueError:
            raise tanjun_errors.CommandError(f"Couldn't find {resource_type}.") from None

        except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError) as exc:
            _LOGGER.exception("Spotify returned invalid data", exc_info=exc)
            error_manager = rest_manager.HikariErrorManager(
                break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
            )
            await error_manager.try_respond(ctx, content="Spotify returned invalid data.")
            raise

        else:
            assert self.paginator_pool is not None
            self.paginator_pool.add_paginator(message, response_paginator)

    @spotify.with_check
    def _spotify_authentication_check(self, _: tanjun_traits.Context) -> bool:
        return self._spotify_auth is not None

    @parsing.with_greedy_argument("path", default=None)
    @parsing.with_parser
    @components.as_command("docs")
    async def docs(self, ctx: tanjun_traits.Context, path: typing.Optional[str]) -> None:
        """Search Hikari's documentation.

        Arguments
            * path: Optional argument to query Hikari's documentation by.
        """
        error_manager = rest_manager.HikariErrorManager(
            break_on=(hikari_errors.ForbiddenError, hikari_errors.NotFoundError)
        )

        if not path:
            await error_manager.try_respond(ctx, content=HIKARI_IO + "/hikari/index.html")

        else:
            path = path.replace(" ", "_")
            inventory = await self._doc_fetcher.acquire_resource(self._acquire_session())
            description: typing.List[str] = []
            # TODO: this line blocks for 2 seconds
            entries: typing.Iterator[typing.Tuple[str, int, int]] = iter(
                inventory.suggest(path, thresh=70, with_index=True, with_score=True)
            )

            for result, _ in zip(entries, range(10)):
                sphinx_object: sphobjinv.DataObjStr = inventory.objects[result[2]]
                description.append(f"[{sphinx_object.name}]({HIKARI_IO}/{sphinx_object.uri_expanded})")

            embed = embeds.Embed(
                description="\n".join(description) if description else "No results found.",
                color=constants.embed_colour(),
            )
            await error_manager.try_respond(ctx, embed=embed)
