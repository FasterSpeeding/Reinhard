-- $1 = message ID
-- $2 = channel ID
-- $3 = starer ID
INSERT INTO poststars (message_id, channel_id, starer_id)
    VALUES ($1, $2, $3);