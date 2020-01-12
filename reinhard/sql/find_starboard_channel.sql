-- $1 = guild ID
SELECT * FROM StarboardChannels
WHERE guild_id = $1;