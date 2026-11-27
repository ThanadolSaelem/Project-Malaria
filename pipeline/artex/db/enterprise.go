package db

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

// Enterprise Governance models inspired by HCL AppScan 360:
//   1. Finding Fingerprint Hash & Cross-Run Lifecycle (new/open/in_progress/noise/fixed/reopened)
//   2. Control-Plane Quality Gate (Engine != Ready, structured Exit Codes)
//   3. Root-Cause FixGroup Aggregation (FixLocation / OpenSourceLib / ApiEndpoint / SecurityControl)
//   4. Scan Operation Modes & Incremental Reference Baselines
//   5. Reusable Scan Context Bundles (Auth / OpenAPI / Postman / TestPolicy)

var (
	reCVE         = regexp.MustCompile(`(?i)\bCVE-\d{4}-\d{4,7}\b`)
	reURLPath     = regexp.MustCompile(`https?://[^\s"'<>]+`)
	reFilePath    = regexp.MustCompile(`(?:^|[\s"'(\[])((?:/workspace|/app|/var|/etc|[A-Za-z0-9_.-]+/)[A-Za-z0-9_./-]+\.(?:py|js|ts|tsx|go|php|sh|rb|java|cs|c|cpp|yml|yaml|json|xml|sql|conf|env|html))`)
	reMultiSpace  = regexp.MustCompile(`\s+`)
	reVolatileHex = regexp.MustCompile(`\b[0-9a-f]{16,}\b|\b\d{5,}\b`)
)

// EnterpriseFinding extends a persisted finding row with fingerprint, cross-run triage,
// FixGroup ownership, VEX status, and extracted CVE identifiers.
type EnterpriseFinding struct {
	ID               int64     `json:"id"`
	TaskID           *int64    `json:"task_id,omitempty"`
	NodeID           *int64    `json:"node_id,omitempty"`
	VulnClass        string    `json:"vulnclass"`
	Name             string    `json:"name"`
	Severity         string    `json:"severity"`
	Summary          string    `json:"summary"`
	Evidence         string    `json:"evidence"`
	Status           string    `json:"status"`
	Fingerprint      string    `json:"fingerprint"`
	TriageStatus     string    `json:"triage_status"`
	TriageNote       string    `json:"triage_note"`
	FixGroupKey      string    `json:"fix_group_key"`
	FixGroupType     string    `json:"fix_group_type"`
	FixGroupSubject  string    `json:"fix_group_subject"`
	VexStatus        string    `json:"vex_status"`
	VexJustification string    `json:"vex_justification"`
	FirstSeenTaskID  *int64    `json:"first_seen_task_id,omitempty"`
	LastSeenTaskID   *int64    `json:"last_seen_task_id,omitempty"`
	SeenCount        int       `json:"seen_count"`
	CVEs             []string  `json:"cves,omitempty"`
	CreatedAt        time.Time `json:"created_at"`
}

// FixGroupSummary aggregates multiple findings sharing the same remediation root cause.
type FixGroupSummary struct {
	FixGroupKey     string   `json:"fix_group_key"`
	Type            string   `json:"type"`
	Subject         string   `json:"subject"`
	HighestSeverity string   `json:"highest_severity"`
	TotalCount      int      `json:"total_count"`
	ActiveCount     int      `json:"active_count"`
	NoiseCount      int      `json:"noise_count"`
	FixedCount      int      `json:"fixed_count"`
	CVEs            []string `json:"cves,omitempty"`
	FindingIDs      []int64  `json:"finding_ids"`
	VulnClasses     []string `json:"vuln_classes"`
	RemediationHint string   `json:"remediation_hint"`
}

// CorrelationResult summarizes cross-run delta counts for a task or workspace.
type CorrelationResult struct {
	TaskID           int64 `json:"task_id"`
	BaselineTaskID   int64 `json:"baseline_task_id,omitempty"`
	Total            int   `json:"total"`
	NewCount         int   `json:"new_count"`
	OpenCount        int   `json:"open_count"`
	InProgressCount  int   `json:"in_progress_count"`
	ReopenedCount    int   `json:"reopened_count"`
	NoiseCount       int   `json:"noise_count"`
	FixedCount       int   `json:"fixed_count"`
	AutoSuppressed   int   `json:"auto_suppressed_noise"`
	AutoMarkedFixed  int   `json:"auto_marked_fixed"`
	FixGroupCount    int   `json:"fix_group_count"`
}

// GateCheckItem records one deterministic Control-Plane Quality Gate assertion.
type GateCheckItem struct {
	Name   string `json:"name"`
	Passed bool   `json:"passed"`
	Detail string `json:"detail"`
}

// TaskQualityGate stores the authoritative Control-Plane completion verdict (Engine != Ready).
type TaskQualityGate struct {
	TaskID      int64           `json:"task_id"`
	GateStatus  string          `json:"gate_status"` // pending | ready | ready_incomplete | pending_support | failed
	ExitCode    string          `json:"exit_code"`   // Success | FailureToLogin | WAFBlocked | UntestedAssetsRemaining | InsufficientEvidence | GoalsIncomplete | ManualStop
	ExitReason  string          `json:"exit_reason"`
	Checks      []GateCheckItem `json:"checks"`
	EvaluatedBy string          `json:"evaluated_by"`
	EvaluatedAt time.Time       `json:"evaluated_at"`
}

// TaskScanProfile tracks AppScan-style ScanOperation mode, incremental baseline, and attached bundle.
type TaskScanProfile struct {
	TaskID              int64            `json:"task_id"`
	ScanMode            string           `json:"scan_mode"` // full | explore_only | test_only | retest | report_only
	BaselineTaskID      int64            `json:"baseline_task_id,omitempty"`
	BundleID            int64            `json:"bundle_id,omitempty"`
	IsReferenceBaseline bool             `json:"is_reference_baseline"`
	PhaseTimings        map[string]int64 `json:"phase_timings,omitempty"`
	UpdatedAt           time.Time        `json:"updated_at"`
}

// ReferenceBaselineItem is a lightweight descriptor of a saved baseline scan task.
type ReferenceBaselineItem struct {
	TaskID       int64  `json:"task_id"`
	Name         string `json:"name"`
	Description  string `json:"description"`
	ScanMode     string `json:"scan_mode"`
	AssetCount   int    `json:"asset_count"`
	FindingCount int    `json:"finding_count"`
}

// ScanContextBundle stores reusable authentication, OpenAPI/Postman specs, and test policy rules.
type ScanContextBundle struct {
	ID            int64          `json:"id"`
	Name          string         `json:"name"`
	TargetPattern string         `json:"target_pattern"`
	CompanyID     *int64         `json:"company_id,omitempty"`
	AuthType      string         `json:"auth_type"` // none | api_key | bearer_token | cookie_session | login_sequence
	AuthConfig    map[string]any `json:"auth_config"`
	OpenAPIPath   string         `json:"openapi_path"`
	PostmanPath   string         `json:"postman_path"`
	TestPolicy    string         `json:"test_policy"` // standard | fast_passive | owasp_api_top10 | owasp_web_full | code_script_audit
	ExcludePaths  []string       `json:"exclude_paths"`
	RateLimitRPS  int            `json:"rate_limit_rps"`
	Notes         string         `json:"notes"`
	CreatedAt     time.Time      `json:"created_at"`
	UpdatedAt     time.Time      `json:"updated_at"`
}

// EnsureEnterpriseTables idempotently adds AppScan-inspired governance columns and tables.
func (d *DB) EnsureEnterpriseTables() error {
	_, err := d.Exec(`
ALTER TABLE findings ADD COLUMN IF NOT EXISTS fingerprint       TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS triage_status     TEXT NOT NULL DEFAULT 'new';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS triage_note       TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS fix_group_key     TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS fix_group_type    TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS fix_group_subject TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS vex_status        TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS vex_justification TEXT NOT NULL DEFAULT '';
ALTER TABLE findings ADD COLUMN IF NOT EXISTS first_seen_task_id BIGINT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS last_seen_task_id  BIGINT;
ALTER TABLE findings ADD COLUMN IF NOT EXISTS seen_count         INT NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_findings_fingerprint ON findings(fingerprint) WHERE fingerprint <> '';
CREATE INDEX IF NOT EXISTS idx_findings_triage ON findings(triage_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_findings_fix_group ON findings(fix_group_key) WHERE fix_group_key <> '';

CREATE TABLE IF NOT EXISTS task_quality_gates (
    task_id      BIGINT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    gate_status  TEXT NOT NULL DEFAULT 'pending',
    exit_code    TEXT NOT NULL DEFAULT 'Pending',
    exit_reason  TEXT NOT NULL DEFAULT '',
    checks_json  JSONB NOT NULL DEFAULT '[]',
    evaluated_by TEXT NOT NULL DEFAULT 'control_plane',
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scan_context_bundles (
    id               BIGSERIAL PRIMARY KEY,
    name             TEXT NOT NULL,
    target_pattern   TEXT NOT NULL DEFAULT '',
    company_id       BIGINT REFERENCES companies(id) ON DELETE SET NULL,
    auth_type        TEXT NOT NULL DEFAULT 'none',
    auth_config_json JSONB NOT NULL DEFAULT '{}',
    openapi_path     TEXT NOT NULL DEFAULT '',
    postman_path     TEXT NOT NULL DEFAULT '',
    test_policy      TEXT NOT NULL DEFAULT 'standard',
    exclude_paths    JSONB NOT NULL DEFAULT '[]',
    rate_limit_rps   INTEGER NOT NULL DEFAULT 5,
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS task_scan_profiles (
    task_id               BIGINT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    scan_mode             TEXT NOT NULL DEFAULT 'full',
    baseline_task_id      BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
    bundle_id             BIGINT REFERENCES scan_context_bundles(id) ON DELETE SET NULL,
    is_reference_baseline BOOLEAN NOT NULL DEFAULT false,
    phase_timings_json    JSONB NOT NULL DEFAULT '{}',
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
`)
	return err
}

// ExtractCVEs returns sorted unique uppercase CVE identifiers found across text fields.
func ExtractCVEs(texts ...string) []string {
	seen := map[string]bool{}
	var out []string
	for _, t := range texts {
		for _, m := range reCVE.FindAllString(t, -1) {
			up := strings.ToUpper(strings.TrimSpace(m))
			if up != "" && !seen[up] {
				seen[up] = true
				out = append(out, up)
			}
		}
	}
	sort.Strings(out)
	return out
}

func normalizeFingerprintToken(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	s = reVolatileHex.ReplaceAllString(s, "<id>")
	s = reMultiSpace.ReplaceAllString(s, " ")
	if len(s) > 180 {
		s = s[:180]
	}
	return s
}

func extractPrimaryLocation(summary, evidence string) (kind string, loc string) {
	combined := summary + "\n" + evidence
	if cves := ExtractCVEs(combined); len(cves) > 0 {
		return "OpenSourceLib", cves[0]
	}
	if m := reFilePath.FindStringSubmatch(combined); len(m) >= 2 {
		return "FixLocation", strings.TrimSpace(m[1])
	}
	if u := reURLPath.FindString(combined); u != "" {
		// Strip query parameter values to group by endpoint route
		if q := strings.IndexByte(u, '?'); q > 0 {
			u = u[:q]
		}
		u = strings.TrimRight(u, ".,;)")
		return "ApiEndpoint", u
	}
	return "SecurityControl", ""
}

// ComputeFindingFingerprint produces a stable cross-run SHA-256[:24] fingerprint.
func ComputeFindingFingerprint(vulnclass, name, summary, evidence string) string {
	_, loc := extractPrimaryLocation(summary, evidence)
	vc := normalizeFingerprintToken(vulnclass)
	nm := normalizeFingerprintToken(name)
	if nm == "" {
		nm = normalizeFingerprintToken(summary)
	}
	canonical := fmt.Sprintf("v1|%s|%s|%s", vc, nm, strings.ToLower(strings.TrimSpace(loc)))
	sum := sha256.Sum256([]byte(canonical))
	return hex.EncodeToString(sum[:12])
}

// ComputeFixGroup maps a finding to an AppScan-style Root-Cause FixGroup.
func ComputeFixGroup(vulnclass, name, summary, evidence string) (key, groupType, subject string) {
	locKind, loc := extractPrimaryLocation(summary, evidence)
	vc := strings.TrimSpace(vulnclass)
	if vc == "" {
		vc = strings.TrimSpace(name)
	}
	if vc == "" {
		vc = "General Security Weakness"
	}
	switch locKind {
	case "OpenSourceLib":
		return "lib:" + strings.ToLower(loc), "OpenSourceLib", fmt.Sprintf("Upgrade / Patch %s (%s)", loc, vc)
	case "FixLocation":
		return "file:" + strings.ToLower(loc) + ":" + strings.ToLower(vc), "FixLocation", fmt.Sprintf("Fix %s in %s", vc, loc)
	case "ApiEndpoint":
		return "api:" + strings.ToLower(loc) + ":" + strings.ToLower(vc), "ApiEndpoint", fmt.Sprintf("Harden %s (%s)", loc, vc)
	default:
		normVC := strings.ToLower(reMultiSpace.ReplaceAllString(vc, "_"))
		return "ctrl:" + normVC, "SecurityControl", fmt.Sprintf("Remediate %s", vc)
	}
}

func severityRank(s string) int {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "critical":
		return 0
	case "high":
		return 1
	case "medium":
		return 2
	case "low":
		return 3
	default:
		return 4
	}
}

func mapLegacyStatusToTriage(legacy string) string {
	switch strings.ToLower(strings.TrimSpace(legacy)) {
	case "false_positive", "ignored", "duplicate":
		return "noise"
	case "fixed", "resolved":
		return "fixed"
	case "in_progress":
		return "in_progress"
	case "confirmed":
		return "open"
	default:
		return "new"
	}
}

func mapTriageToLegacyStatus(triage string) string {
	switch strings.ToLower(strings.TrimSpace(triage)) {
	case "noise":
		return "false_positive"
	case "fixed":
		return "fixed"
	case "in_progress":
		return "in_progress"
	case "open", "reopened":
		return "confirmed"
	default:
		return "pending"
	}
}

// BackfillFindingFingerprints ensures every finding row has a fingerprint and FixGroup populated.
func (d *DB) BackfillFindingFingerprints() error {
	rows, err := d.Query(`
		SELECT id, task_id, vulnclass, name, summary, evidence, status, fingerprint, triage_status, fix_group_key
		FROM findings
		WHERE fingerprint = '' OR fix_group_key = '' OR first_seen_task_id IS NULL`)
	if err != nil {
		return err
	}
	type rowItem struct {
		id         int64
		taskID     sql.NullInt64
		vulnclass  string
		name       string
		summary    string
		evidence   string
		status     string
		fp         string
		triage     string
		fgKey      string
	}
	var items []rowItem
	for rows.Next() {
		var r rowItem
		if rows.Scan(&r.id, &r.taskID, &r.vulnclass, &r.name, &r.summary, &r.evidence, &r.status, &r.fp, &r.triage, &r.fgKey) == nil {
			items = append(items, r)
		}
	}
	rows.Close()

	for _, r := range items {
		fp := r.fp
		if fp == "" {
			fp = ComputeFindingFingerprint(r.vulnclass, r.name, r.summary, r.evidence)
		}
		fgKey, fgType, fgSubj := ComputeFixGroup(r.vulnclass, r.name, r.summary, r.evidence)
		if r.fgKey != "" {
			fgKey = r.fgKey
		}
		triage := strings.TrimSpace(r.triage)
		if triage == "" || triage == "new" {
			triage = mapLegacyStatusToTriage(r.status)
		}
		var tidPtr any
		if r.taskID.Valid {
			tidPtr = r.taskID.Int64
		}
		_, _ = d.Exec(`
			UPDATE findings
			SET fingerprint = $2,
			    fix_group_key = $3,
			    fix_group_type = CASE WHEN fix_group_type = '' THEN $4 ELSE fix_group_type END,
			    fix_group_subject = CASE WHEN fix_group_subject = '' THEN $5 ELSE fix_group_subject END,
			    triage_status = $6,
			    first_seen_task_id = COALESCE(first_seen_task_id, $7),
			    last_seen_task_id = COALESCE(last_seen_task_id, $7)
			WHERE id = $1`,
			r.id, fp, fgKey, fgType, fgSubj, triage, tidPtr)
	}
	return nil
}

// CorrelateTaskFindings performs AppScan-style cross-run correlation for taskID:
//   - Backfills fingerprints & FixGroups
//   - Suppresses findings whose fingerprint was previously marked 'noise'
//   - Marks recurring previously-'fixed' fingerprints as 'reopened'
//   - If a baselineTaskID exists, marks baseline open findings absent in taskID as 'fixed'
func (d *DB) CorrelateTaskFindings(taskID int64) (*CorrelationResult, error) {
	if err := d.BackfillFindingFingerprints(); err != nil {
		return nil, err
	}
	res := &CorrelationResult{TaskID: taskID}

	var baselineID int64
	if taskID > 0 {
		_ = d.QueryRow(`SELECT COALESCE(baseline_task_id, 0) FROM task_scan_profiles WHERE task_id = $1`, taskID).Scan(&baselineID)
		res.BaselineTaskID = baselineID
	}

	// Build prior fingerprint state map from earlier tasks (or baseline task).
	priorState := map[string]string{}
	priorFirstTask := map[string]int64{}
	priorSeen := map[string]int{}
	if taskID > 0 {
		q := `
			SELECT fingerprint, triage_status, COALESCE(first_seen_task_id, task_id, 0), seen_count
			FROM findings
			WHERE fingerprint <> '' AND COALESCE(task_id, 0) <> $1
			ORDER BY created_at ASC, id ASC`
		rows, err := d.Query(q, taskID)
		if err == nil {
			for rows.Next() {
				var fp, tr string
				var ftid int64
				var cnt int
				if rows.Scan(&fp, &tr, &ftid, &cnt) == nil {
					if tr == "noise" || priorState[fp] != "noise" {
						priorState[fp] = tr
					}
					if ftid > 0 && priorFirstTask[fp] == 0 {
						priorFirstTask[fp] = ftid
					}
					priorSeen[fp] += max(1, cnt)
				}
			}
			rows.Close()
		}
	}

	// Walk current task's findings and correlate against prior history.
	curFPs := map[string]bool{}
	var rows *sql.Rows
	var err error
	if taskID > 0 {
		rows, err = d.Query(`
			SELECT id, fingerprint, triage_status, triage_note, fix_group_key
			FROM findings
			WHERE task_id = $1
			ORDER BY id ASC`, taskID)
	} else {
		rows, err = d.Query(`
			SELECT id, fingerprint, triage_status, triage_note, fix_group_key
			FROM findings
			ORDER BY id ASC`)
	}
	if err != nil {
		return nil, err
	}
	type curItem struct {
		id     int64
		fp     string
		triage string
		note   string
		fgKey  string
	}
	var current []curItem
	for rows.Next() {
		var c curItem
		if rows.Scan(&c.id, &c.fp, &c.triage, &c.note, &c.fgKey) == nil {
			current = append(current, c)
		}
	}
	rows.Close()

	fgSeen := map[string]bool{}
	for _, c := range current {
		curFPs[c.fp] = true
		if c.fgKey != "" {
			fgSeen[c.fgKey] = true
		}
		nextTriage := strings.ToLower(strings.TrimSpace(c.triage))
		if nextTriage == "" {
			nextTriage = "new"
		}
		nextNote := c.note
		if taskID > 0 {
			if prev, ok := priorState[c.fp]; ok {
				switch prev {
				case "noise":
					if nextTriage != "noise" {
						nextTriage = "noise"
						res.AutoSuppressed++
						if nextNote == "" {
							nextNote = "Auto-suppressed: fingerprint previously marked as Noise (False Positive)"
						}
					}
				case "fixed":
					if nextTriage == "new" || nextTriage == "open" {
						nextTriage = "reopened"
						if nextNote == "" {
							nextNote = fmt.Sprintf("Reopened: regression detected in Task #%d", taskID)
						}
					}
				case "open", "in_progress", "reopened", "new":
					if nextTriage == "new" {
						nextTriage = "open"
					}
				}
				seenTotal := priorSeen[c.fp] + 1
				ftid := priorFirstTask[c.fp]
				if ftid <= 0 {
					ftid = taskID
				}
				_, _ = d.Exec(`
					UPDATE findings
					SET triage_status = $2,
					    status = $3,
					    triage_note = $4,
					    first_seen_task_id = $5,
					    last_seen_task_id = $6,
					    seen_count = $7
					WHERE id = $1`,
					c.id, nextTriage, mapTriageToLegacyStatus(nextTriage), nextNote, ftid, taskID, seenTotal)
			}
		}

		res.Total++
		switch nextTriage {
		case "new":
			res.NewCount++
		case "open":
			res.OpenCount++
		case "in_progress":
			res.InProgressCount++
		case "reopened":
			res.ReopenedCount++
		case "noise":
			res.NoiseCount++
		case "fixed":
			res.FixedCount++
		}
	}

	// If comparing against an explicit Reference Baseline task, mark absent open findings as fixed!
	if taskID > 0 && baselineID > 0 && baselineID != taskID && len(current) > 0 {
		bRows, bErr := d.Query(`
			SELECT id, fingerprint
			FROM findings
			WHERE task_id = $1 AND triage_status IN ('new', 'open', 'reopened', 'in_progress') AND fingerprint <> ''`, baselineID)
		if bErr == nil {
			var toFix []int64
			for bRows.Next() {
				var bid int64
				var bfp string
				if bRows.Scan(&bid, &bfp) == nil && !curFPs[bfp] {
					toFix = append(toFix, bid)
				}
			}
			bRows.Close()
			for _, bid := range toFix {
				_, _ = d.Exec(`
					UPDATE findings
					SET triage_status = 'fixed',
					    status = 'fixed',
					    triage_note = CASE WHEN triage_note = '' THEN $2 ELSE triage_note END
					WHERE id = $1`,
					bid, fmt.Sprintf("Auto-marked Fixed: absent in follow-up Task #%d", taskID))
				res.AutoMarkedFixed++
			}
		}
	}

	res.FixGroupCount = len(fgSeen)
	return res, nil
}

// ListEnterpriseFindings returns findings enriched with fingerprint, triage, FixGroup, VEX & CVEs.
func (d *DB) ListEnterpriseFindings(taskID int64, includeNoise bool) ([]EnterpriseFinding, error) {
	_ = d.BackfillFindingFingerprints()
	var rows *sql.Rows
	var err error
	baseSQL := `
		SELECT id, task_id, node_id, vulnclass, name, severity, summary, evidence, status,
		       fingerprint, triage_status, triage_note, fix_group_key, fix_group_type, fix_group_subject,
		       vex_status, vex_justification, first_seen_task_id, last_seen_task_id, seen_count, created_at
		FROM findings`
	if taskID > 0 {
		if includeNoise {
			rows, err = d.Query(baseSQL+` WHERE task_id = $1 ORDER BY created_at DESC, id DESC`, taskID)
		} else {
			rows, err = d.Query(baseSQL+` WHERE task_id = $1 AND triage_status <> 'noise' ORDER BY created_at DESC, id DESC`, taskID)
		}
	} else {
		if includeNoise {
			rows, err = d.Query(baseSQL + ` ORDER BY created_at DESC, id DESC LIMIT 300`)
		} else {
			rows, err = d.Query(baseSQL + ` WHERE triage_status <> 'noise' ORDER BY created_at DESC, id DESC LIMIT 300`)
		}
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []EnterpriseFinding{}
	for rows.Next() {
		var f EnterpriseFinding
		var tid, nid, ftid, ltid sql.NullInt64
		if err := rows.Scan(
			&f.ID, &tid, &nid, &f.VulnClass, &f.Name, &f.Severity, &f.Summary, &f.Evidence, &f.Status,
			&f.Fingerprint, &f.TriageStatus, &f.TriageNote, &f.FixGroupKey, &f.FixGroupType, &f.FixGroupSubject,
			&f.VexStatus, &f.VexJustification, &ftid, &ltid, &f.SeenCount, &f.CreatedAt,
		); err != nil {
			continue
		}
		if tid.Valid {
			v := tid.Int64
			f.TaskID = &v
		}
		if nid.Valid {
			v := nid.Int64
			f.NodeID = &v
		}
		if ftid.Valid {
			v := ftid.Int64
			f.FirstSeenTaskID = &v
		}
		if ltid.Valid {
			v := ltid.Int64
			f.LastSeenTaskID = &v
		}
		f.CVEs = ExtractCVEs(f.VulnClass, f.Name, f.Summary, f.Evidence)
		out = append(out, f)
	}
	return out, rows.Err()
}

// UpdateFindingTriage updates AppScan-style triage_status, VEX disposition, and FixGroup key.
func (d *DB) UpdateFindingTriage(findingID int64, triageStatus, triageNote, vexStatus, vexJustification, fixGroupKey string) error {
	validTriage := map[string]bool{
		"": true, "new": true, "open": true, "in_progress": true, "noise": true, "fixed": true, "reopened": true,
	}
	tr := strings.ToLower(strings.TrimSpace(triageStatus))
	if !validTriage[tr] {
		return fmt.Errorf("invalid triage_status: %s", triageStatus)
	}
	validVex := map[string]bool{
		"": true, "affected": true, "not_affected": true, "fixed": true, "under_investigation": true,
	}
	vx := strings.ToLower(strings.TrimSpace(vexStatus))
	if !validVex[vx] {
		return fmt.Errorf("invalid vex_status: %s", vexStatus)
	}

	if tr != "" {
		_, err := d.Exec(`
			UPDATE findings
			SET triage_status = $2,
			    status = $3,
			    triage_note = $4,
			    vex_status = CASE WHEN $5 <> '' THEN $5 ELSE vex_status END,
			    vex_justification = CASE WHEN $6 <> '' THEN $6 ELSE vex_justification END,
			    fix_group_key = CASE WHEN $7 <> '' THEN $7 ELSE fix_group_key END
			WHERE id = $1`,
			findingID, tr, mapTriageToLegacyStatus(tr), strings.TrimSpace(triageNote), vx, strings.TrimSpace(vexJustification), strings.TrimSpace(fixGroupKey))
		return err
	}
	_, err := d.Exec(`
		UPDATE findings
		SET triage_note = CASE WHEN $2 <> '' THEN $2 ELSE triage_note END,
		    vex_status = $3,
		    vex_justification = $4,
		    fix_group_key = CASE WHEN $5 <> '' THEN $5 ELSE fix_group_key END
		WHERE id = $1`,
		findingID, strings.TrimSpace(triageNote), vx, strings.TrimSpace(vexJustification), strings.TrimSpace(fixGroupKey))
	return err
}

// BuildFixGroups aggregates findings into root-cause FixGroups ("fix 1 place, close N issues").
func (d *DB) BuildFixGroups(taskID int64) ([]FixGroupSummary, error) {
	findings, err := d.ListEnterpriseFindings(taskID, true)
	if err != nil {
		return nil, err
	}
	type acc struct {
		sum     FixGroupSummary
		cveSet  map[string]bool
		vcSet   map[string]bool
	}
	byKey := map[string]*acc{}
	for _, f := range findings {
		key := f.FixGroupKey
		gtype := f.FixGroupType
		subj := f.FixGroupSubject
		if key == "" {
			key, gtype, subj = ComputeFixGroup(f.VulnClass, f.Name, f.Summary, f.Evidence)
		}
		a, ok := byKey[key]
		if !ok {
			a = &acc{
				sum: FixGroupSummary{
					FixGroupKey:     key,
					Type:            gtype,
					Subject:         subj,
					HighestSeverity: f.Severity,
					RemediationHint: buildFixGroupHint(gtype, subj),
				},
				cveSet: map[string]bool{},
				vcSet:  map[string]bool{},
			}
			byKey[key] = a
		}
		a.sum.TotalCount++
		a.sum.FindingIDs = append(a.sum.FindingIDs, f.ID)
		switch f.TriageStatus {
		case "noise":
			a.sum.NoiseCount++
		case "fixed":
			a.sum.FixedCount++
		default:
			a.sum.ActiveCount++
			if severityRank(f.Severity) < severityRank(a.sum.HighestSeverity) || a.sum.HighestSeverity == "" {
				a.sum.HighestSeverity = f.Severity
			}
		}
		for _, cve := range f.CVEs {
			if !a.cveSet[cve] {
				a.cveSet[cve] = true
				a.sum.CVEs = append(a.sum.CVEs, cve)
			}
		}
		vc := strings.TrimSpace(f.VulnClass)
		if vc != "" && !a.vcSet[vc] {
			a.vcSet[vc] = true
			a.sum.VulnClasses = append(a.sum.VulnClasses, vc)
		}
	}

	out := make([]FixGroupSummary, 0, len(byKey))
	for _, a := range byKey {
		sort.Strings(a.sum.CVEs)
		sort.Strings(a.sum.VulnClasses)
		if a.sum.HighestSeverity == "" {
			a.sum.HighestSeverity = "info"
		}
		out = append(out, a.sum)
	}
	sort.SliceStable(out, func(i, j int) bool {
		ri, rj := severityRank(out[i].HighestSeverity), severityRank(out[j].HighestSeverity)
		if ri != rj {
			return ri < rj
		}
		if out[i].ActiveCount != out[j].ActiveCount {
			return out[i].ActiveCount > out[j].ActiveCount
		}
		return out[i].TotalCount > out[j].TotalCount
	})
	return out, nil
}

func buildFixGroupHint(gtype, subject string) string {
	switch gtype {
	case "OpenSourceLib":
		return fmt.Sprintf("อัปเกรดไลบรารี/แพ็กเกจที่เป็นต้นเหตุ (%s) เป็นเวอร์ชันที่อุดช่องโหว่แล้ว และรัน Re-Test ยืนยัน", subject)
	case "FixLocation":
		return fmt.Sprintf("แก้ไขซอร์สโค้ดที่จุดต้นเหตุ (%s) พร้อมเพิ่มการตรวจสอบ Input Validation / Authorization ในฟังก์ชันเดียว", subject)
	case "ApiEndpoint":
		return fmt.Sprintf("เสริมการควบคุมสิทธิ์, Validation และ Security Headers ที่ปลายทาง (%s) เพื่อปิดทุกประเด็นพร้อมกัน", subject)
	default:
		return fmt.Sprintf("กำหนดมาตรการควบคุมกลางสำหรับ %s แล้วตรวจสอบซ้ำแบบ Re-Test", subject)
	}
}

// GetTaskQualityGate reads the latest Control-Plane Quality Gate for taskID.
func (d *DB) GetTaskQualityGate(taskID int64) (*TaskQualityGate, error) {
	var g TaskQualityGate
	var checksRaw []byte
	err := d.QueryRow(`
		SELECT task_id, gate_status, exit_code, exit_reason, checks_json, evaluated_by, evaluated_at
		FROM task_quality_gates
		WHERE task_id = $1`, taskID).Scan(
		&g.TaskID, &g.GateStatus, &g.ExitCode, &g.ExitReason, &checksRaw, &g.EvaluatedBy, &g.EvaluatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	_ = json.Unmarshal(checksRaw, &g.Checks)
	return &g, nil
}

// UpsertTaskQualityGate saves a Control-Plane Quality Gate evaluation.
func (d *DB) UpsertTaskQualityGate(g TaskQualityGate) error {
	checksRaw, _ := json.Marshal(g.Checks)
	if len(checksRaw) == 0 {
		checksRaw = []byte("[]")
	}
	_, err := d.Exec(`
		INSERT INTO task_quality_gates (task_id, gate_status, exit_code, exit_reason, checks_json, evaluated_by, evaluated_at)
		VALUES ($1, $2, $3, $4, $5::jsonb, $6, now())
		ON CONFLICT (task_id) DO UPDATE
		SET gate_status  = EXCLUDED.gate_status,
		    exit_code    = EXCLUDED.exit_code,
		    exit_reason  = EXCLUDED.exit_reason,
		    checks_json  = EXCLUDED.checks_json,
		    evaluated_by = EXCLUDED.evaluated_by,
		    evaluated_at = now()`,
		g.TaskID, g.GateStatus, g.ExitCode, g.ExitReason, string(checksRaw), g.EvaluatedBy)
	return err
}

// GetTaskScanProfile returns the ScanOperation profile for taskID (with safe defaults).
func (d *DB) GetTaskScanProfile(taskID int64) (*TaskScanProfile, error) {
	p := &TaskScanProfile{
		TaskID:       taskID,
		ScanMode:     "full",
		PhaseTimings: map[string]int64{},
	}
	var baseID, bundleID sql.NullInt64
	var timingsRaw []byte
	err := d.QueryRow(`
		SELECT scan_mode, baseline_task_id, bundle_id, is_reference_baseline, phase_timings_json, updated_at
		FROM task_scan_profiles
		WHERE task_id = $1`, taskID).Scan(
		&p.ScanMode, &baseID, &bundleID, &p.IsReferenceBaseline, &timingsRaw, &p.UpdatedAt,
	)
	if err == sql.ErrNoRows {
		return p, nil
	}
	if err != nil {
		return nil, err
	}
	if baseID.Valid {
		p.BaselineTaskID = baseID.Int64
	}
	if bundleID.Valid {
		p.BundleID = bundleID.Int64
	}
	_ = json.Unmarshal(timingsRaw, &p.PhaseTimings)
	return p, nil
}

// UpsertTaskScanProfile persists ScanOperation mode, baseline linkage, and bundle attachment.
func (d *DB) UpsertTaskScanProfile(p TaskScanProfile) error {
	validModes := map[string]bool{
		"full": true, "explore_only": true, "test_only": true, "retest": true, "report_only": true,
	}
	mode := strings.ToLower(strings.TrimSpace(p.ScanMode))
	if !validModes[mode] {
		mode = "full"
	}
	var basePtr, bundlePtr any
	if p.BaselineTaskID > 0 && p.BaselineTaskID != p.TaskID {
		basePtr = p.BaselineTaskID
	}
	if p.BundleID > 0 {
		bundlePtr = p.BundleID
	}
	timingsRaw, _ := json.Marshal(p.PhaseTimings)
	if len(timingsRaw) == 0 || string(timingsRaw) == "null" {
		timingsRaw = []byte("{}")
	}
	_, err := d.Exec(`
		INSERT INTO task_scan_profiles (task_id, scan_mode, baseline_task_id, bundle_id, is_reference_baseline, phase_timings_json, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6::jsonb, now())
		ON CONFLICT (task_id) DO UPDATE
		SET scan_mode             = EXCLUDED.scan_mode,
		    baseline_task_id      = EXCLUDED.baseline_task_id,
		    bundle_id             = EXCLUDED.bundle_id,
		    is_reference_baseline = EXCLUDED.is_reference_baseline,
		    phase_timings_json    = EXCLUDED.phase_timings_json,
		    updated_at            = now()`,
		p.TaskID, mode, basePtr, bundlePtr, p.IsReferenceBaseline, string(timingsRaw))
	return err
}

// ListReferenceBaselines lists tasks flagged as Reference Baselines (plus recent completed tasks).
func (d *DB) ListReferenceBaselines() ([]ReferenceBaselineItem, error) {
	rows, err := d.Query(`
		SELECT t.id, COALESCE(t.name, ''), COALESCE(t.description, ''), COALESCE(p.scan_mode, 'full'),
		       (SELECT count(*) FROM task_asset_links l WHERE l.task_id = t.id) AS asset_cnt,
		       (SELECT count(*) FROM findings f WHERE f.task_id = t.id AND f.triage_status <> 'noise') AS finding_cnt
		FROM tasks t
		LEFT JOIN task_scan_profiles p ON p.task_id = t.id
		WHERE t.deleted_at IS NULL
		  AND (COALESCE(p.is_reference_baseline, false) = true OR t.status = 'done')
		ORDER BY COALESCE(p.is_reference_baseline, false) DESC, t.id DESC
		LIMIT 30`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ReferenceBaselineItem{}
	for rows.Next() {
		var it ReferenceBaselineItem
		if rows.Scan(&it.TaskID, &it.Name, &it.Description, &it.ScanMode, &it.AssetCount, &it.FindingCount) == nil {
			out = append(out, it)
		}
	}
	return out, rows.Err()
}

// ListScanBundles returns all saved reusable Auth / OpenAPI / Postman / TestPolicy bundles.
func (d *DB) ListScanBundles() ([]ScanContextBundle, error) {
	rows, err := d.Query(`
		SELECT id, name, target_pattern, company_id, auth_type, auth_config_json,
		       openapi_path, postman_path, test_policy, exclude_paths, rate_limit_rps, notes, created_at, updated_at
		FROM scan_context_bundles
		ORDER BY updated_at DESC, id DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ScanContextBundle{}
	for rows.Next() {
		var b ScanContextBundle
		var cid sql.NullInt64
		var authRaw, exclRaw []byte
		if rows.Scan(
			&b.ID, &b.Name, &b.TargetPattern, &cid, &b.AuthType, &authRaw,
			&b.OpenAPIPath, &b.PostmanPath, &b.TestPolicy, &exclRaw, &b.RateLimitRPS, &b.Notes, &b.CreatedAt, &b.UpdatedAt,
		) != nil {
			continue
		}
		if cid.Valid {
			v := cid.Int64
			b.CompanyID = &v
		}
		_ = json.Unmarshal(authRaw, &b.AuthConfig)
		_ = json.Unmarshal(exclRaw, &b.ExcludePaths)
		if b.AuthConfig == nil {
			b.AuthConfig = map[string]any{}
		}
		if b.ExcludePaths == nil {
			b.ExcludePaths = []string{}
		}
		out = append(out, b)
	}
	return out, rows.Err()
}

// GetScanBundle fetches a single ScanContextBundle by ID.
func (d *DB) GetScanBundle(id int64) (*ScanContextBundle, error) {
	if id <= 0 {
		return nil, nil
	}
	var b ScanContextBundle
	var cid sql.NullInt64
	var authRaw, exclRaw []byte
	err := d.QueryRow(`
		SELECT id, name, target_pattern, company_id, auth_type, auth_config_json,
		       openapi_path, postman_path, test_policy, exclude_paths, rate_limit_rps, notes, created_at, updated_at
		FROM scan_context_bundles
		WHERE id = $1`, id).Scan(
		&b.ID, &b.Name, &b.TargetPattern, &cid, &b.AuthType, &authRaw,
		&b.OpenAPIPath, &b.PostmanPath, &b.TestPolicy, &exclRaw, &b.RateLimitRPS, &b.Notes, &b.CreatedAt, &b.UpdatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if cid.Valid {
		v := cid.Int64
		b.CompanyID = &v
	}
	_ = json.Unmarshal(authRaw, &b.AuthConfig)
	_ = json.Unmarshal(exclRaw, &b.ExcludePaths)
	return &b, nil
}

// SaveScanBundle creates or updates a reusable ScanContextBundle.
func (d *DB) SaveScanBundle(b *ScanContextBundle) (int64, error) {
	name := strings.TrimSpace(b.Name)
	if name == "" {
		return 0, fmt.Errorf("bundle name is required")
	}
	authType := strings.ToLower(strings.TrimSpace(b.AuthType))
	if authType == "" {
		authType = "none"
	}
	policy := strings.ToLower(strings.TrimSpace(b.TestPolicy))
	if policy == "" {
		policy = "standard"
	}
	rps := b.RateLimitRPS
	if rps <= 0 {
		rps = 5
	}
	authRaw, _ := json.Marshal(b.AuthConfig)
	if len(authRaw) == 0 || string(authRaw) == "null" {
		authRaw = []byte("{}")
	}
	exclRaw, _ := json.Marshal(b.ExcludePaths)
	if len(exclRaw) == 0 || string(exclRaw) == "null" {
		exclRaw = []byte("[]")
	}
	if b.ID > 0 {
		_, err := d.Exec(`
			UPDATE scan_context_bundles
			SET name = $2, target_pattern = $3, company_id = $4, auth_type = $5,
			    auth_config_json = $6::jsonb, openapi_path = $7, postman_path = $8,
			    test_policy = $9, exclude_paths = $10::jsonb, rate_limit_rps = $11,
			    notes = $12, updated_at = now()
			WHERE id = $1`,
			b.ID, name, strings.TrimSpace(b.TargetPattern), b.CompanyID, authType,
			string(authRaw), strings.TrimSpace(b.OpenAPIPath), strings.TrimSpace(b.PostmanPath),
			policy, string(exclRaw), rps, strings.TrimSpace(b.Notes))
		return b.ID, err
	}
	var id int64
	err := d.QueryRow(`
		INSERT INTO scan_context_bundles
			(name, target_pattern, company_id, auth_type, auth_config_json, openapi_path, postman_path, test_policy, exclude_paths, rate_limit_rps, notes)
		VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9::jsonb, $10, $11)
		RETURNING id`,
		name, strings.TrimSpace(b.TargetPattern), b.CompanyID, authType, string(authRaw),
		strings.TrimSpace(b.OpenAPIPath), strings.TrimSpace(b.PostmanPath),
		policy, string(exclRaw), rps, strings.TrimSpace(b.Notes)).Scan(&id)
	return id, err
}

// DeleteScanBundle removes a ScanContextBundle by ID.
func (d *DB) DeleteScanBundle(id int64) error {
	_, err := d.Exec(`DELETE FROM scan_context_bundles WHERE id = $1`, id)
	return err
}
