package db

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
)

const playbookEmbedDim = 256

// SemanticPlaybook represents a reusable tactical lesson, bypass, or CMS/tech exploitation
// pattern stored in PostgreSQL with pgvector cosine similarity + pg_trgm hybrid search.
type SemanticPlaybook struct {
	ID           int64     `json:"id"`
	Fingerprint  string    `json:"fingerprint"`
	Title        string    `json:"title"`
	TechTags     []string  `json:"tech_tags"`
	VulnClass    string    `json:"vuln_class"`
	Tactic       string    `json:"tactic"`
	PlaybookText string    `json:"playbook_text"`
	SourceKind   string    `json:"source_kind"` // finding | rsi_lesson | recon_pattern | manual
	SourceTaskID *int64    `json:"source_task_id,omitempty"`
	SuccessCount int       `json:"success_count"`
	Similarity   float64   `json:"similarity,omitempty"`
	CreatedAt    time.Time `json:"created_at"`
	UpdatedAt    time.Time `json:"updated_at"`
}

var knownTechTagPatterns = []struct {
	tag string
	re  *regexp.Regexp
}{
	{"wordpress", regexp.MustCompile(`(?i)\b(wordpress|wp-login|wp-admin|wp-content|wp-json|xmlrpc\.php)\b`)},
	{"laravel", regexp.MustCompile(`(?i)\b(laravel|xsrf-token|artisan|telescope|_ignition)\b`)},
	{"php", regexp.MustCompile(`(?i)\b(php|phpsessid|\.php)\b`)},
	{"custom-cms", regexp.MustCompile(`(?i)\b(custom\s+php|custom\s+cms|ewt)\b`)},
	{"jwt", regexp.MustCompile(`(?i)\b(jwt|json\s+web\s+token|hmac|bearer)\b`)},
	{"firebase", regexp.MustCompile(`(?i)\b(firebase|firestore|identitytoolkit)\b`)},
	{"cloudflare", regexp.MustCompile(`(?i)\b(cloudflare|cf-ray)\b`)},
	{"nginx", regexp.MustCompile(`(?i)\b(nginx)\b`)},
	{"apache", regexp.MustCompile(`(?i)\b(apache|tomcat|htaccess|cgi-bin)\b`)},
	{"python", regexp.MustCompile(`(?i)\b(python|django|flask|fastapi|simplehttp)\b`)},
	{"nodejs", regexp.MustCompile(`(?i)\b(node\.?js|express|next\.?js|nuxt)\b`)},
	{"ios-mobile", regexp.MustCompile(`(?i)\b(ios|ipa|nsallowsarbitraryloads|flutter|xcprivacy|android|apk)\b`)},
	{"idor-bac", regexp.MustCompile(`(?i)\b(idor|bola|bfla|broken\s+access|privilege\s+escalation|cwe-639|cwe-284)\b`)},
	{"xss", regexp.MustCompile(`(?i)\b(xss|cross-site\s+scripting|svg\s+upload|cwe-79)\b`)},
	{"sqli", regexp.MustCompile(`(?i)\b(sqli|sql\s+injection|sqlmap|union\s+select|cwe-89)\b`)},
	{"auth-session", regexp.MustCompile(`(?i)\b(auth\s*bypass|session\s+fixation|logout|cookie|cwe-287|cwe-613|cwe-384)\b`)},
	{"mass-assignment", regexp.MustCompile(`(?i)\b(mass\s+assignment|over-posting|cwe-915)\b`)},
	{"file-upload", regexp.MustCompile(`(?i)\b(file\s+upload|unrestricted\s+upload|webshell|cwe-434)\b`)},
	{"rate-limit", regexp.MustCompile(`(?i)\b(rate\s+limit|brute\s+force|credential\s+stuffing|cwe-307)\b`)},
	{"c2-infra", regexp.MustCompile(`(?i)\b(command-and-control|c2|dns\s+tunnel|beacon|cobalt)\b`)},
}

// ExtractTechTags identifies canonical technology and vulnerability-class tags from text.
func ExtractTechTags(texts ...string) []string {
	joined := strings.Join(texts, "\n")
	seen := map[string]bool{}
	var out []string
	for _, item := range knownTechTagPatterns {
		if item.re.MatchString(joined) && !seen[item.tag] {
			seen[item.tag] = true
			out = append(out, item.tag)
		}
	}
	sort.Strings(out)
	return out
}

func hashTokenFeature(tok string, salt uint32) (idx int, sign float64) {
	h := fnv.New64a()
	_, _ = h.Write([]byte{byte(salt), byte(salt >> 8)})
	_, _ = h.Write([]byte(tok))
	sum := h.Sum64()
	idx = int(sum % playbookEmbedDim)
	if (sum>>32)&1 == 1 {
		sign = 1.0
	} else {
		sign = -1.0
	}
	return idx, sign
}

// ComputePlaybookEmbedding256 builds a zero-RAM, deterministic L2-normalized 256-dim
// semantic feature vector over cyber tokens, word unigrams/bigrams, and multilingual
// character 3/4-grams (supporting both Thai & English) formatted as a pgvector literal.
func ComputePlaybookEmbedding256(text string) string {
	var vec [playbookEmbedDim]float64
	norm := strings.ToLower(strings.TrimSpace(text))
	if norm == "" {
		vec[0] = 1.0
		return formatVectorLiteral(vec[:])
	}

	// 1. Word & cyber-identifier tokens + bigrams (weighted higher for semantic specificity)
	var words []string
	var cur strings.Builder
	for _, r := range norm {
		if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' || r == '.' || r == '/' {
			cur.WriteRune(r)
		} else if cur.Len() > 0 {
			w := strings.Trim(cur.String(), "._-/")
			if len(w) >= 2 {
				words = append(words, w)
			}
			cur.Reset()
		}
	}
	if cur.Len() > 0 {
		w := strings.Trim(cur.String(), "._-/")
		if len(w) >= 2 {
			words = append(words, w)
		}
	}

	for i, w := range words {
		if i >= 600 {
			break
		}
		weight := 2.0
		if strings.HasPrefix(w, "cwe-") || strings.HasPrefix(w, "cve-") || strings.Contains(w, "wp-") {
			weight = 3.2
		}
		idx1, s1 := hashTokenFeature("w:"+w, 1)
		vec[idx1] += s1 * weight
		idx2, s2 := hashTokenFeature("w2:"+w, 2)
		vec[idx2] += s2 * (weight * 0.5)

		if i+1 < len(words) {
			bg := w + "_" + words[i+1]
			bidx, bs := hashTokenFeature("bg:"+bg, 3)
			vec[bidx] += bs * 1.6
		}
	}

	// 2. Multilingual character 3-grams (captures Thai phrases, partial paths, and tech stems)
	runes := []rune(norm)
	if len(runes) > 1200 {
		runes = runes[:1200]
	}
	for i := 0; i+3 <= len(runes); i++ {
		ng := string(runes[i : i+3])
		if strings.TrimSpace(ng) == "" {
			continue
		}
		idx, s := hashTokenFeature("c3:"+ng, 7)
		vec[idx] += s * 0.65
	}

	// 3. Canonical tech tags boost
	for _, tag := range ExtractTechTags(norm) {
		idx, s := hashTokenFeature("tag:"+tag, 11)
		vec[idx] += s * 3.8
	}

	// L2 normalize for cosine distance (<=>)
	var sumSq float64
	for _, v := range vec {
		sumSq += v * v
	}
	if sumSq > 1e-12 {
		inv := 1.0 / math.Sqrt(sumSq)
		for i := range vec {
			vec[i] *= inv
		}
	} else {
		vec[0] = 1.0
	}
	return formatVectorLiteral(vec[:])
}

func formatVectorLiteral(v []float64) string {
	var sb strings.Builder
	sb.Grow(len(v) * 9)
	sb.WriteByte('[')
	for i, x := range v {
		if i > 0 {
			sb.WriteByte(',')
		}
		sb.WriteString(strconv.FormatFloat(x, 'f', 5, 64))
	}
	sb.WriteByte(']')
	return sb.String()
}

// EnsurePlaybookMemorySchema enables pgvector + pg_trgm and creates semantic_playbooks.
func (d *DB) EnsurePlaybookMemorySchema() error {
	_, err := d.Exec(`
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS semantic_playbooks (
    id             BIGSERIAL PRIMARY KEY,
    fingerprint    TEXT NOT NULL UNIQUE,
    title          TEXT NOT NULL,
    tech_tags      TEXT[] NOT NULL DEFAULT '{}',
    vuln_class     TEXT NOT NULL DEFAULT '',
    tactic         TEXT NOT NULL DEFAULT '',
    playbook_text  TEXT NOT NULL,
    source_kind    TEXT NOT NULL DEFAULT 'finding',
    source_task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
    success_count  INTEGER NOT NULL DEFAULT 1,
    embedding      vector(256) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_semantic_playbooks_hnsw
    ON semantic_playbooks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_semantic_playbooks_tags
    ON semantic_playbooks USING gin (tech_tags);
CREATE INDEX IF NOT EXISTS idx_semantic_playbooks_trgm
    ON semantic_playbooks USING gin ((title || ' ' || playbook_text) gin_trgm_ops);
`)
	if err != nil {
		return err
	}
	// Best-effort initial backfill from existing findings, RSI lessons, and confirmed facts
	_, _ = d.SyncPlaybooksFromHistory(0)
	return nil
}

func computePlaybookFingerprint(sourceKind, title, body string) string {
	h := sha256.Sum256([]byte(strings.ToLower(strings.TrimSpace(sourceKind)) + "|" + normalizeFingerprintToken(title) + "|" + normalizeFingerprintToken(body)))
	return "pb_" + hex.EncodeToString(h[:12])
}

// UpsertSemanticPlaybook inserts or updates a semantic playbook entry with its pgvector embedding.
func (d *DB) UpsertSemanticPlaybook(in SemanticPlaybook) (*SemanticPlaybook, error) {
	title := strings.TrimSpace(in.Title)
	body := strings.TrimSpace(in.PlaybookText)
	if title == "" || body == "" {
		return nil, fmt.Errorf("title and playbook_text are required")
	}
	kind := strings.TrimSpace(in.SourceKind)
	if kind == "" {
		kind = "manual"
	}
	tags := in.TechTags
	autoTags := ExtractTechTags(title, in.VulnClass, in.Tactic, body)
	tagSet := map[string]bool{}
	var mergedTags []string
	for _, t := range append(tags, autoTags...) {
		clean := strings.ToLower(strings.TrimSpace(t))
		if clean != "" && !tagSet[clean] {
			tagSet[clean] = true
			mergedTags = append(mergedTags, clean)
		}
	}
	sort.Strings(mergedTags)

	fp := strings.TrimSpace(in.Fingerprint)
	if fp == "" {
		fp = computePlaybookFingerprint(kind, title, body)
	}
	emb := ComputePlaybookEmbedding256(title + "\n" + in.VulnClass + "\n" + strings.Join(mergedTags, " ") + "\n" + body)

	var out SemanticPlaybook
	var srcTask sql.NullInt64
	var rawTags string
	err := d.QueryRow(`
INSERT INTO semantic_playbooks (
    fingerprint, title, tech_tags, vuln_class, tactic, playbook_text, source_kind, source_task_id, embedding, updated_at
) VALUES ($1, $2, $3::text[], $4, $5, $6, $7, $8, $9::vector, now())
ON CONFLICT (fingerprint) DO UPDATE SET
    title          = EXCLUDED.title,
    tech_tags      = EXCLUDED.tech_tags,
    vuln_class     = CASE WHEN EXCLUDED.vuln_class <> '' THEN EXCLUDED.vuln_class ELSE semantic_playbooks.vuln_class END,
    tactic         = CASE WHEN EXCLUDED.tactic <> '' THEN EXCLUDED.tactic ELSE semantic_playbooks.tactic END,
    playbook_text  = EXCLUDED.playbook_text,
    source_task_id = COALESCE(EXCLUDED.source_task_id, semantic_playbooks.source_task_id),
    embedding      = EXCLUDED.embedding,
    updated_at     = now()
RETURNING id, fingerprint, title, array_to_json(tech_tags)::text, vuln_class, tactic, playbook_text, source_kind, source_task_id, success_count, created_at, updated_at
`, fp, title, mergedTags, strings.TrimSpace(in.VulnClass), strings.TrimSpace(in.Tactic), body, kind, in.SourceTaskID, emb).Scan(
		&out.ID, &out.Fingerprint, &out.Title, &rawTags, &out.VulnClass, &out.Tactic,
		&out.PlaybookText, &out.SourceKind, &srcTask, &out.SuccessCount, &out.CreatedAt, &out.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	_ = json.Unmarshal([]byte(rawTags), &out.TechTags)
	if out.TechTags == nil {
		out.TechTags = []string{}
	}
	if srcTask.Valid {
		v := srcTask.Int64
		out.SourceTaskID = &v
	}
	return &out, nil
}

// SearchSemanticPlaybooks executes hybrid pgvector cosine similarity + pg_trgm + tech_tag retrieval.
func (d *DB) SearchSemanticPlaybooks(query string, extraTags []string, limit int) ([]SemanticPlaybook, error) {
	if limit <= 0 || limit > 30 {
		limit = 6
	}
	q := strings.TrimSpace(query)
	if q == "" && len(extraTags) == 0 {
		rows, err := d.Query(`
SELECT id, fingerprint, title, array_to_json(tech_tags)::text, vuln_class, tactic, playbook_text, source_kind, source_task_id, success_count, 1.0::float8, created_at, updated_at
FROM semantic_playbooks
ORDER BY updated_at DESC
LIMIT $1`, limit)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		return scanPlaybookRows(rows)
	}

	tags := ExtractTechTags(q, strings.Join(extraTags, " "))
	for _, t := range extraTags {
		clean := strings.ToLower(strings.TrimSpace(t))
		if clean != "" {
			found := false
			for _, ex := range tags {
				if ex == clean {
					found = true
					break
				}
			}
			if !found {
				tags = append(tags, clean)
			}
		}
	}
	emb := ComputePlaybookEmbedding256(q + " " + strings.Join(tags, " "))

	rows, err := d.Query(`
SELECT
    id, fingerprint, title, array_to_json(tech_tags)::text, vuln_class, tactic, playbook_text, source_kind, source_task_id, success_count,
    LEAST(0.99, GREATEST(0.0,
        (1.0 - (embedding <=> $1::vector)) * 0.68 +
        similarity(title || ' ' || playbook_text, $2) * 0.22 +
        CASE WHEN cardinality($3::text[]) > 0 AND tech_tags && $3::text[] THEN 0.18 ELSE 0.0 END
    )) AS hybrid_score,
    created_at, updated_at
FROM semantic_playbooks
ORDER BY hybrid_score DESC, updated_at DESC
LIMIT $4
`, emb, q, tags, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanPlaybookRows(rows)
}

func scanPlaybookRows(rows *sql.Rows) ([]SemanticPlaybook, error) {
	var out []SemanticPlaybook
	for rows.Next() {
		var it SemanticPlaybook
		var srcTask sql.NullInt64
		var rawTags string
		if err := rows.Scan(
			&it.ID, &it.Fingerprint, &it.Title, &rawTags, &it.VulnClass, &it.Tactic,
			&it.PlaybookText, &it.SourceKind, &srcTask, &it.SuccessCount, &it.Similarity, &it.CreatedAt, &it.UpdatedAt,
		); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(rawTags), &it.TechTags)
		if it.TechTags == nil {
			it.TechTags = []string{}
		}
		if srcTask.Valid {
			v := srcTask.Int64
			it.SourceTaskID = &v
		}
		it.Similarity = math.Round(it.Similarity*1000) / 1000
		out = append(out, it)
	}
	if out == nil {
		out = []SemanticPlaybook{}
	}
	return out, nil
}

// CountSemanticPlaybooks returns total stored playbooks in pgvector.
func (d *DB) CountSemanticPlaybooks() int {
	var n int
	_ = d.QueryRow(`SELECT count(*) FROM semantic_playbooks`).Scan(&n)
	return n
}

// DeleteSemanticPlaybook deletes a playbook by ID.
func (d *DB) DeleteSemanticPlaybook(id int64) error {
	_, err := d.Exec(`DELETE FROM semantic_playbooks WHERE id = $1`, id)
	return err
}

// SyncPlaybooksFromHistory harvests non-noise findings, RSI lessons, and confirmed
// architectural/recon facts into pgvector semantic_playbooks so lessons persist across tasks.
func (d *DB) SyncPlaybooksFromHistory(taskID int64) (int, error) {
	synced := 0

	// 1. Harvest non-noise findings
	fQuery := `
SELECT id, task_id, vulnclass, name, severity, summary, evidence
FROM findings
WHERE triage_status <> 'noise' AND (length(summary) > 25 OR length(evidence) > 25)`
	var fRows *sql.Rows
	var err error
	if taskID > 0 {
		fRows, err = d.Query(fQuery+` AND task_id = $1 ORDER BY id DESC LIMIT 50`, taskID)
	} else {
		fRows, err = d.Query(fQuery + ` ORDER BY id DESC LIMIT 80`)
	}
	if err == nil {
		for fRows.Next() {
			var id int64
			var tid sql.NullInt64
			var vclass, name, sev, summary, ev string
			if fRows.Scan(&id, &tid, &vclass, &name, &sev, &summary, &ev) == nil {
				title := strings.TrimSpace(name)
				if title == "" {
					title = strings.Split(strings.TrimSpace(summary), "\n")[0]
					if len(title) > 110 {
						title = title[:110]
					}
				}
				if title == "" {
					title = vclass
				}
				body := strings.TrimSpace(summary)
				if strings.TrimSpace(ev) != "" {
					if len(ev) > 700 {
						ev = ev[:700]
					}
					body += "\nPoC / Verification Pattern: " + strings.TrimSpace(ev)
				}
				var srcPtr *int64
				if tid.Valid && tid.Int64 > 0 {
					v := tid.Int64
					srcPtr = &v
				}
				if _, uerr := d.UpsertSemanticPlaybook(SemanticPlaybook{
					Fingerprint:  fmt.Sprintf("pb_finding_%d", id),
					Title:        fmt.Sprintf("[%s] %s", strings.ToUpper(sev), title),
					VulnClass:    vclass,
					Tactic:       "Exploitation & Verification",
					PlaybookText: body,
					SourceKind:   "finding",
					SourceTaskID: srcPtr,
				}); uerr == nil {
					synced++
				}
			}
		}
		fRows.Close()
	}

	// 2. Harvest RSI lessons if present
	lRows, err := d.Query(`SELECT id, title, content FROM rsi_lessons ORDER BY id DESC LIMIT 40`)
	if err == nil {
		for lRows.Next() {
			var lid int64
			var title, content string
			if lRows.Scan(&lid, &title, &content) == nil && strings.TrimSpace(content) != "" {
				if _, uerr := d.UpsertSemanticPlaybook(SemanticPlaybook{
					Fingerprint:  fmt.Sprintf("pb_rsi_%d", lid),
					Title:        title,
					Tactic:       "Agent RSI Lesson",
					PlaybookText: content,
					SourceKind:   "rsi_lesson",
				}); uerr == nil {
					synced++
				}
			}
		}
		lRows.Close()
	}

	// 3. Harvest rich confirmed technical/CMS recon patterns from exploration_nodes
	nQuery := `
SELECT n.id, e.task_id, COALESCE(n.payload->>'detail', n.payload->>'summary', '') AS detail
FROM exploration_nodes n
LEFT JOIN explorations e ON e.id = n.exploration_id
WHERE n.kind = 'fact' AND n.state = 'confirmed'
  AND length(COALESCE(n.payload->>'detail', n.payload->>'summary', '')) >= 120`
	var nRows *sql.Rows
	if taskID > 0 {
		nRows, err = d.Query(nQuery+` AND e.task_id = $1 ORDER BY n.id DESC LIMIT 25`, taskID)
	} else {
		nRows, err = d.Query(nQuery + ` ORDER BY n.id DESC LIMIT 40`)
	}
	if err == nil {
		for nRows.Next() {
			var nid int64
			var tid sql.NullInt64
			var detail string
			if nRows.Scan(&nid, &tid, &detail) == nil {
				tags := ExtractTechTags(detail)
				if len(tags) == 0 {
					continue
				}
				firstLn := strings.TrimSpace(strings.Split(detail, "\n")[0])
				if len(firstLn) > 105 {
					firstLn = firstLn[:105]
				}
				if len(detail) > 900 {
					detail = detail[:900]
				}
				var srcPtr *int64
				if tid.Valid && tid.Int64 > 0 {
					v := tid.Int64
					srcPtr = &v
				}
				if _, uerr := d.UpsertSemanticPlaybook(SemanticPlaybook{
					Fingerprint:  fmt.Sprintf("pb_fact_%d", nid),
					Title:        "Tech & Defense Pattern: " + firstLn,
					TechTags:     tags,
					Tactic:       "Reconnaissance & Architecture Pattern",
					PlaybookText: detail,
					SourceKind:   "recon_pattern",
					SourceTaskID: srcPtr,
				}); uerr == nil {
					synced++
				}
			}
		}
		nRows.Close()
	}

	return synced, nil
}
