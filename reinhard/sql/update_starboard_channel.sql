-- $1 = guild ID
-- %2 = channel ID
UPDATE starboardchannels
    SET channel_id = $2
    WHERE guild_id = $1;
