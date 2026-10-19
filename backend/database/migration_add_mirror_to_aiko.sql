-- Per-post opt-out of the Aiko mirror.
--
-- TRUE (the default, and what every existing post gets) keeps today's
-- behaviour: art and photo posts are mirrored to Aiko on every save. FALSE is
-- the admin's "Post to Aiko" switch turned off, and also rules the post out of
-- Instagram, which only publishes posts that went through Aiko.
--
-- Run before deploying the code that reads it: the model selects this column.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS mirror_to_aiko BOOLEAN NOT NULL DEFAULT TRUE;
