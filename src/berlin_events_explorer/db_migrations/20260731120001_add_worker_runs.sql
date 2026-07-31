-- Create "worker_runs" table
CREATE TABLE `worker_runs` (
  `id` integer NOT NULL,
  `started_at` datetime NOT NULL,
  `finished_at` datetime NULL,
  `status` varchar NOT NULL,
  `error` text NULL,
  `summary_json` json NOT NULL,
  PRIMARY KEY (`id`)
);
-- Create index "ix_worker_runs_started_at" to table: "worker_runs"
CREATE INDEX `ix_worker_runs_started_at` ON `worker_runs` (`started_at`);
-- Create index "ix_worker_runs_status" to table: "worker_runs"
CREATE INDEX `ix_worker_runs_status` ON `worker_runs` (`status`);
