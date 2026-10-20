CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    username TEXT NOT NULL UNIQUE CHECK (length(trim(username)) > 0),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('entry', 'manager', 'admin')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS reasons (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS waste_records (
    id INTEGER PRIMARY KEY,
    event_at TEXT NOT NULL CHECK (length(trim(event_at)) > 0),
    area_id INTEGER NOT NULL REFERENCES areas(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    reason_id INTEGER NOT NULL REFERENCES reasons(id),
    quantity_kg REAL NOT NULL CHECK (quantity_kg > 0),
    user_id INTEGER NOT NULL REFERENCES users(id),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_waste_records_event_at ON waste_records(event_at);
CREATE INDEX IF NOT EXISTS idx_waste_records_area_id ON waste_records(area_id);
CREATE INDEX IF NOT EXISTS idx_waste_records_category_id ON waste_records(category_id);
CREATE INDEX IF NOT EXISTS idx_waste_records_reason_id ON waste_records(reason_id);
