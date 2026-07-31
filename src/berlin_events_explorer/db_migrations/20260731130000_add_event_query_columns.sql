-- Virtual date and title columns derived from the canonical JSON payload so
-- listing views can filter, sort, and paginate in SQL instead of Python.
ALTER TABLE `events` ADD COLUMN `start_date` text GENERATED ALWAYS AS (json_extract(`event_json`, '$.start_date')) VIRTUAL;
ALTER TABLE `events` ADD COLUMN `end_date` text GENERATED ALWAYS AS (json_extract(`event_json`, '$.end_date')) VIRTUAL;
ALTER TABLE `events` ADD COLUMN `title` text GENERATED ALWAYS AS (json_extract(`event_json`, '$.title')) VIRTUAL;
-- Case-folded search haystack (title, venue, performers) maintained by the
-- application on every upsert; NULL rows are backfilled on store open.
ALTER TABLE `events` ADD COLUMN `search_text` text NULL;
-- Create index "ix_events_start_date" to table: "events"
CREATE INDEX `ix_events_start_date` ON `events` (`start_date`);
-- Create index "ix_events_first_seen_at" to table: "events"
CREATE INDEX `ix_events_first_seen_at` ON `events` (`first_seen_at`);
