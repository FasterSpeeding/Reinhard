-- %1 = guild ID
-- %2 = string prefix
INSERT INTO public.prefixes
(guild_id, prefix)
VALUES($1, $2);
