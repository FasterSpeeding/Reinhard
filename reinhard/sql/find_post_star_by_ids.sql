-- $1 = message ID
-- $2 = starer ID
SELECT * FROM PostStars
WHERE message_id = $1 and starer_id = $2;
