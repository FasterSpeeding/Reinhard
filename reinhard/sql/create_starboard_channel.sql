-- $1 = guild ID
-- %2 = channel ID
INSERT INTO starboardchannels (guild_id, channel_id)
    VALUES ($1, $2);