-- PostgreSQL initialization script
-- Runs once when the container is first created.
-- Sets up the database with correct permissions.

-- Ensure the database exists with proper encoding
-- (handled by POSTGRES_DB env var, this is just safety)

-- Grant necessary privileges
GRANT ALL PRIVILEGES ON DATABASE campusconnect TO campusconnect;

-- Note: The btree_gist extension is created by the Alembic migration.
-- We don't create it here because Alembic manages all schema changes.
