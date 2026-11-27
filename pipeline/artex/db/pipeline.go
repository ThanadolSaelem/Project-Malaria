package db

import (
	"database/sql"
	"strings"
	"time"
)

// ConversationLink tracks cross-module artifacts (tasks, companies, ScopeSentry
// projects/scans) created or attached from a /chat conversation.
type ConversationLink struct {
	ID                   int64     `json:"id"`
	ConversationID       int64     `json:"conversation_id"`
	TaskID               *int64    `json:"task_id,omitempty"`
	CompanyID            *int64    `json:"company_id,omitempty"`
	ScopeSentryProjectID string    `json:"scopesentry_project_id,omitempty"`
	ScopeSentryTaskID    string    `json:"scopesentry_task_id,omitempty"`
	Target               string    `json:"target,omitempty"`
	CreatedAt            time.Time `json:"created_at"`
}

// EnsurePipelineTables idempotently creates tables required by the cross-module
// pipeline integration so existing databases upgrade cleanly in place.
func (d *DB) EnsurePipelineTables() error {
	_, err := d.Exec(`
CREATE TABLE IF NOT EXISTS conversation_links (
    id                     BIGSERIAL PRIMARY KEY,
    conversation_id        BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    task_id                BIGINT REFERENCES tasks(id) ON DELETE CASCADE,
    company_id             BIGINT REFERENCES companies(id) ON DELETE SET NULL,
    scopesentry_project_id TEXT NOT NULL DEFAULT '',
    scopesentry_task_id    TEXT NOT NULL DEFAULT '',
    target                 TEXT NOT NULL DEFAULT '',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_conv_links_conv ON conversation_links(conversation_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_links_conv_task ON conversation_links(conversation_id, task_id)
    WHERE task_id IS NOT NULL;
`)
	if err != nil {
		return err
	}
	if err := d.EnsureEnterpriseTables(); err != nil {
		return err
	}
	if perr := d.EnsurePlaybookMemorySchema(); perr != nil {
		// Log-friendly non-fatal fallback if pgvector extension isn't installed yet on an external DB
		_ = perr
	}
	return nil
}

// UpsertConversationLink records or updates a cross-module link for convID.
func (d *DB) UpsertConversationLink(link ConversationLink) error {
	if link.ConversationID <= 0 {
		return nil
	}
	target := strings.TrimSpace(link.Target)
	ssProj := strings.TrimSpace(link.ScopeSentryProjectID)
	ssTask := strings.TrimSpace(link.ScopeSentryTaskID)

	if link.TaskID != nil && *link.TaskID > 0 {
		_, err := d.Exec(`
INSERT INTO conversation_links (conversation_id, task_id, company_id, scopesentry_project_id, scopesentry_task_id, target)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (conversation_id, task_id) WHERE task_id IS NOT NULL DO UPDATE
SET company_id             = COALESCE(EXCLUDED.company_id, conversation_links.company_id),
    scopesentry_project_id = CASE WHEN EXCLUDED.scopesentry_project_id <> '' THEN EXCLUDED.scopesentry_project_id ELSE conversation_links.scopesentry_project_id END,
    scopesentry_task_id    = CASE WHEN EXCLUDED.scopesentry_task_id <> '' THEN EXCLUDED.scopesentry_task_id ELSE conversation_links.scopesentry_task_id END,
    target                 = CASE WHEN EXCLUDED.target <> '' THEN EXCLUDED.target ELSE conversation_links.target END`,
			link.ConversationID, *link.TaskID, link.CompanyID, ssProj, ssTask, target)
		return err
	}

	_, err := d.Exec(`
INSERT INTO conversation_links (conversation_id, task_id, company_id, scopesentry_project_id, scopesentry_task_id, target)
VALUES ($1, NULL, $2, $3, $4, $5)`,
		link.ConversationID, link.CompanyID, ssProj, ssTask, target)
	return err
}

// ListConversationLinks returns all recorded cross-module links for a conversation, newest first.
func (d *DB) ListConversationLinks(convID int64) ([]ConversationLink, error) {
	if convID <= 0 {
		return nil, nil
	}
	rows, err := d.Query(`
SELECT id, conversation_id, task_id, company_id, scopesentry_project_id, scopesentry_task_id, target, created_at
FROM conversation_links
WHERE conversation_id = $1
ORDER BY created_at DESC, id DESC`, convID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ConversationLink{}
	for rows.Next() {
		var l ConversationLink
		var tid, cid sql.NullInt64
		if err := rows.Scan(&l.ID, &l.ConversationID, &tid, &cid, &l.ScopeSentryProjectID, &l.ScopeSentryTaskID, &l.Target, &l.CreatedAt); err != nil {
			return nil, err
		}
		if tid.Valid {
			v := tid.Int64
			l.TaskID = &v
		}
		if cid.Valid {
			v := cid.Int64
			l.CompanyID = &v
		}
		out = append(out, l)
	}
	return out, rows.Err()
}

// SyncTaskCompanyAssets attaches newly discovered assets owned by any of the task's
// linked company scopes (task_scope kind='company') onto the task idempotently.
func (d *DB) SyncTaskCompanyAssets(taskID int64) (int64, error) {
	if taskID <= 0 {
		return 0, nil
	}
	tx, err := d.Begin()
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	if err := lockCompanyScopeMutation(tx); err != nil {
		return 0, err
	}
	var added int64
	err = tx.QueryRow(`
WITH matched AS (
    SELECT a.id, c.name AS company_name
    FROM assets a
    JOIN companies c ON c.id = a.company_id
    JOIN task_scope ts ON ts.kind = 'company' AND ts.company_id = a.company_id AND ts.task_id = $1
    WHERE NOT ($1 = ANY(a.task_ids))
), upd AS (
    UPDATE assets a
    SET task_ids = array_append(a.task_ids, $1)
    FROM matched m
    WHERE a.id = m.id
    RETURNING a.id
), linked AS (
    INSERT INTO task_asset_links(task_id, asset_id, source, source_summary)
    SELECT $1, m.id, $2, 'synced from company scope: ' || m.company_name
    FROM matched m
    ON CONFLICT (task_id, asset_id) DO NOTHING
)
SELECT count(*) FROM upd`, taskID, taskCompanyAssetSource).Scan(&added)
	if err != nil {
		return 0, err
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return added, nil
}

// ListTaskScopeSentryLinks returns active (non-deleted) task-linked ScopeSentry
// mappings newest first for background ASM synchronization.
func (d *DB) ListTaskScopeSentryLinks() ([]ConversationLink, error) {
	rows, err := d.Query(`
SELECT DISTINCT ON (cl.task_id, cl.scopesentry_project_id)
       cl.id, cl.conversation_id, cl.task_id, cl.company_id,
       cl.scopesentry_project_id, cl.scopesentry_task_id, cl.target, cl.created_at
FROM conversation_links cl
JOIN tasks t ON t.id = cl.task_id
WHERE cl.task_id IS NOT NULL
  AND t.deleted_at IS NULL
  AND (cl.scopesentry_project_id <> '' OR cl.scopesentry_task_id <> '')
ORDER BY cl.task_id DESC, cl.scopesentry_project_id, cl.created_at DESC, cl.id DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ConversationLink{}
	for rows.Next() {
		var l ConversationLink
		var tid, cid sql.NullInt64
		if err := rows.Scan(&l.ID, &l.ConversationID, &tid, &cid, &l.ScopeSentryProjectID, &l.ScopeSentryTaskID, &l.Target, &l.CreatedAt); err != nil {
			return nil, err
		}
		if tid.Valid {
			v := tid.Int64
			l.TaskID = &v
		}
		if cid.Valid {
			v := cid.Int64
			l.CompanyID = &v
		}
		out = append(out, l)
	}
	return out, rows.Err()
}
