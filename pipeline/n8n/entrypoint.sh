#!/bin/sh
# =============================================================================
# n8n Entrypoint — Auto-Sync Project-Malaria Credentials, Workflows & Ownership
# =============================================================================
set -eu

N8N_USER_DIR="${N8N_USER_FOLDER:-/home/node/.n8n}"
DB_FILE="$N8N_USER_DIR/database.sqlite"
mkdir -p "$N8N_USER_DIR"

grant_n8n_ownership() {
  [ -f "$DB_FILE" ] || return 0
  node - "$DB_FILE" <<'EOF' 2>/dev/null || true
const dbFile = process.argv[2];
const paths = [
  'sqlite3',
  '/usr/local/lib/node_modules/n8n/node_modules/sqlite3',
  '/usr/local/lib/node_modules/n8n/node_modules/@n8n/db/node_modules/sqlite3',
];
let sqlite3 = null;
for (const p of paths) {
  try { sqlite3 = require(p); break; } catch (_) {}
}
if (!sqlite3) process.exit(0);
const db = new sqlite3.Database(dbFile);
db.serialize(() => {
  db.run(`
    INSERT OR IGNORE INTO shared_credentials (credentialsId, projectId, role, createdAt, updatedAt)
    SELECT c.id, p.id, 'credential:owner', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    FROM credentials_entity c CROSS JOIN project p
    WHERE p.type = 'personal';
  `);
  db.run(`
    INSERT OR IGNORE INTO shared_workflow (workflowId, projectId, role, createdAt, updatedAt)
    SELECT w.id, p.id, 'workflow:owner', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    FROM workflow_entity w CROSS JOIN project p
    WHERE p.type = 'personal';
  `);
  db.run(`
    UPDATE workflow_entity SET active = 1 WHERE id = 'malaria-dual-brain-relay';
  `);
});
db.close();
EOF
}

echo "[n8n-bootstrap] Syncing LiteLLM Gateway credential and Project-Malaria Node Workflows..."
if [ -d "/seed/credentials" ]; then
  n8n import:credentials --separate --input=/seed/credentials/ 2>/dev/null || true
fi
if [ -d "/seed/workflows" ]; then
  n8n import:workflow --separate --input=/seed/workflows/ 2>/dev/null || true
  n8n update:workflow --id=malaria-dual-brain-relay --active=true 2>/dev/null || true
fi
grant_n8n_ownership
echo "[n8n-bootstrap] ✓ Synced Project-Malaria Workflows & Credential Ownership"

# Background watcher: auto-grant credential & workflow ownership after first-time user signup
(
  i=0
  while [ "$i" -lt 60 ]; do
    sleep 5
    grant_n8n_ownership
    i=$((i + 1))
  done
) &

exec n8n start
