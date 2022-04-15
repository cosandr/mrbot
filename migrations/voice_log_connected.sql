INSERT INTO voice_log (connected, time, user_id, ch_id, guild_id)
SELECT DISTINCT ON (connect, disconnect)
       connect > disconnect AS connected,
       GREATEST(connect, disconnect) AS time,
       user_id, ch_id, guild_id
FROM old_voice_log WHERE connect IS NOT null AND disconnect IS NOT null;
