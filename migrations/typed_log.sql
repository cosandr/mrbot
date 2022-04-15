INSERT INTO typed_log (time, user_id, ch_id, guild_id)
SELECT time, user_id, ch_id, guild_id FROM old_typed_log;
