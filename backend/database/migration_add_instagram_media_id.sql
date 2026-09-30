-- Instagram publishing record.
--
-- `instagram_media_id` holds Instagram's own id for a post once it has been
-- published there, and stays NULL for everything else -- which is most posts,
-- since the admin toggle that triggers a push defaults to off.
--
-- It is a record rather than a mirror. Instagram's Graph API has no endpoint to
-- delete a published post or edit its caption, so unlike `source`/`source_id`
-- (which the notes ingest upserts against) this column is written exactly once
-- and never reconciled. Its second job is being that guard: a post that already
-- carries an id is skipped, so re-saving can never double-post.
--
-- No unique index. A duplicate here would mean Instagram handed back the same
-- media id for two different posts, which it does not do, and a constraint that
-- can only fire on their bug would block a legitimate write for no gain.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_media_id VARCHAR(255);
