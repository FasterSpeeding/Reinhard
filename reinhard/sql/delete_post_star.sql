-- $1 = message ID
-- $2 = starer ID
DELETE FROM poststars
WHERE poststars.message_id = $1 and poststars.starer_id = $2