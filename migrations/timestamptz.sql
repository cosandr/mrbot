-- SELECT 'ALTER TABLE ' || t.table_name || ' ALTER ' || t.column_name || ' TYPE timestamptz USING ' || t.column_name ||
--        ' AT TIME ZONE ''UTC'''
-- FROM (
--     SELECT column_name,
--            table_name
--     FROM information_schema.columns
--     WHERE data_type = 'timestamp without time zone'
--       AND table_catalog = 'discord'
--       AND table_schema = 'public'
-- ) AS t;
DROP TRIGGER IF EXISTS trigger_update_todo_time ON todo;

ALTER TABLE reminders ALTER notify_ts TYPE timestamptz USING notify_ts AT TIME ZONE 'UTC';
ALTER TABLE reminders ALTER updated TYPE timestamptz USING updated AT TIME ZONE 'UTC';
ALTER TABLE reminders ALTER added TYPE timestamptz USING added AT TIME ZONE 'UTC';
ALTER TABLE command_log ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE pasta ALTER added TYPE timestamptz USING added AT TIME ZONE 'UTC';
ALTER TABLE todo ALTER added TYPE timestamptz USING added AT TIME ZONE 'UTC';
ALTER TABLE todo ALTER done TYPE timestamptz USING done AT TIME ZONE 'UTC';
ALTER TABLE todo ALTER updated TYPE timestamptz USING updated AT TIME ZONE 'UTC';
ALTER TABLE old_typed_log ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE old_voice_log ALTER connect TYPE timestamptz USING connect AT TIME ZONE 'UTC';
ALTER TABLE old_voice_log ALTER disconnect TYPE timestamptz USING disconnect AT TIME ZONE 'UTC';
ALTER TABLE typed_log ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE messages ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE user_activities ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE user_status ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE voice_log ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE message_edits ALTER time TYPE timestamptz USING time AT TIME ZONE 'UTC';
ALTER TABLE pepecoins ALTER updated TYPE timestamptz USING updated AT TIME ZONE 'UTC';

CREATE TRIGGER trigger_update_todo_time BEFORE UPDATE ON todo FOR EACH ROW WHEN ((new.done IS NULL)) EXECUTE FUNCTION update_todo_time();
ALTER TABLE reminders ALTER added SET DEFAULT NOW();

CREATE TYPE pepe_stats_new AS (
        claim_time timestamptz,
        streak integer,
        last_tick timestamptz,
        tcoins numeric(50,0)
);

ALTER TABLE pepecoins ALTER stats TYPE pepe_stats_new USING (
    ((stats).claim_time AT TIME ZONE 'UTC')::timestamptz,
    (stats).streak,
    ((stats).last_tick AT TIME ZONE 'UTC')::timestamptz,
    (stats).tcoins
);

DROP TYPE pepe_stats;

ALTER TYPE pepe_stats_new RENAME TO pepe_stats;
