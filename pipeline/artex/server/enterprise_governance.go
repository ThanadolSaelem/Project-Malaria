package server

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/Autumn-27/artex/db"
)

// EvaluateTaskQualityGate implements AppScan's Control-Plane Separation of Duty
// ("Engine is not allowed to change status to Ready"). Independently evaluates real
// PostgreSQL Evidence, Traffic, Assets Coverage, Auth/WAF health, and Goal state.
func (s *Server) EvaluateTaskQualityGate(taskID int64, evaluatedBy string) (*db.TaskQualityGate, error) {
	if s == nil || s.m == nil || s.m.pg == nil || taskID <= 0 {
		return nil, fmt.Errorf("invalid task_id or server unavailable")
	}
	if evaluatedBy == "" {
		evaluatedBy = "control_plane"
	}

	// Ensure fingerprints & FixGroups are up to date before gating.
	_, _ = s.m.pg.CorrelateTaskFindings(taskID)

	checks := []db.GateCheckItem{}
	gateStatus := "ready"
	exitCode := "Success"
	exitReason := "ผ่านเกณฑ์คุณภาพ Control Plane ครบทุกข้อ (พร้อมจัดทำรายงานและส่งมอบ)"

	var authFailCount, wafBlockCount, okRespCount int
	if t, ok := s.m.Task(strconv.FormatInt(taskID, 10)); ok && t != nil && t.Store != nil {
		expID := t.Store.ID()
		if expID > 0 {
			_ = s.m.pg.QueryRow(`
				SELECT
					COALESCE(SUM(CASE WHEN detail ~* '(401 unauthorized|failure to login|invalid credentials|login failed|session expired)' THEN 1 ELSE 0 END), 0),
					COALESCE(SUM(CASE WHEN detail ~* '(403 forbidden|429 too many|cloudflare|waf block|rate limit)' THEN 1 ELSE 0 END), 0),
					COALESCE(SUM(CASE WHEN NOT is_error AND kind IN ('tool_result','result') THEN 1 ELSE 0 END), 0)
				FROM activity
				WHERE exploration_id = $1`, expID).Scan(&authFailCount, &wafBlockCount, &okRespCount)
		}
	}

	// 1. Auth health check
	authPassed := !(authFailCount >= 5 && okRespCount < authFailCount*2)
	authDetail := fmt.Sprintf("พบสัญญาณ 401/Login Fail %d ครั้ง", authFailCount)
	if !authPassed {
		authDetail = fmt.Sprintf("พบ Auth/Login ล้มเหลวซ้ำ %d ครั้ง — แนะนำอัปเดต Auth Bundle/Cookie แล้วสแกนต่อ", authFailCount)
		gateStatus = "pending_support"
		exitCode = "FailureToLogin"
		exitReason = "พบปัญหาการยืนยันตัวตน (401/Login Failed ซ้ำต่อเนื่อง) Control Plane จึงกันไม่ให้ปิดงานเป็น Ready"
	}
	checks = append(checks, db.GateCheckItem{Name: "auth_health", Passed: authPassed, Detail: authDetail})

	// 2. WAF / Rate-limit check
	wafPassed := !(wafBlockCount >= 8 && okRespCount < wafBlockCount*2)
	wafDetail := fmt.Sprintf("พบสัญญาณ WAF/403/429 จำนวน %d ครั้ง", wafBlockCount)
	if !wafPassed {
		wafDetail = fmt.Sprintf("ถูก WAF หรือ Rate Limit บล็อกสูง (%d ครั้ง) — แนะนำลด RateLimit RPS ใน Scan Bundle", wafBlockCount)
		if gateStatus == "ready" {
			gateStatus = "ready_incomplete"
			exitCode = "WAFBlocked"
			exitReason = "ผลสแกนอาจไม่ครบถ้วนเนื่องจากถูก WAF/Rate-Limit บล็อกสูง"
		}
	}
	checks = append(checks, db.GateCheckItem{Name: "waf_ratelimit", Passed: wafPassed, Detail: wafDetail})

	// 3. Asset coverage completeness check
	untestedCount := 0
	if as := s.assetStore(); as != nil && as.CoverageEnabled(taskID) {
		_, untestedCount, _ = as.ListUntestedAssetsWithSources(taskID, "", 1, 0)
	}
	covPassed := untestedCount == 0
	covDetail := "Asset ในขอบเขตทั้งหมดถูกตรวจสอบแล้ว"
	if !covPassed {
		covDetail = fmt.Sprintf("ยังมี Asset ในขอบเขตที่ยังไม่ได้ทดสอบเหลืออยู่ %d รายการ", untestedCount)
		if gateStatus == "ready" {
			gateStatus = "ready_incomplete"
			exitCode = "UntestedAssetsRemaining"
			exitReason = fmt.Sprintf("ยังมี Asset ในขอบเขตยังไม่ได้ทดสอบ %d รายการ (สามารถรันโหมด TestOnly เก็บตกได้)", untestedCount)
		}
	}
	checks = append(checks, db.GateCheckItem{Name: "coverage_completeness", Passed: covPassed, Detail: covDetail})

	// 4. Evidence integrity check for active (non-noise) findings
	findings, _ := s.m.pg.ListEnterpriseFindings(taskID, false)
	missingEvidence := 0
	for _, f := range findings {
		if len(strings.TrimSpace(f.Evidence)) < 20 {
			var boundCnt int
			_ = s.m.pg.QueryRow(`SELECT count(*) FROM finding_traffic_bindings WHERE finding_id = $1`, f.ID).Scan(&boundCnt)
			if boundCnt == 0 {
				missingEvidence++
			}
		}
	}
	evPassed := missingEvidence == 0
	evDetail := fmt.Sprintf("Active Findings ทั้ง %d รายการมีหลักฐานประกอบครบถ้วน", len(findings))
	if !evPassed {
		evDetail = fmt.Sprintf("มี Active Finding %d จาก %d รายการที่ยังขาดหลักฐาน/PoC หรือ Traffic Binding", missingEvidence, len(findings))
		if gateStatus == "ready" {
			gateStatus = "ready_incomplete"
			exitCode = "InsufficientEvidence"
			exitReason = "พบ Finding ที่ยังไม่มีหลักฐานยืนยันเพียงพอ — แนะนำให้ Re-Test หรือแนบหลักฐานเพิ่ม"
		}
	}
	checks = append(checks, db.GateCheckItem{Name: "evidence_integrity", Passed: evPassed, Detail: evDetail})

	// 5. Mission Goals verification check
	openGoals, metGoals := 0, 0
	if t, ok := s.m.Task(strconv.FormatInt(taskID, 10)); ok && t != nil && t.Store != nil {
		if goals, err := t.Store.ListByKind(db.KindGoal, 50); err == nil {
			for _, g := range goals {
				if g.State == "met" {
					metGoals++
				} else if g.State == "open" {
					openGoals++
				}
			}
		}
	}
	goalsPassed := openGoals == 0
	goalsDetail := fmt.Sprintf("Goal บรรลุแล้ว %d ข้อ (คงค้าง %d ข้อ)", metGoals, openGoals)
	if !goalsPassed && gateStatus == "ready" {
		gateStatus = "ready_incomplete"
		exitCode = "GoalsIncomplete"
		exitReason = fmt.Sprintf("ยังมี Mission Goal เปิดค้างอยู่ %d ข้อ", openGoals)
	}
	checks = append(checks, db.GateCheckItem{Name: "goal_verification", Passed: goalsPassed, Detail: goalsDetail})

	gate := db.TaskQualityGate{
		TaskID:      taskID,
		GateStatus:  gateStatus,
		ExitCode:    exitCode,
		ExitReason:  exitReason,
		Checks:      checks,
		EvaluatedBy: evaluatedBy,
		EvaluatedAt: time.Now().UTC(),
	}
	if err := s.m.pg.UpsertTaskQualityGate(gate); err != nil {
		return nil, err
	}
	return &gate, nil
}

// copyBaselineAssetsToTask implements AppScan incremental baseline reuse: inherits
// discovered Assets from baselineTaskID into targetTaskID so TestOnly skips recon!
func (s *Server) copyBaselineAssetsToTask(baselineTaskID, targetTaskID int64) (int64, error) {
	if s == nil || s.m == nil || s.m.pg == nil || baselineTaskID <= 0 || targetTaskID <= 0 || baselineTaskID == targetTaskID {
		return 0, nil
	}
	var copied int64
	err := s.m.pg.QueryRow(`
		WITH src AS (
			SELECT asset_id FROM task_asset_links WHERE task_id = $1
		), upd AS (
			UPDATE assets a
			SET task_ids = CASE WHEN NOT ($2 = ANY(a.task_ids)) THEN array_append(a.task_ids, $2) ELSE a.task_ids END
			FROM src
			WHERE a.id = src.asset_id
			RETURNING a.id
		), ins AS (
			INSERT INTO task_asset_links(task_id, asset_id, source, source_summary)
			SELECT $2, u.id, 'baseline', 'inherited from Reference Baseline Task #' || $1::text
			FROM upd u
			ON CONFLICT (task_id, asset_id) DO NOTHING
		)
		SELECT count(*) FROM upd`, baselineTaskID, targetTaskID).Scan(&copied)
	return copied, err
}

// formatScanBundleBriefing renders a concise, safe prompt directive for an attached ScanContextBundle.
func formatScanBundleBriefing(b *db.ScanContextBundle) string {
	if b == nil {
		return ""
	}
	var sb strings.Builder
	fmt.Fprintf(&sb, "- Active Scan Context Bundle: #%d %q (Policy: %s, RateLimit: %d rps)\n", b.ID, b.Name, b.TestPolicy, b.RateLimitRPS)
	if b.TargetPattern != "" {
		fmt.Fprintf(&sb, "  Target Pattern: %s\n", b.TargetPattern)
	}
	if b.AuthType != "" && b.AuthType != "none" {
		keys := make([]string, 0, len(b.AuthConfig))
		for k := range b.AuthConfig {
			keys = append(keys, k)
		}
		fmt.Fprintf(&sb, "  Auth Profile: %s (configured fields: %s — call artex MCP get_scan_bundle(id=%d) for headers/login steps)\n",
			b.AuthType, strings.Join(keys, ", "), b.ID)
	}
	if b.OpenAPIPath != "" {
		fmt.Fprintf(&sb, "  OpenAPI / Swagger Spec: %s\n", b.OpenAPIPath)
	}
	if b.PostmanPath != "" {
		fmt.Fprintf(&sb, "  Postman Collection: %s\n", b.PostmanPath)
	}
	if len(b.ExcludePaths) > 0 {
		fmt.Fprintf(&sb, "  Excluded Paths (DO NOT TEST): %s\n", strings.Join(b.ExcludePaths, ", "))
	}
	if b.Notes != "" {
		fmt.Fprintf(&sb, "  Policy Notes: %s\n", b.Notes)
	}
	return sb.String()
}

// --- HTTP Handlers (/api/enterprise/*) ---

func parsePathTaskID(r *http.Request) int64 {
	raw := strings.TrimSpace(r.PathValue("id"))
	v, _ := strconv.ParseInt(raw, 10, 64)
	return v
}

func (s *Server) enterpriseTaskOverview(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid := parsePathTaskID(r)
	if tid <= 0 {
		writeErr(w, 400, "invalid task id")
		return
	}
	corr, _ := s.m.pg.CorrelateTaskFindings(tid)
	gate, _ := s.m.pg.GetTaskQualityGate(tid)
	if gate == nil {
		gate, _ = s.EvaluateTaskQualityGate(tid, "control_plane")
	}
	profile, _ := s.m.pg.GetTaskScanProfile(tid)
	fixGroups, _ := s.m.pg.BuildFixGroups(tid)
	findings, _ := s.m.pg.ListEnterpriseFindings(tid, true)
	var bundle *db.ScanContextBundle
	if profile != nil && profile.BundleID > 0 {
		bundle, _ = s.m.pg.GetScanBundle(profile.BundleID)
	}
	baselines, _ := s.m.pg.ListReferenceBaselines()
	bundles, _ := s.m.pg.ListScanBundles()

	writeJSON(w, 200, map[string]any{
		"ok":          true,
		"task_id":     tid,
		"gate":        gate,
		"profile":     profile,
		"correlation": corr,
		"fix_groups":  fixGroups,
		"findings":    findings,
		"bundle":      bundle,
		"baselines":   baselines,
		"bundles":     bundles,
	})
}

func (s *Server) enterpriseEvaluateGate(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid := parsePathTaskID(r)
	if tid <= 0 {
		writeErr(w, 400, "invalid task id")
		return
	}
	gate, err := s.EvaluateTaskQualityGate(tid, "control_plane")
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "gate": gate})
}

func (s *Server) enterpriseOverrideGate(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid := parsePathTaskID(r)
	if tid <= 0 {
		writeErr(w, 400, "invalid task id")
		return
	}
	var req struct {
		GateStatus string `json:"gate_status"`
		ExitCode   string `json:"exit_code"`
		ExitReason string `json:"exit_reason"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	valid := map[string]bool{"ready": true, "ready_incomplete": true, "pending_support": true, "failed": true}
	st := strings.ToLower(strings.TrimSpace(req.GateStatus))
	if !valid[st] {
		writeErr(w, 400, "gate_status must be ready / ready_incomplete / pending_support / failed")
		return
	}
	existing, _ := s.m.pg.GetTaskQualityGate(tid)
	checks := []db.GateCheckItem{}
	if existing != nil {
		checks = existing.Checks
	}
	code := strings.TrimSpace(req.ExitCode)
	if code == "" {
		if st == "ready" {
			code = "OperatorApproved"
		} else {
			code = "OperatorOverride"
		}
	}
	reason := strings.TrimSpace(req.ExitReason)
	if reason == "" {
		reason = "ผู้ปฏิบัติงานยืนยันปรับสถานะ Control-Plane Gate ด้วยตนเอง"
	}
	gate := db.TaskQualityGate{
		TaskID:      tid,
		GateStatus:  st,
		ExitCode:    code,
		ExitReason:  reason,
		Checks:      checks,
		EvaluatedBy: "operator",
		EvaluatedAt: time.Now().UTC(),
	}
	if err := s.m.pg.UpsertTaskQualityGate(gate); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "gate": gate})
}

func (s *Server) enterpriseCorrelateTask(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid := parsePathTaskID(r)
	corr, err := s.m.pg.CorrelateTaskFindings(tid)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	fixGroups, _ := s.m.pg.BuildFixGroups(tid)
	writeJSON(w, 200, map[string]any{"ok": true, "correlation": corr, "fix_groups": fixGroups})
}

func (s *Server) enterpriseListFixGroups(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid, _ := strconv.ParseInt(strings.TrimSpace(r.URL.Query().Get("task_id")), 10, 64)
	groups, err := s.m.pg.BuildFixGroups(tid)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "task_id": tid, "fix_groups": groups})
}

func (s *Server) enterpriseListFindings(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid, _ := strconv.ParseInt(strings.TrimSpace(r.URL.Query().Get("task_id")), 10, 64)
	includeNoise := r.URL.Query().Get("include_noise") != "0"
	items, err := s.m.pg.ListEnterpriseFindings(tid, includeNoise)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "task_id": tid, "findings": items})
}

func (s *Server) enterpriseTriageFinding(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	fid := parsePathTaskID(r)
	if fid <= 0 {
		writeErr(w, 400, "invalid finding id")
		return
	}
	var req struct {
		TriageStatus     string `json:"triage_status"`
		TriageNote       string `json:"triage_note"`
		VexStatus        string `json:"vex_status"`
		VexJustification string `json:"vex_justification"`
		FixGroupKey      string `json:"fix_group_key"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if err := s.m.pg.UpdateFindingTriage(fid, req.TriageStatus, req.TriageNote, req.VexStatus, req.VexJustification, req.FixGroupKey); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "finding_id": fid})
}

func (s *Server) enterpriseUpdateScanProfile(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid := parsePathTaskID(r)
	if tid <= 0 {
		writeErr(w, 400, "invalid task id")
		return
	}
	var req struct {
		ScanMode            string `json:"scan_mode"`
		BaselineTaskID      int64  `json:"baseline_task_id"`
		BundleID            int64  `json:"bundle_id"`
		IsReferenceBaseline *bool  `json:"is_reference_baseline"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	cur, _ := s.m.pg.GetTaskScanProfile(tid)
	if cur == nil {
		cur = &db.TaskScanProfile{TaskID: tid, ScanMode: "full"}
	}
	if req.ScanMode != "" {
		cur.ScanMode = req.ScanMode
	}
	if req.BaselineTaskID >= 0 {
		cur.BaselineTaskID = req.BaselineTaskID
	}
	if req.BundleID >= 0 {
		cur.BundleID = req.BundleID
	}
	if req.IsReferenceBaseline != nil {
		cur.IsReferenceBaseline = *req.IsReferenceBaseline
	}
	if err := s.m.pg.UpsertTaskScanProfile(*cur); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	var copied int64
	if cur.BaselineTaskID > 0 && (cur.ScanMode == "test_only" || cur.ScanMode == "retest") {
		copied, _ = s.copyBaselineAssetsToTask(cur.BaselineTaskID, tid)
	}
	writeJSON(w, 200, map[string]any{"ok": true, "profile": cur, "baseline_assets_inherited": copied})
}

func (s *Server) enterpriseRunScanOperation(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	tid := parsePathTaskID(r)
	if tid <= 0 {
		writeErr(w, 400, "invalid task id")
		return
	}
	var req struct {
		Operation      string `json:"operation"` // full | explore_only | test_only | retest | report_only
		BaselineTaskID int64  `json:"baseline_task_id"`
		BundleID       int64  `json:"bundle_id"`
		TemplateID     string `json:"template_id"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	res, err := s.executeScanOperation(r.Context(), tid, req.Operation, req.BaselineTaskID, req.BundleID, req.TemplateID)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	writeJSON(w, 200, res)
}

func (s *Server) executeScanOperation(ctx context.Context, taskID int64, operation string, baselineID, bundleID int64, templateID string) (map[string]any, error) {
	op := strings.ToLower(strings.TrimSpace(operation))
	if op == "" {
		op = "full"
	}
	t, ok := s.m.Task(strconv.FormatInt(taskID, 10))
	if !ok || t == nil {
		return nil, fmt.Errorf("task #%d not found", taskID)
	}
	prof, _ := s.m.pg.GetTaskScanProfile(taskID)
	if prof == nil {
		prof = &db.TaskScanProfile{TaskID: taskID}
	}
	prof.ScanMode = op
	if baselineID > 0 {
		prof.BaselineTaskID = baselineID
	}
	if bundleID > 0 {
		prof.BundleID = bundleID
	}
	_ = s.m.pg.UpsertTaskScanProfile(*prof)

	var inherited int64
	if prof.BaselineTaskID > 0 && (op == "test_only" || op == "retest") {
		inherited, _ = s.copyBaselineAssetsToTask(prof.BaselineTaskID, taskID)
	}

	switch op {
	case "report_only":
		corr, _ := s.m.pg.CorrelateTaskFindings(taskID)
		gate, _ := s.EvaluateTaskQualityGate(taskID, "control_plane")
		return map[string]any{
			"ok":          true,
			"operation":   "report_only",
			"task_id":     taskID,
			"correlation": corr,
			"gate":        gate,
			"message":     "Correlated findings and evaluated Quality Gate (ready to generate Report Only without re-scanning).",
		}, nil

	case "explore_only":
		// Add an explicit exploration-only intent and mark as Reference Baseline candidate.
		if t.Store != nil {
			in, _ := json.Marshal(map[string]any{
				"task_id": strconv.FormatInt(taskID, 10),
				"summary": fmt.Sprintf("[ExploreOnly] Discover attack surface, endpoints, assets, and scripts without active exploitation for Task #%d", taskID),
			})
			_, _ = s.mcpCallDomainTool(ctx, in, true, "add_intent")
		}
		prof.IsReferenceBaseline = true
		_ = s.m.pg.UpsertTaskScanProfile(*prof)
		s.engine.Resume(t)
		return map[string]any{
			"ok":        true,
			"operation": "explore_only",
			"task_id":   taskID,
			"message":   "Started Explore-Only discovery phase and marked Task as Reference Baseline.",
		}, nil

	case "test_only":
		if t.Store != nil {
			in, _ := json.Marshal(map[string]any{
				"task_id": strconv.FormatInt(taskID, 10),
				"summary": fmt.Sprintf("[TestOnly] Skip redundant recon (inherited %d baseline assets) and run targeted vulnerability tests against mapped attack surface", inherited),
			})
			_, _ = s.mcpCallDomainTool(ctx, in, true, "add_intent")
		}
		s.engine.Resume(t)
		return map[string]any{
			"ok":                        true,
			"operation":                 "test_only",
			"task_id":                   taskID,
			"baseline_assets_inherited": inherited,
			"message":                   fmt.Sprintf("Started Test-Only scan inheriting %d assets from baseline.", inherited),
		}, nil

	case "retest":
		srcTID := prof.BaselineTaskID
		if srcTID <= 0 {
			srcTID = taskID
		}
		findings, _ := s.m.pg.ListEnterpriseFindings(srcTID, false)
		var openTitles []string
		for _, f := range findings {
			if f.TriageStatus != "fixed" && f.TriageStatus != "noise" {
				openTitles = append(openTitles, fmt.Sprintf("#%d [%s] %s (fp:%s)", f.ID, f.Severity, firstLine(f.Name+" "+f.VulnClass, 60), f.Fingerprint))
			}
		}
		summary := fmt.Sprintf("[ReTest] Verify remediation status of %d active finding(s) from Task #%d: %s",
			len(openTitles), srcTID, strings.Join(openTitles, "; "))
		if len(summary) > 800 {
			summary = summary[:800] + "..."
		}
		if t.Store != nil {
			in, _ := json.Marshal(map[string]any{
				"task_id": strconv.FormatInt(taskID, 10),
				"summary": summary,
			})
			_, _ = s.mcpCallDomainTool(ctx, in, true, "add_intent")
		}
		s.engine.Resume(t)
		return map[string]any{
			"ok":               true,
			"operation":        "retest",
			"task_id":          taskID,
			"targets_retested": len(openTitles),
			"message":          fmt.Sprintf("Queued targeted Re-Test for %d active findings.", len(openTitles)),
		}, nil

	default: // full
		s.engine.Resume(t)
		return map[string]any{
			"ok":        true,
			"operation": "full",
			"task_id":   taskID,
			"message":   "Resumed Full Explore + Test autonomous pipeline.",
		}, nil
	}
}

func (s *Server) enterpriseListBaselines(w http.ResponseWriter, _ *http.Request) {
	if s.pg(w) == nil {
		return
	}
	items, err := s.m.pg.ListReferenceBaselines()
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "baselines": items})
}

func (s *Server) enterpriseListBundles(w http.ResponseWriter, _ *http.Request) {
	if s.pg(w) == nil {
		return
	}
	items, err := s.m.pg.ListScanBundles()
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "bundles": items})
}

func (s *Server) enterpriseSaveBundle(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req db.ScanContextBundle
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	id, err := s.m.pg.SaveScanBundle(&req)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	saved, _ := s.m.pg.GetScanBundle(id)
	writeJSON(w, 200, map[string]any{"ok": true, "id": id, "bundle": saved})
}

func (s *Server) enterpriseDeleteBundle(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	id := parsePathTaskID(r)
	if id <= 0 {
		writeErr(w, 400, "invalid bundle id")
		return
	}
	if err := s.m.pg.DeleteScanBundle(id); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true})
}

func (s *Server) enterpriseUploadBundleSpec(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 32<<20)
	if err := r.ParseMultipartForm(8 << 20); err != nil {
		writeErr(w, 400, "parse multipart failed: "+err.Error())
		return
	}
	files := r.MultipartForm.File["file"]
	if len(files) == 0 {
		writeErr(w, 400, "missing file")
		return
	}
	kind := sanitizeFolderSegment(r.FormValue("kind"))
	if kind == "" {
		kind = "spec"
	}
	profileDir := filepath.Join(sharedWorkspaceRoot, "profiles")
	if err := os.MkdirAll(profileDir, 0o755); err != nil {
		profileDir = filepath.Join(s.m.dir, "profiles")
		_ = os.MkdirAll(profileDir, 0o755)
	}
	hdr := files[0]
	base := filepath.Base(hdr.Filename)
	dest := uniqueUploadPath(profileDir, kind+"-"+base)
	if err := saveUpload(hdr, dest); err != nil {
		writeErr(w, 500, "save spec failed: "+err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "path": dest, "name": filepath.Base(dest), "size": hdr.Size})
}

func (s *Server) enterpriseAttachBundle(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req struct {
		BundleID       int64 `json:"bundle_id"`
		TaskID         int64 `json:"task_id"`
		ConversationID int64 `json:"conversation_id"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if req.BundleID > 0 {
		b, err := s.m.pg.GetScanBundle(req.BundleID)
		if err != nil || b == nil {
			writeErr(w, 404, "bundle not found")
			return
		}
	}
	if req.TaskID > 0 {
		prof, _ := s.m.pg.GetTaskScanProfile(req.TaskID)
		if prof == nil {
			prof = &db.TaskScanProfile{TaskID: req.TaskID, ScanMode: "full"}
		}
		prof.BundleID = req.BundleID
		_ = s.m.pg.UpsertTaskScanProfile(*prof)
	}
	cur := s.loadSharedContext()
	cur.BundleID = req.BundleID
	if req.TaskID > 0 {
		cur.TaskID = req.TaskID
	}
	if req.ConversationID > 0 {
		cur.ConversationID = req.ConversationID
	}
	_ = s.saveSharedContext(cur)
	writeJSON(w, 200, map[string]any{"ok": true, "bundle_id": req.BundleID, "shared_context": s.buildSharedContextResponse()})
}

// buildEnterprisePolicyDirectiveForChat injects the active Scan Operation Mode and
// reusable Scan Context Bundle (Auth/OpenAPI/Postman/TestPolicy) into /chat prompts.
func (s *Server) buildEnterprisePolicyDirectiveForChat(convID int64) string {
	if s == nil || s.m == nil || s.m.pg == nil {
		return ""
	}
	cur := s.loadSharedContext()
	mode := strings.TrimSpace(cur.ScanMode)
	bundleID := cur.BundleID

	var activeTaskID int64 = cur.TaskID
	if convID > 0 {
		if links, err := s.m.pg.ListConversationLinks(convID); err == nil {
			for _, l := range links {
				if l.TaskID != nil && *l.TaskID > 0 {
					activeTaskID = *l.TaskID
					if prof, perr := s.m.pg.GetTaskScanProfile(*l.TaskID); perr == nil && prof != nil {
						if prof.ScanMode != "" && prof.ScanMode != "full" {
							mode = prof.ScanMode
						}
						if prof.BundleID > 0 {
							bundleID = prof.BundleID
						}
					}
					break
				}
			}
		}
	}

	var bundle *db.ScanContextBundle
	if bundleID > 0 {
		bundle, _ = s.m.pg.GetScanBundle(bundleID)
	}
	_, pbBrief := s.buildPlaybookBriefingForTask(activeTaskID, cur.Target)
	if (mode == "" || mode == "full") && bundle == nil && pbBrief == "" {
		return ""
	}
	var sb strings.Builder
	if (mode != "" && mode != "full") || bundle != nil {
		sb.WriteString("[Enterprise Scan Policy & Reusable Context Bundle]\n")
	}
	if mode != "" && mode != "full" {
		switch mode {
		case "explore_only":
			sb.WriteString("- Scan Mode: EXPLORE_ONLY — Map attack surface, assets, routes, and scripts ONLY; do NOT run active exploit payloads.\n")
		case "test_only":
			sb.WriteString("- Scan Mode: TEST_ONLY — Skip initial broad recon; directly run vulnerability tests against already-mapped assets/endpoints.\n")
		case "retest":
			sb.WriteString("- Scan Mode: RETEST — Re-verify existing open/reopened findings only and confirm whether each is Fixed or Reopened.\n")
		case "report_only":
			sb.WriteString("- Scan Mode: REPORT_ONLY — Do NOT scan target; directly call generate_task_report to assemble updated .docx and .md reports.\n")
		}
	}
	if bundle != nil {
		sb.WriteString(formatScanBundleBriefing(bundle))
		if len(bundle.AuthConfig) > 0 {
			if rawAuth, err := json.Marshal(bundle.AuthConfig); err == nil {
				sb.WriteString("  Auth Config JSON: " + string(rawAuth) + "\n")
			}
		}
	}
	if pbBrief != "" {
		if sb.Len() > 0 {
			sb.WriteByte('\n')
		}
		sb.WriteString(pbBrief)
	}
	return strings.TrimSpace(sb.String())
}

// hookEnterpriseOnTaskComplete is called from Engine.setTaskGoalMet so every completed
// task automatically runs Cross-Run Correlation, Control-Plane Quality Gate evaluation,
// and pgvector Semantic Playbook harvesting.
func (s *Server) hookEnterpriseOnTaskComplete(taskIDStr string) {
	tid, err := strconv.ParseInt(strings.TrimSpace(taskIDStr), 10, 64)
	if err != nil || tid <= 0 {
		return
	}
	go func() {
		if _, cerr := s.m.pg.CorrelateTaskFindings(tid); cerr != nil {
			log.Printf("[enterprise] correlate task #%d: %v", tid, cerr)
		}
		if synced, perr := s.m.pg.SyncPlaybooksFromHistory(tid); perr == nil && synced > 0 {
			log.Printf("[playbooks] auto-indexed %d semantic playbook(s) from task #%d into pgvector", synced, tid)
		}
		if gate, gerr := s.EvaluateTaskQualityGate(tid, "control_plane"); gerr != nil {
			log.Printf("[enterprise] gate task #%d: %v", tid, gerr)
		} else if gate != nil {
			log.Printf("[enterprise] task #%d Control-Plane Gate -> %s (%s): %s", tid, gate.GateStatus, gate.ExitCode, gate.ExitReason)
		}
	}()
}
