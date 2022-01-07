-- BSD 3-Clause License
--
-- Copyright (c) 2020-2022, Lucina
-- All rights reserved.
--
-- Redistribution and use in source and binary forms, with or without
-- modification, are permitted provided that the following conditions are met:
--
-- * Redistributions of source code must retain the above copyright notice, this
--   list of conditions and the following disclaimer.
--
-- * Redistributions in binary form must reproduce the above copyright notice,
--   this list of conditions and the following disclaimer in the documentation
--   and/or other materials provided with the distribution.
--
-- * Neither the name of the copyright holder nor the names of its
--   contributors may be used to endorse or promote products derived from
--   this software without specific prior written permission.
--
-- THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
-- AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
-- IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
-- DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
-- FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
-- DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
-- SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
-- CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
-- OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
-- OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
CREATE TABLE IF NOT EXISTS StarredMessages (
    message_id              BIGINT,
    message_content         TEXT    NOT NULL,
    channel_id              BIGINT  NOT NULL,
    author_id               BIGINT  NOT NULL,
    author_avatar_hash      TEXT,
    message_status          INT     NOT NULL DEFAULT 0,
   -- starboard_channel_id BIGINT,
    starboard_message_id    BIGINT,

    CONSTRAINT starred_messages_pk 
        PRIMARY KEY (message_id)
);

CREATE TABLE IF NOT EXISTS Stars (
    message_id  BIGINT NOT NULL,
    starrer_id  BIGINT NOT NULL,

    CONSTRAINT stars_message_id_fk
        FOREIGN KEY (message_id)
        REFERENCES StarredMessages(message_id)

    CONSTRAINT stars_pk
        PRIMARY KEY (message_id, starrer_id)
);

CREATE TABLE IF NOT EXISTS Guilds (
    id                      BIGINT PRIMARY KEY,
    starboard_channel_id    BIGINT,
    log_members             boolean NOT NULL DEFAULT false,
    member_join_log         BIGINT,
    message_spam_system     boolean NOT NULL DEFAULT false,

    CONSTRAINT guilds_pk
        PRIMARY KEY (id)
)

CREATE TABLE IF NOT EXISTS BotUserBans (
    user_id     BIGINT NOT NULL,
    reason      TEXT NOT NULL,
    expires_at  TIMESTAMP,

    CONSTRAINT bot_user_bans_pk
        PRIMARY KEY (user_id)
)

CREATE TABLE IF NOT EXISTS BotGuildBans (
    guild_id    BIGINT NOT NULL,
    reason      TEXT NOT NULL,
    expires     TIMESTAMP,

    CONSTRAINT bot_guild_bans_pk
        PRIMARY KEY (guild_id)
)

CREATE TABLE IF NOT EXISTS Tags (
    id          BIGINT,
    name        TEXT NOT NULL,
    content     TEXT NOT NULL,
    author_id   BIGINT NOT NULL,
    guild_id    BIGINT NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    uses        INT NOT NULL DEFAULT 0,

    CONSTRAINT tags_pk
        PRIMARY KEY (id),

    CONSTRAINT tags_name_fk
        UNIQUE (name, guild_id)
)
