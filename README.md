# Reinhard

Reference implementation of a Python 3.12+ Hikari-Tanjun bot.

For more information on the libraries this uses see [Tanjun](https://github.com/FasterSpeeding/Tanjun)
and [Hikari](https://github.com/hikari-py/hikari)

## Usage

### Invite

The standard instance of this bot can be invited to your guild using this
[invite link](https://discord.com/oauth2/authorize?client_id={me.id}&scope=bot%20applications.commands&permissions=8)

### Self-hosted.

This can be self hosted through only a few easy steps:

1. Ensure you have docker-compose installed.
2. Rename .env.example to .env and fill in the required entries.
3. Run `docker-compose up`.
