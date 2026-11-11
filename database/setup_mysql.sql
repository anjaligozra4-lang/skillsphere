CREATE DATABASE IF NOT EXISTS skillsphere_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'skillsphere'@'localhost' IDENTIFIED BY 'replace-with-a-local-password';
GRANT ALL PRIVILEGES ON skillsphere_db.* TO 'skillsphere'@'localhost';
FLUSH PRIVILEGES;

-- Run backend Alembic migrations after configuring backend/.env:
-- python -m alembic upgrade head
