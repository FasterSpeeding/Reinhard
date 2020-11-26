from __future__ import annotations

__all__: typing.Sequence[str] = ["ExternalComponent"]

import asyncio
import html
import logging
import typing

import aiohttp
from hikari import embeds
from hikari import errors as hikari_errors
from hikari import undefined
from tanjun import components
from tanjun import context
from tanjun import errors as tanjun_errors
from tanjun import parsing
from yuyo import backoff
from yuyo import paginaton

from reinhard.util import constants
from reinhard.util import help as help_util
from reinhard.util import rest_manager

if typing.TYPE_CHECKING:
    from tanjun import traits as tanjun_traits


__exports__ = ["ExternalComponent"]


YOUTUBE_TYPES = {
    "youtube#video": ("videoId", "https://youtube.com/watch?v="),
    "youtube#channel": ("channelId", "https://www.youtube.com/channel/"),
    "youtube#playlist": ("playlistId", "https://www.youtube.com/playlist?list="),
}


class YoutubePaginator(typing.AsyncIterator[typing.Tuple[str, undefined.UndefinedType]]):
    __slots__ = ("_buffer", "_client", "next_page_token", "parameters", "user_agent")

    def __init__(self, parameters: typing.MutableMapping[str, typing.Union[str, int]], user_agent: str) -> None:
        self._buffer: typing.MutableSequence[typing.Mapping[str, typing.Any]] = []
        self._client: typing.Optional[aiohttp.ClientSession] = None
        self.next_page_token: str = ""
        self.parameters = parameters
        self.user_agent = user_agent

    def __aiter__(self) -> YoutubePaginator:
        return self

    async def __anext__(self) -> typing.Tuple[str, undefined.UndefinedType]:
        if self._client is None:
            self._client = aiohttp.ClientSession(headers={"User-Agent": self.user_agent})

        if not self.next_page_token and self.next_page_token is not None:
            retry = backoff.Backoff(max_retries=5)
            error_manager = rest_manager.AIOHTTPStatusHandler(retry, break_on=(404,))

            params: typing.Mapping[str, typing.Union[str, int]] = {"pageToken": self.next_page_token, **self.parameters}
            async for _ in retry:
                with error_manager:
                    response = await self._client.get("https://www.googleapis.com/youtube/v3/search", params=params,)
                    response.raise_for_status()
                    break

            else:
                if retry.is_depleted:
                    raise RuntimeError(f"Youtube request passed max_retries with params:\n {params!r}") from None

                raise StopAsyncIteration from None

            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
                raise exc

            self.next_page_token = data.get("nextPageToken")
            self._buffer.extend(data["items"])

        if not self._buffer:
            if self._client:
                await self._client.close()

            raise StopAsyncIteration

        while self._buffer:
            page = self._buffer.pop(0)
            if response_type := YOUTUBE_TYPES.get(page["id"]["kind"].lower()):
                return f"{response_type[1]}{page['id'][response_type[0]]}", undefined.UNDEFINED

        raise RuntimeError(f"Got unexpected 'kind' from youtube {page['id']['kind']}")

    def __del__(self) -> None:
        if self._client is not None:
            asyncio.ensure_future(self._client.close())


@help_util.with_component_name("External Component")
@help_util.with_component_doc("A utility used for getting data from 3rd party APIs.")
class ExternalComponent(components.Component):
    __slots__: typing.Sequence[str] = ("google_token", "logger", "paginator_pool", "user_agent")

    def __init__(
        self, *, google_token: typing.Optional[str] = None, hooks: typing.Optional[tanjun_traits.Hooks] = None
    ) -> None:
        super().__init__(hooks=hooks)
        self.google_token = google_token
        self.logger = logging.Logger("hikari.reinhard.external")
        self.paginator_pool: typing.Optional[paginaton.PaginatorPool] = None
        self.user_agent = ""
        self.youtube.add_check(lambda _: bool(self.google_token),)

    def bind_client(self, client: tanjun_traits.Client, /) -> None:
        super().bind_client(client)
        self.paginator_pool = paginaton.PaginatorPool(client.rest_service, client.dispatch_service)

    async def close(self) -> None:
        if self.paginator_pool is not None:
            await self.paginator_pool.close()

        await self.close()
        await super().close()

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

    @help_util.with_parameter_doc("query", "The required argument of a query to search up a song by.")
    @help_util.with_command_doc("Get a song's lyrics.")
    @parsing.greedy_argument("query")
    @components.command("lyrics")
    async def lyrics(self, ctx: context.Context, query: str) -> None:
        async with aiohttp.ClientSession(headers={"User-Agent": self.user_agent}) as session:
            retry = backoff.Backoff(max_retries=5)
            error_manager = rest_manager.AIOHTTPStatusHandler(
                retry, on_404=f"Couldn't find the lyrics for `{query[:1960]}`"
            )
            async for _ in retry:
                with error_manager:
                    response = await session.get("https://lyrics.tsu.sh/v1", params={"q": query})
                    response.raise_for_status()
                    break

            else:
                raise tanjun_errors.CommandError("Couldn't get response in time") from None

            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError) as exc:
                hikari_error_manager = rest_manager.HikariErrorManager(
                    retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
                )
                retry.reset()

                async for _ in retry:
                    with hikari_error_manager:
                        await ctx.message.reply(content=f"Invalid data returned by server.")
                        break

                self.logger.debug(
                    "Received unexpected data from lyrics.tsu.sh of type %s\n %s",
                    response.headers.get("Content-Type", "unknown"),
                    await response.text(),
                )
                raise exc

            icon = data["song"].get("icon")
            title = data["song"]["full_title"]
            pages = (
                (
                    undefined.UNDEFINED,
                    embeds.Embed(description=html.unescape(page), color=constants.EMBED_COLOUR)
                    .set_footer(text=f"Page {index + 1}")
                    .set_author(icon=icon, name=html.unescape(title)),
                )
                async for page, index in paginaton.string_paginator(iter(data["content"].splitlines() or ["..."]))
            )
            response_paginator = paginaton.Paginator(
                ctx.client.rest_service,
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

    @help_util.with_command_doc("Get a youtube video.")
    @parsing.option("safe_search", "--safe", "-s", "--safe-search", converters=(bool,), default=None)
    @parsing.option("order", "-o", "--order", default="relevance")
    @parsing.option("language", "-l", "--language", default=None)
    @parsing.option("region", "-r", "--region", default=None)
    @parsing.option("resource_type", "-rt", "--type", "-t", "--resource-type", default="video")
    @parsing.greedy_argument("query")
    @components.command("youtube", "yt")
    async def youtube(  # TODO: fully document
        self,
        ctx: context.Context,
        query: str,
        resource_type: str,
        region: typing.Optional[str],
        language: typing.Optional[str],
        order: str,
        safe_search: typing.Optional[bool],
    ) -> None:
        if safe_search is not False:
            ...

        resource_type = resource_type.lower()
        if resource_type not in ("channel", "playlist", "video"):
            raise tanjun_errors.CommandError("Resource type must be one of 'channel', 'playist' or 'video'.")

        assert self.google_token is not None
        parameters: typing.MutableMapping[str, typing.Union[str, int]] = {
            "key": self.google_token,
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
            ctx.client.rest_service,
            ctx.message.channel_id,
            YoutubePaginator(parameters, self.user_agent),
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
            self.logger.exception("Youtube returned invalid data, %r", exc)

            retry = backoff.Backoff(max_retries=5)
            error_manager = rest_manager.HikariErrorManager(
                retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
            )
            async for _ in retry:
                with error_manager:
                    await ctx.message.reply(content="Youtube returned invalid data.")
                    break

            raise

        else:
            assert self.paginator_pool is not None
            self.paginator_pool.add_paginator(message, response_paginator)

    @help_util.with_parameter_doc("--source | -s", "The optional argument of a show's title.")
    @help_util.with_command_doc("Get a random cute anime image.")
    @parsing.option("source", "--source", "-s", default=None)
    @components.command("moe")  # TODO: https://lewd.bowsette.pictures/api/request
    async def moe(self, ctx: tanjun_traits.Context, source: typing.Optional[str] = None) -> None:
        params = {}
        if source is not None:
            params["source"] = source

        async with aiohttp.ClientSession(headers={"User-Agent": self.user_agent}) as session:
            retry = backoff.Backoff(max_retries=5)
            error_manager = rest_manager.AIOHTTPStatusHandler(
                retry, on_404=f"Couldn't find source `{source[:1970]}`" if source is not None else "couldn't access api"
            )
            async for _ in retry:
                with error_manager:
                    response = await session.get("http://api.cutegirls.moe/json", params=params)
                    response.raise_for_status()
                    break

            else:
                raise tanjun_errors.CommandError("Couldn't get response in time") from None

            hikari_error_manager = rest_manager.HikariErrorManager(
                retry, break_on=(hikari_errors.NotFoundError, hikari_errors.ForbiddenError)
            )
            retry.reset()

            try:
                data = (await response.json())["data"]
            except (aiohttp.ContentTypeError, aiohttp.ClientPayloadError, ValueError, KeyError) as exc:
                async for _ in retry:
                    with hikari_error_manager:
                        await ctx.message.reply(content="Image API returned invalid data.")
                        break

                raise exc

            async for _ in retry:
                with hikari_error_manager:
                    await ctx.message.reply(content=f"{data['image']} (source {data.get('source') or 'unknown'})")
                    break

    async def query_nekos_life(self, endpoint: str, response_key: str, **kwargs: typing.Any) -> str:
        async with aiohttp.ClientSession(headers={"User-Agent": self.user_agent}) as session:
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
            except (KeyError, ValueError, TypeError):
                status_code = response.status

            if status_code == 404:
                raise tanjun_errors.CommandError("Query not found.") from None

            if status_code >= 500 or data is None or response_key not in data:
                raise tanjun_errors.CommandError(
                    "Unable to fetch image at the moment due to server error or malformed response."
                ) from None

            if status_code >= 300:
                raise tanjun_errors.CommandError(
                    f"Unable to fetch image due to unexpected error {data.get('msg', '')}"
                ) from None

            result = data[response_key]
            assert isinstance(result, str)
            return result
