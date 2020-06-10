from __future__ import annotations

import typing

import aiohttp

from hikari import embeds
from tanjun import clusters
from tanjun import commands
from tanjun import decorators
from tanjun import errors

from ..util import command_hooks
from ..util import constants
from ..util import paginators


exports = ["UtilCluster"]


YOUTUBE_TYPES = {
    "youtube#video": ("videoId", "https://youtube.com/watch?v="),
    "youtube#channel": ("channelId", "https://www.youtube.com/channel/"),
    "youtube#playlist": ("playlistId", "https://www.youtube.com/playlist?list="),
}


class UtilCluster(clusters.Cluster):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(
            *args,
            **kwargs,
            hooks=commands.Hooks(
                on_error=command_hooks.error_hook, on_conversion_error=command_hooks.on_conversion_error
            ),
        )
        self.paginator_pool = paginators.PaginatorPool(self.components)
        self.user_agent: str = ""

    def filter_error(self, content: str) -> str:
        content.replace(self.components.config.token, "<REDACTED>")
        for token in self.components.config.tokens.deserialize().values():
            content.replace(token, "<REDACTED>")
        return content

    async def load(self) -> None:
        application = await self.components.rest.fetch_my_application_info()
        owner_id = application.team.owner_user_id if application.team else application.owner.id
        me = await self.components.rest.fetch_me()
        self.user_agent = f"Reinhard discord bot (id:{me.id}; owner:{owner_id})"
        await super().load()

    @decorators.command(greedy="query")
    async def lyrics(self, ctx: commands.Context, query: str) -> None:
        async with aiohttp.ClientSession(
            headers={"User-Agent": self.user_agent}
        ) as session:
            response = await session.get("https://lyrics.tsu.sh/v1", params={"q": query})

            if response.status == 404:
                await ctx.message.safe_reply(content=f"Couldn't find the lyrics for `{query}`")
                return  # TODO: handle all 4XX

            if response.status >= 500:
                await ctx.message.safe_reply(content=f"Failed to fetch lyrics due to server error {response.status}")
                self.logger.exception(
                    "Received unexpected %s response from lyrics.tsu.sh\n %s", response.status, await response.text()
                )
                return

            try:
                data = await response.json()
            except ValueError as exc:
                await ctx.message.safe_reply(content=f"Invalid data returned by server.")
                self.logger.debug(
                    "Received unexpected data from lyrics.tsu.sh of type %s\n %s",
                    response.headers.get("Content-Type", "unknown"),
                    await response.text(),
                )
                raise exc
            else:
                icon = data["song"].get("icon")
                title = data["song"]["full_title"]
                response_paginator = (
                    (
                        "",
                        embeds.Embed(description=page, color=constants.EMBED_COLOUR)
                        .set_footer(text=f"Page {index}")
                        .set_author(icon=icon, name=title),
                    )
                    for page, index in paginators.string_paginator(data["content"].splitlines() or ["..."])
                )
                content, embed = next(response_paginator)
                message = await ctx.message.safe_reply(content=content, embed=embed)
                await self.paginator_pool.register_message(
                    message=message,
                    paginator=paginators.ResponsePaginator(
                        generator=response_paginator, first_entry=(content, embed), authors=(ctx.message.author.id,)
                    ),
                )

    async def log_bad_youtube_response(self, response: aiohttp.ClientResponse) -> None:
        self.logger.exception(
            "Received unexpected %s response from youtube's api\n %s", response.status, await response.text()
        )

    @decorators.command(
        greedy="query", aliases=("yt",), checks=(lambda ctx: bool(ctx.components.config.tokens.google),)
    )
    async def youtube(
        self,
        ctx: commands.Context,
        query: str,
        resource_type: str = "video",
        region: typing.Optional[str] = None,
        language: typing.Optional[str] = None,
        order: str = "relevance",
    ) -> None:
        resource_type = resource_type.lower()
        if resource_type not in ("channel", "playlist", "video"):
            await ctx.message.reply(content="Resource type must be one of 'channel', 'playist' or 'video'.")
            return

        parameters = {
            "key": ctx.components.config.tokens.google,
            "maxResults": 50,
            "order": order,
            "part": "snippet",
            "q": query,
            "safeSearch": "none" if False else "strict",  # TODO: channel.nsfw
            "type": resource_type,
        }

        if region is not None:
            parameters["regionCode"] = region

        if language is not None:
            parameters["relevanceLanguage"] = language

        async def get_next_page(
            parameters_: typing.MutableMapping[str, typing.Any]
        ) -> typing.AsyncIterator[typing.Tuple[str, embeds.Embed]]:
            next_page_token = ""
            async with aiohttp.ClientSession(
                headers={"User-Agent": self.user_agent}
            ) as session:
                while response := await session.get(
                    "https://www.googleapis.com/youtube/v3/search", params={"pageToken": next_page_token, **parameters_}
                ):
                    if response.status == 404:
                        raise errors.CommandError(f"Couldn't find `{query}`.")

                    if response.status >= 500 and next_page_token == "":
                        await self.log_bad_youtube_response(response)
                        raise errors.CommandError("Failed to reach youtube at this time, please try again later.")

                    if response.status >= 400 and next_page_token == "":
                        try:
                            error = (await response.json())["error"]["message"]
                        except (ValueError, KeyError):
                            raise errors.CommandError(
                                f"Received unexpected status code from youtube {response.status}."
                            )
                        else:
                            raise errors.CommandError(error)
                        finally:
                            await self.log_bad_youtube_response(response)
                    elif response.status >= 300:
                        await self.log_bad_youtube_response(response)
                        return

                    try:
                        data = await response.json()
                    except ValueError as exc:
                        self.logger.exception(
                            "Received unexpected data from youtube's api of type %s\n %s",
                            response.headers.get("Content-Type", "unknown"),
                            await response.text(),
                        )
                        if next_page_token == "":
                            raise errors.CommandError("Youtube returned invalid data.")
                        raise exc

                    for page in data["items"]:
                        response_type = YOUTUBE_TYPES.get(page["id"]["kind"])
                        yield f"{response_type[1]}{page['id'][response_type[0]]}", ...

                    if (next_page_token := data.get("nextPageToken")) is None:
                        break

        paginator = get_next_page(parameters)
        async for result in paginator:
            message = await ctx.message.reply(content=result[0], embed=result[1])
            await self.paginator_pool.register_message(
                message,
                paginator=paginators.AsyncResponsePaginator(
                    generator=paginator, first_entry=result, authors=[ctx.message.author.id]
                ),
            )
            break
        else:
            # data["pageInfo"]["totalResults"] will not reliably be `0` when no data is returned and they don't use 404
            # for that so we'll just check to see if nothing is being returned.
            await ctx.message.safe_reply(content=f"Couldn't find `{query}`.")

    @decorators.command  # TODO: https://lewd.bowsette.pictures/api/request
    async def moe(self, ctx: commands.Context, source: typing.Optional[str] = None) -> None:
        params = {}
        if source is not None:
            params["source"] = source

        async with aiohttp.ClientSession(
            headers={"User-Agent": self.user_agent}
        ) as session:
            response = await session.get("http://api.cutegirls.moe/json", params=params)
            if response.status == 404:
                await ctx.message.reply(content="Couldn't find image with provided search parameters.")
                return
            elif response.status >= 300:
                try:
                    message = (await response.json())["message"]
                except (ValueError, KeyError):
                    await ctx.message.safe_reply(
                        content=f"Failed to retrieve image from API which returned a {response.status}"
                    )
                else:
                    await ctx.message.safe_reply(content=f"Server returned: {message}")
                finally:
                    self.logger.exception(
                        "Received bad %s response from cutegirls.moe\n %s", response.status, await response.text()
                    )
                    return
            try:
                data = (await response.json())["data"]
            except (ValueError, KeyError) as exc:
                self.logger.exception(
                    "Received unexpected data from cutegirls.moe of type%s\n %s",
                    response.headers.get("Content-Type", "unknown"),
                    await response.text(),
                )
                await ctx.message.reply(content="Image API returned invalid data.")
                raise exc
            else:
                await ctx.message.reply(content=f"{data['image']} (source {data.get('source') or 'unknown'})")

    async def query_nekos_life(self, endpoint: str, response_key: str, **kwargs: typing.Any) -> str:
        async with aiohttp.ClientSession(
            headers={"User-Agent": self.user_agent}
        ) as session:
            response = await session.get(url := "https://nekos.life/api/v2" + endpoint)
            try:
                data = await response.json()
            except ValueError:
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
                raise errors.CommandError("Query not found.")

            if status_code >= 500 or data is None or response_key not in data:
                raise errors.CommandError(
                    "Unable to fetch image at the moment due to server error or malformed response."
                )

            if status_code >= 300:
                raise errors.CommandError(
                    f"Unable to fetch image due to unexpected error {data.get('msg', '')}"
                )

            return data[response_key]
