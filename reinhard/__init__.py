from __future__ import annotations

import typing

from tanjun import clients

from . import client as reinhard_client

if typing.TYPE_CHECKING:
    from tanjun import traits as tanjun_traits


@clients.as_loader
def load(client: tanjun_traits.Client, /) -> None:
    reinhard_client.add_components(client)
