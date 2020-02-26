CREATE TABLE IF NOT EXISTS StarboardChannels (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT
);

CREATE TABLE IF NOT EXISTS StarboardEntries (
    message_id BIGINT PRIMARY KEY,  -- Is that sufficient?
    channel_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    message_status INT NOT NULL DEFAULT 0,
   -- starboard_channel_id BIGINT,
    starboard_message_id BIGINT
);

CREATE TABLE IF NOT EXISTS PostStars (
    message_id BIGINT NOT NULL references StarboardEntries(message_id),  -- Is that sufficient?
    channel_id BIGINT NOT NULL,
    starer_id BIGINT NOT NULL,
    PRIMARY KEY (message_id, starer_id)
);

CREATE TABLE IF NOT EXISTS Filters (
    target_id BIGINT PRIMARY KEY,
    target_type SMALLINT NOT NULL,
    status SMALLINT NOT NULL,
    timeout TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Prefixes (
    guild_id BIGINT PRIMARY KEY,
    prefix VARCHAR(10) NOT NULL
);
