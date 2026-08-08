-- Store externally observed links/status separately from mutable source JSON.
CREATE TABLE `event_details` (
  `event_id` varchar NOT NULL,
  `provider` varchar NOT NULL,
  `event_url` text NULL,
  `ticket_url` text NULL,
  `observed_status` varchar NULL,
  `evidence_url` text NULL,
  `confidence` varchar NULL,
  `checked_at` datetime NOT NULL,
  `status_expires_at` datetime NULL,
  `last_successful_at` datetime NULL,
  `details_json` json NOT NULL,
  PRIMARY KEY (`event_id`),
  CONSTRAINT `fk_event_details_event` FOREIGN KEY (`event_id`) REFERENCES `events` (`id`) ON DELETE CASCADE
);
CREATE INDEX `ix_event_details_provider_checked_at` ON `event_details` (`provider`, `checked_at`);
