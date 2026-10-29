-- Schema from the audited 1.0 release (1e667f0), without user data.
CREATE TABLE projects(
          slug TEXT PRIMARY KEY, name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active', progress INTEGER NOT NULL DEFAULT 0,
          summary TEXT NOT NULL DEFAULT '', next_step TEXT NOT NULL DEFAULT '',
          links TEXT NOT NULL DEFAULT '[]', archived INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, github_repo TEXT NOT NULL DEFAULT '', gh_synced_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE updates(
          id INTEGER PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(slug) ON DELETE CASCADE ON UPDATE CASCADE,
          ts INTEGER NOT NULL, author TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'note',
          text TEXT NOT NULL, link TEXT NOT NULL DEFAULT '');
CREATE INDEX updates_project_ts ON updates(project, ts DESC);
CREATE TABLE cards(
          id INTEGER PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(slug) ON DELETE CASCADE ON UPDATE CASCADE,
          title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', col TEXT NOT NULL DEFAULT 'todo',
          position INTEGER NOT NULL DEFAULT 0, link TEXT NOT NULL DEFAULT '',
          block_owner TEXT NOT NULL DEFAULT '', block_reason TEXT NOT NULL DEFAULT '',
          created_by TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
          done_at INTEGER);
CREATE INDEX cards_project_col ON cards(project, col, position);
CREATE TABLE notes(
              id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
              tags TEXT NOT NULL DEFAULT '[]', project TEXT REFERENCES projects(slug) ON DELETE SET NULL ON UPDATE CASCADE,
              pinned INTEGER NOT NULL DEFAULT 0, private INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
CREATE VIRTUAL TABLE notes_fts USING fts5(title, body, tags, content='notes', content_rowid='id',
              tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
              INSERT INTO notes_fts(rowid,title,body,tags) VALUES(new.id,new.title,new.body,new.tags); END;
CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
              INSERT INTO notes_fts(notes_fts,rowid,title,body,tags) VALUES('delete',old.id,old.title,old.body,old.tags); END;
CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
              INSERT INTO notes_fts(notes_fts,rowid,title,body,tags) VALUES('delete',old.id,old.title,old.body,old.tags);
              INSERT INTO notes_fts(rowid,title,body,tags) VALUES(new.id,new.title,new.body,new.tags); END;
CREATE TABLE todos(
              id INTEGER PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open', priority INTEGER NOT NULL DEFAULT 2,
              due_date TEXT, due_time TEXT,
              project TEXT REFERENCES projects(slug) ON DELETE SET NULL ON UPDATE CASCADE,
              private INTEGER NOT NULL DEFAULT 0, card_id INTEGER, created_by TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, done_at INTEGER);
CREATE INDEX todos_status_due ON todos(status, due_date);
CREATE TABLE reminders(
              id INTEGER PRIMARY KEY, text TEXT NOT NULL, at INTEGER NOT NULL, repeat TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending', todo_id INTEGER REFERENCES todos(id) ON DELETE SET NULL,
              project TEXT REFERENCES projects(slug) ON DELETE SET NULL ON UPDATE CASCADE,
              private INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
              last_fired_at INTEGER, fire_count INTEGER NOT NULL DEFAULT 0);
CREATE INDEX reminders_due ON reminders(status, at);
CREATE TABLE notifications(
              id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
              body TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '', project TEXT,
              read INTEGER NOT NULL DEFAULT 0, delivered INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
CREATE INDEX notifications_ts ON notifications(ts DESC);
CREATE TABLE memory_entities(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, type TEXT NOT NULL DEFAULT 'general',
              updated_at INTEGER NOT NULL);
CREATE TABLE memory_facts(
              id INTEGER PRIMARY KEY, entity_id INTEGER NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
              text TEXT NOT NULL, added_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
PRAGMA user_version=4;
