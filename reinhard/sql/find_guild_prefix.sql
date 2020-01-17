-- $1 = guild ID.
SELECT prefix FROM Prefixes
WHERE guild_id = $1;