-- $1 = message id
SELECT * FROM StarboardEntries
WHERE message_id = $1;