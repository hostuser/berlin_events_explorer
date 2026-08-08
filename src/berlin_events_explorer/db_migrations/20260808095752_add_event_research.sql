-- Store AI-assisted search observations separately from source/provider detail links.
CREATE TABLE `event_research` (
  `event_id` varchar NOT NULL,
  `provider` varchar NOT NULL,
  `event_url` text NOT NULL,
  `ticket_url` text NULL,
  `evidence_url` text NOT NULL,
  `summary` text NULL,
  `checked_at` datetime NOT NULL,
  PRIMARY KEY (`event_id`),
  CONSTRAINT `fk_event_research_event` FOREIGN KEY (`event_id`) REFERENCES `events` (`id`) ON DELETE CASCADE
);
CREATE INDEX `ix_event_research_provider_checked_at` ON `event_research` (`provider`, `checked_at`);
