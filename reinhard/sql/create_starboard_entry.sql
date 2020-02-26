-- $1 = message_id
-- $2 = channel_id
-- $3 = author_id
-- $4 = message_status
INSERT INTO StarboardEntries
    (message_id, channel_id, author_id, message_status)
    VALUES($1, $2, $3, $4);