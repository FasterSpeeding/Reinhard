CREATE TABLE IF NOT EXISTS StarboardChannels (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT
);

CREATE TABLE IF NOT EXISTS StarboardEntries (
    message_id BIGINT PRIMARY KEY,  -- Is that sufficient?
    channel_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    starboard_entry_id BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS PostStars (
    message_id BIGINT NOT NULL,  -- Is that sufficient?
    channel_id BIGINT NOT NULL,
    starer_id BIGINT NOT NULL
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
