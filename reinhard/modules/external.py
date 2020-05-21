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

if typing.TYPE_CHECKING:
    from hikari import applications
    from hikari import users


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
        self.application: typing.Optional[applications.Application] = None
        self.user: typing.Optional[users.MyUser] = None
        self.paginator_pool = paginators.PaginatorPool(self.components)

    async def load(self) -> None:
        self.application = await self.components.rest.fetch_my_application_info()
        self.user = await self.components.rest.fetch_me()
        await super().load()

    @decorators.command(greedy="query")
    async def lyrics(self, ctx: commands.Context, query: str) -> None:
        owner_id = self.application.team.owner_user_id if self.application.team else self.application.owner.id
        async with aiohttp.ClientSession(
            headers={"User-Agent": f"Reinhard (id:{self.user.id}; owner:{owner_id})"}
        ) as session:
            response = await session.get("https://lyrics.tsu.sh/v1", params={"q": query})
            if response.status == 404:
                await ctx.message.safe_reply(content=f"Couldn't find the lyrics for `{query}`")
                return  # TODO: handle all 4XX
            if response.status >= 500:
                await ctx.message.safe_reply(content=f"Failed to fetch lyrics due to server error {response.status}")
                return

            try:
                data = await response.json()
            except ValueError as exc:
                await ctx.message.safe_reply(content=f"Invalid data returned by server: ```python\n{exc}```")
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
        owner_id = self.application.team.owner_user_id if self.application.team else self.application.owner.id
        parameters = {
            "key": ctx.components.config.tokens.google,
            "maxResults": 50,
            "order": order,
            "part": "snippet",
            "q": query,
            "safeSearch": "strict" if False else "none",  # TODO: channel.nsfw
            "type": resource_type,
        }
        if region is not None:
            parameters["regionCode"] = region
        if language is not None:
            parameters["relevanceLanguage"] = language

        async def get_next_page(parameters_: typing.MutableMapping[str, typing.Any]):
            next_page_token = ""
            async with aiohttp.ClientSession(
                headers={"User-Agent": f"Reinhard (id:{self.user.id}; owner:{owner_id})"}
            ) as session:
                while response := await session.get(
                    "https://www.googleapis.com/youtube/v3/search", params={"pageToken": next_page_token, **parameters_}
                ):
                    if response.status == 404:
                        raise errors.CommandError(f"Couldn't find `{query}`.")
                    if response.status >= 500 and next_page_token == "":
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
                    elif response.status >= 300:
                        return

                    try:
                        data = await response.json()
                    except ValueError:
                        if next_page_token == "":
                            raise errors.CommandError("Youtube returned invalid data.")
                        return

                    next_page_token = data.get("nextPageToken")
                    for page in data["items"]:
                        response_type = YOUTUBE_TYPES.get(page["id"]["kind"])
                        yield f"{response_type[1]}{page['id'][response_type[0]]}", ...
                    if next_page_token is None:
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
            #  data["pageInfo"]["totalResults"] will not reliably be `0` when no data is returned and they don't use 404
            #  for that so we'll just check to see if nothing is being returned.
            await ctx.message.safe_reply(content=f"Couldn't find `{query}`.")

    @decorators.command  # TODO: https://lewd.bowsette.pictures/api/request
    async def moe(self, ctx: commands.Context, source: typing.Optional[str] = None) -> None:
        owner_id = self.application.team.owner_user_id if self.application.team else self.application.owner.id
        params = {}
        if source is not None:
            params["source"] = source

        async with aiohttp.ClientSession(
            headers={"User-Agent": f"Reinhard (id:{self.user.id}; owner:{owner_id})"}
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
                    return
            try:
                data = (await response.json())["data"]
            except (ValueError, KeyError):
                await ctx.message.reply(content="Image API returned invalid data.")
            else:
                await ctx.message.reply(content=f"{data['image']} (by {data.get('author') or 'unknown'})")
