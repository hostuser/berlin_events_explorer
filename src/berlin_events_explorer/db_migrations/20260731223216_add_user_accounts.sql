-- Create "users" table
CREATE TABLE `users` (
  `id` integer NOT NULL,
  `email` varchar NOT NULL,
  `password_hash` varchar NOT NULL,
  `display_name` varchar NOT NULL,
  `role` varchar NOT NULL,
  `is_active` integer NOT NULL DEFAULT 1,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `last_login_at` datetime NULL,
  PRIMARY KEY (`id`)
);
-- Create index "uq_users_email" to table: "users"
CREATE UNIQUE INDEX `uq_users_email` ON `users` (`email`);
-- Create "auth_tokens" table
CREATE TABLE `auth_tokens` (
  `id` integer NOT NULL,
  `purpose` varchar NOT NULL,
  `token_hash` varchar NOT NULL,
  `email` varchar NOT NULL,
  `role` varchar NULL,
  `user_id` integer NULL,
  `created_by` integer NULL,
  `created_at` datetime NOT NULL,
  `expires_at` datetime NOT NULL,
  `used_at` datetime NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `fk_auth_tokens_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_auth_tokens_created_by` FOREIGN KEY (`created_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
);
-- Create index "uq_auth_tokens_token_hash" to table: "auth_tokens"
CREATE UNIQUE INDEX `uq_auth_tokens_token_hash` ON `auth_tokens` (`token_hash`);
-- Create index "ix_auth_tokens_purpose" to table: "auth_tokens"
CREATE INDEX `ix_auth_tokens_purpose` ON `auth_tokens` (`purpose`);
-- Create "user_settings" table
CREATE TABLE `user_settings` (
  `user_id` integer NOT NULL,
  `key` varchar NOT NULL,
  `value_json` json NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`user_id`, `key`),
  CONSTRAINT `fk_user_settings_user_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
);
