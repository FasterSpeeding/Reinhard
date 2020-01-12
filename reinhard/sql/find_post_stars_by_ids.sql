-- $1 = message id
-- $2 = author id
SELECT * FROM PostStars
WHERE message_id = $1 and starer_id = S2;