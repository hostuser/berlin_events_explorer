-- Create "events" table
CREATE TABLE `events` (
  `id` varchar NOT NULL,
  `provider` varchar NOT NULL,
  `source_record_hash` varchar NOT NULL,
  `event_json` json NOT NULL,
  `first_seen_at` datetime NOT NULL,
  `last_seen_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
);
-- Create index "ix_events_provider" to table: "events"
CREATE INDEX `ix_events_provider` ON `events` (`provider`);
-- Create "venues" table
CREATE TABLE `venues` (
  `id` varchar NOT NULL,
  `name` varchar NOT NULL,
  `normalized_name` varchar NOT NULL,
  `city` varchar NULL,
  `country` varchar NULL,
  `address` text NULL,
  `postal_code` varchar NULL,
  `latitude` varchar NULL,
  `longitude` varchar NULL,
  `website` text NULL,
  `osm_type` varchar NULL,
  `osm_id` varchar NULL,
  `status` varchar NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `last_checked_at` datetime NULL,
  PRIMARY KEY (`id`)
);
-- Create index "venues_osm_type_osm_id" to table: "venues"
CREATE UNIQUE INDEX `venues_osm_type_osm_id` ON `venues` (`osm_type`, `osm_id`);
-- Create index "ix_venues_status" to table: "venues"
CREATE INDEX `ix_venues_status` ON `venues` (`status`);
-- Create index "ix_venues_normalized_name" to table: "venues"
CREATE INDEX `ix_venues_normalized_name` ON `venues` (`normalized_name`);
-- Create "artists" table
CREATE TABLE `artists` (
  `id` varchar NOT NULL,
  `name` varchar NOT NULL,
  `normalized_name` varchar NOT NULL,
  `artist_type` varchar NULL,
  `country` varchar NULL,
  `disambiguation` text NULL,
  `musicbrainz_id` varchar NULL,
  `musicbrainz_url` text NULL,
  `genres_json` json NOT NULL,
  `status` varchar NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `last_checked_at` datetime NULL,
  PRIMARY KEY (`id`)
);
-- Create index "artists_musicbrainz_id" to table: "artists"
CREATE UNIQUE INDEX `artists_musicbrainz_id` ON `artists` (`musicbrainz_id`);
-- Create index "ix_artists_normalized_name" to table: "artists"
CREATE INDEX `ix_artists_normalized_name` ON `artists` (`normalized_name`);
-- Create index "ix_artists_status" to table: "artists"
CREATE INDEX `ix_artists_status` ON `artists` (`status`);
-- Create "source_snapshots" table
CREATE TABLE `source_snapshots` (
  `provider` varchar NOT NULL,
  `url` text NOT NULL,
  `etag` varchar NULL,
  `last_modified` varchar NULL,
  `content_hash` varchar NULL,
  `checked_at` datetime NOT NULL,
  PRIMARY KEY (`provider`)
);
-- Create "audit_log" table
CREATE TABLE `audit_log` (
  `id` integer NOT NULL,
  `event_id` varchar NOT NULL,
  `provider` varchar NOT NULL,
  `action` varchar NOT NULL,
  `changes_json` json NOT NULL,
  `changed_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
);
-- Create index "ix_audit_log_event_id" to table: "audit_log"
CREATE INDEX `ix_audit_log_event_id` ON `audit_log` (`event_id`);
-- Create "log" table
CREATE TABLE `log` (
  `id` integer NOT NULL,
  `level` varchar NOT NULL,
  `event` varchar NOT NULL,
  `message` text NOT NULL,
  `context_json` json NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
);
-- Create index "ix_log_event" to table: "log"
CREATE INDEX `ix_log_event` ON `log` (`event`);
-- Create index "ix_log_created_at" to table: "log"
CREATE INDEX `ix_log_created_at` ON `log` (`created_at`);
-- Create index "ix_log_level" to table: "log"
CREATE INDEX `ix_log_level` ON `log` (`level`);
-- Create "settings" table
CREATE TABLE `settings` (
  `key` varchar NOT NULL,
  `value_json` json NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`key`)
);
-- Create "venue_metadata" table
CREATE TABLE `venue_metadata` (
  `id` integer NOT NULL,
  `venue_id` varchar NOT NULL,
  `field` varchar NOT NULL,
  `value_json` json NOT NULL,
  `provider` varchar NOT NULL,
  `source_url` text NULL,
  `confidence` varchar NULL,
  `retrieved_at` datetime NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `0` FOREIGN KEY (`venue_id`) REFERENCES `venues` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "venue_metadata_venue_id_field_provider_source_url" to table: "venue_metadata"
CREATE UNIQUE INDEX `venue_metadata_venue_id_field_provider_source_url` ON `venue_metadata` (`venue_id`, `field`, `provider`, `source_url`);
-- Create index "ix_venue_metadata_venue_id" to table: "venue_metadata"
CREATE INDEX `ix_venue_metadata_venue_id` ON `venue_metadata` (`venue_id`);
-- Create "venue_candidates" table
CREATE TABLE `venue_candidates` (
  `id` integer NOT NULL,
  `venue_id` varchar NOT NULL,
  `provider` varchar NOT NULL,
  `source_url` text NOT NULL,
  `osm_type` varchar NOT NULL,
  `osm_id` varchar NOT NULL,
  `display_name` text NOT NULL,
  `address` text NULL,
  `postal_code` varchar NULL,
  `website` text NULL,
  `latitude` varchar NULL,
  `longitude` varchar NULL,
  `confidence` varchar NOT NULL,
  `retrieved_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `0` FOREIGN KEY (`venue_id`) REFERENCES `venues` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "venue_candidates_venue_id_provider_osm_type_osm_id" to table: "venue_candidates"
CREATE UNIQUE INDEX `venue_candidates_venue_id_provider_osm_type_osm_id` ON `venue_candidates` (`venue_id`, `provider`, `osm_type`, `osm_id`);
-- Create index "ix_venue_candidates_venue_id" to table: "venue_candidates"
CREATE INDEX `ix_venue_candidates_venue_id` ON `venue_candidates` (`venue_id`);
-- Create "event_venues" table
CREATE TABLE `event_venues` (
  `event_id` varchar NOT NULL,
  `venue_id` varchar NOT NULL,
  `source_name` varchar NOT NULL,
  PRIMARY KEY (`event_id`),
  CONSTRAINT `0` FOREIGN KEY (`venue_id`) REFERENCES `venues` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION,
  CONSTRAINT `1` FOREIGN KEY (`event_id`) REFERENCES `events` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "ix_event_venues_venue_id" to table: "event_venues"
CREATE INDEX `ix_event_venues_venue_id` ON `event_venues` (`venue_id`);
-- Create "artist_metadata" table
CREATE TABLE `artist_metadata` (
  `id` integer NOT NULL,
  `artist_id` varchar NOT NULL,
  `field` varchar NOT NULL,
  `value_json` json NOT NULL,
  `provider` varchar NOT NULL,
  `source_url` text NULL,
  `confidence` varchar NULL,
  `retrieved_at` datetime NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `0` FOREIGN KEY (`artist_id`) REFERENCES `artists` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "artist_metadata_artist_id_field_provider_source_url" to table: "artist_metadata"
CREATE UNIQUE INDEX `artist_metadata_artist_id_field_provider_source_url` ON `artist_metadata` (`artist_id`, `field`, `provider`, `source_url`);
-- Create index "ix_artist_metadata_artist_id" to table: "artist_metadata"
CREATE INDEX `ix_artist_metadata_artist_id` ON `artist_metadata` (`artist_id`);
-- Create "artist_candidates" table
CREATE TABLE `artist_candidates` (
  `id` integer NOT NULL,
  `artist_id` varchar NOT NULL,
  `provider` varchar NOT NULL,
  `source_url` text NOT NULL,
  `musicbrainz_id` varchar NOT NULL,
  `display_name` text NOT NULL,
  `artist_type` varchar NULL,
  `country` varchar NULL,
  `disambiguation` text NULL,
  `genres_json` json NOT NULL,
  `provider_score` integer NULL,
  `confidence` varchar NOT NULL,
  `retrieved_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `0` FOREIGN KEY (`artist_id`) REFERENCES `artists` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "artist_candidates_artist_id_provider_musicbrainz_id" to table: "artist_candidates"
CREATE UNIQUE INDEX `artist_candidates_artist_id_provider_musicbrainz_id` ON `artist_candidates` (`artist_id`, `provider`, `musicbrainz_id`);
-- Create index "ix_artist_candidates_artist_id" to table: "artist_candidates"
CREATE INDEX `ix_artist_candidates_artist_id` ON `artist_candidates` (`artist_id`);
-- Create "event_artists" table
CREATE TABLE `event_artists` (
  `event_id` varchar NOT NULL,
  `billing_order` integer NOT NULL,
  `artist_id` varchar NOT NULL,
  `source_name` varchar NOT NULL,
  `role` varchar NULL,
  PRIMARY KEY (`event_id`, `billing_order`),
  CONSTRAINT `0` FOREIGN KEY (`artist_id`) REFERENCES `artists` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION,
  CONSTRAINT `1` FOREIGN KEY (`event_id`) REFERENCES `events` (`id`) ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "ix_event_artists_artist_id" to table: "event_artists"
CREATE INDEX `ix_event_artists_artist_id` ON `event_artists` (`artist_id`);
