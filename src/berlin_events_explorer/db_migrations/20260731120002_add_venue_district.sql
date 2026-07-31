-- Add district metadata to canonical venues and cached candidates
ALTER TABLE `venues` ADD COLUMN `district` varchar NULL;
ALTER TABLE `venue_candidates` ADD COLUMN `district` varchar NULL;
