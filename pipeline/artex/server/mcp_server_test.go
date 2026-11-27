package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/mcphttp"
)

func TestMCPAuthAndHTTPMethods(t *testing.T) {
	s, _, _ := trafficEvidenceServer(t)
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	// Unauthenticated requests are rejected cleanly.
	resp, err := http.Post(ts.URL+"/mcp", "application/json", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"ping"}`))
	if err != nil {
		t.Fatalf("POST /mcp unauthenticated: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("POST /mcp unauthenticated status = %d, want 401", resp.StatusCode)
	}

	// Authenticated GET returns 405 Method Not Allowed (POST-only Streamable HTTP).
	getReq, _ := http.NewRequest(http.MethodGet, ts.URL+"/mcp", nil)
	getReq.Header.Set("X-API-Key", s.mcpAPIKey())
	getResp, err := http.DefaultClient.Do(getReq)
	if err != nil {
		t.Fatalf("GET /mcp: %v", err)
	}
	getResp.Body.Close()
	if getResp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("GET /mcp status = %d, want 405", getResp.StatusCode)
	}
}

func TestMCPEndToEndSharedTaskFlow(t *testing.T) {
	s, _, request := trafficEvidenceServer(t)
	pg := s.m.pg
	if err := pg.EnsurePipelineTables(); err != nil {
		t.Fatalf("EnsurePipelineTables: %v", err)
	}

	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	ctx := context.Background()
	cl, err := mcphttp.New(ctx, "artex", ts.URL+"/mcp", map[string]string{
		"X-API-Key": s.mcpAPIKey(),
	}, false, 15)
	if err != nil {
		t.Fatalf("mcphttp.New: %v", err)
	}
	defer cl.Close()

	tools, err := cl.Tools(ctx)
	if err != nil {
		t.Fatalf("cl.Tools: %v", err)
	}
	if len(tools) < 15 {
		t.Fatalf("expected >= 15 ARTEX MCP tools, got %d", len(tools))
	}

	// 1. Start shared target assessment from Deep Agent IDE (/ai) — paused by default, linked conv created.
	rawStart, err := cl.Call(ctx, "start_target_assessment", map[string]any{
		"target":             "https://app.shared-e2e.example",
		"launch_scopesentry": false,
		"description":        "Shared E2E Task",
	})
	if err != nil {
		t.Fatalf("start_target_assessment: %v", err)
	}
	var startRes targetAssessmentResult
	if err := json.Unmarshal([]byte(rawStart), &startRes); err != nil {
		t.Fatalf("decode start_target_assessment: %v (%s)", err, rawStart)
	}
	if startRes.TaskID <= 0 || startRes.ConversationID <= 0 || startRes.CompanyID <= 0 {
		t.Fatalf("unexpected start_target_assessment IDs: %+v", startRes)
	}
	t.Cleanup(func() {
		_ = pg.DeleteConversation(startRes.ConversationID)
		_, _ = s.m.DeleteTask(strconv.FormatInt(startRes.TaskID, 10), DeleteTaskOptions{DeleteFiles: true})
		_, _ = pg.Exec(`DELETE FROM companies WHERE id=$1`, startRes.CompanyID)
	})

	taskObj, ok := s.m.Task(strconv.FormatInt(startRes.TaskID, 10))
	if !ok || taskObj == nil {
		t.Fatalf("created task #%d missing from manager", startRes.TaskID)
	}
	if status := s.deriveTaskStatus(taskObj); status != "paused" {
		t.Fatalf("expected paused manual-ready status when start_autonomous_workers=false, got %q", status)
	}

	// 2. Repeating start_target_assessment for same host attaches to the same task instead of duplicating.
	rawReattach, err := cl.Call(ctx, "start_target_assessment", map[string]any{
		"target":             "https://app.shared-e2e.example/login",
		"launch_scopesentry": false,
	})
	if err != nil {
		t.Fatalf("re-attach start_target_assessment: %v", err)
	}
	var reattach targetAssessmentResult
	if err := json.Unmarshal([]byte(rawReattach), &reattach); err != nil {
		t.Fatalf("decode reattach: %v", err)
	}
	if !reattach.AlreadyOnboarded || reattach.TaskID != startRes.TaskID {
		t.Fatalf("expected attach to task #%d (already_onboarded=true), got %+v", startRes.TaskID, reattach)
	}

	// 3. Verify get_active_context reflects the newly onboarded task & conversation.
	rawCtx, err := cl.Call(ctx, "get_active_context", map[string]any{})
	if err != nil {
		t.Fatalf("get_active_context: %v", err)
	}
	var activeCtx sharedContextResponse
	if err := json.Unmarshal([]byte(rawCtx), &activeCtx); err != nil {
		t.Fatalf("decode active context: %v", err)
	}
	if activeCtx.TaskID != startRes.TaskID || activeCtx.ConversationID != startRes.ConversationID {
		t.Fatalf("active context mismatch: got %+v, want task=%d conv=%d", activeCtx, startRes.TaskID, startRes.ConversationID)
	}

	// 4. Register goals/constraints, create & run an intent, insert assets, record a fact,
	//    add a planner hint, ingest HTTP traffic, report a finding, and prove the goal met
	//    WITHOUT passing task_id explicitly (verifying automatic active shared task resolution).
	rawGoals, err := cl.Call(ctx, "set_goals", map[string]any{
		"text":      "Verify admin API authentication enforcement",
		"vulnclass": "Broken Function Level Authorization",
	})
	if err != nil || !strings.Contains(rawGoals, "goal added:") {
		t.Fatalf("set_goals failed: %q err=%v", rawGoals, err)
	}

	rawGoalList, err := cl.Call(ctx, "list_goals", map[string]any{})
	if err != nil {
		t.Fatalf("list_goals failed: %v", err)
	}
	var goalNodes []db.Node
	if err := json.Unmarshal([]byte(rawGoalList), &goalNodes); err != nil || len(goalNodes) == 0 {
		t.Fatalf("unexpected list_goals output: %q err=%v", rawGoalList, err)
	}
	if goalNodes[0].State != "open" {
		t.Fatalf("expected open goal state, got %q", goalNodes[0].State)
	}

	rawConstraint, err := cl.Call(ctx, "set_constraints", map[string]any{
		"text": "Do not execute destructive write requests",
		"type": "deny",
	})
	if err != nil || !strings.Contains(rawConstraint, "constraint added:") {
		t.Fatalf("set_constraints failed: %q err=%v", rawConstraint, err)
	}

	rawIntent, err := cl.Call(ctx, "add_intent", map[string]any{
		"summary":  "Probe /api/v1/admin authentication guard",
		"priority": 8,
	})
	if err != nil || !strings.Contains(rawIntent, "intent created:") {
		t.Fatalf("add_intent failed: %q err=%v", rawIntent, err)
	}
	intentID, err := strconv.ParseInt(strings.TrimSpace(strings.TrimPrefix(rawIntent, "intent created:")), 10, 64)
	if err != nil || intentID <= 0 {
		t.Fatalf("failed to parse intent_id from %q: %v", rawIntent, err)
	}

	rawStateRun, err := cl.Call(ctx, "update_intent_state", map[string]any{
		"intent_id": intentID,
		"state":     "running",
	})
	if err != nil || !strings.Contains(rawStateRun, `"running"`) {
		t.Fatalf("update_intent_state(running) failed: %q err=%v", rawStateRun, err)
	}

	if _, err := cl.Call(ctx, "insert_assets", map[string]any{
		"assets": []map[string]any{
			{"type": "endpoint", "url": "https://app.shared-e2e.example/api/v1/admin", "method": "GET"},
		},
	}); err != nil {
		t.Fatalf("insert_assets: %v", err)
	}

	rawFact, err := cl.Call(ctx, "record_fact", map[string]any{
		"intent_id":  intentID,
		"summary":    "Audited /api/v1/admin handler in Deep Agent IDE",
		"detail":     "Missing role check before user query",
		"evidence":   "GET /api/v1/admin returned 200 without admin role",
		"confidence": "observed",
		"source":     "target_response",
	})
	if err != nil || !strings.Contains(rawFact, "fact recorded:") {
		t.Fatalf("record_fact unexpected result: %q, err=%v", rawFact, err)
	}

	rawStateDone, err := cl.Call(ctx, "update_intent_state", map[string]any{
		"intent_id": intentID,
		"state":     "done",
	})
	if err != nil || !strings.Contains(rawStateDone, `"done"`) {
		t.Fatalf("update_intent_state(done) failed: %q err=%v", rawStateDone, err)
	}

	if _, err := cl.Call(ctx, "add_task_hint", map[string]any{
		"text": "Check sibling /api/v1/users endpoint for same missing auth guard",
	}); err != nil {
		t.Fatalf("add_task_hint: %v", err)
	}

	rawTraffic, err := cl.Call(ctx, "ingest_traffic", map[string]any{
		"method":           "GET",
		"url":              "https://app.shared-e2e.example/api/v1/admin",
		"status":           200,
		"request_headers":  map[string]string{"Accept": "application/json"},
		"response_headers": map[string]string{"content-type": "application/json"},
		"response_body":    `{"users":["admin","alice"]}`,
	})
	if err != nil {
		t.Fatalf("ingest_traffic: %v", err)
	}
	var trafficOut struct {
		TrafficID string `json:"traffic_id"`
	}
	if err := json.Unmarshal([]byte(rawTraffic), &trafficOut); err != nil || trafficOut.TrafficID == "" {
		t.Fatalf("unexpected ingest_traffic output: %q (%v)", rawTraffic, err)
	}

	rawFinding, err := cl.Call(ctx, "report_finding", map[string]any{
		"intent_id": intentID,
		"vulnclass": "Broken Function Level Authorization",
		"name":      "Unauthenticated Admin API Access",
		"severity":  "high",
		"summary":   "/api/v1/admin leaks admin user list",
		"target":    "https://app.shared-e2e.example/api/v1/admin",
		"evidence":  "GET /api/v1/admin returned HTTP 200 with users JSON",
		"traffic_refs": []map[string]any{
			{"traffic_id": trafficOut.TrafficID, "role": "proof", "note": "Reproducible response"},
		},
	})
	if err != nil || !strings.Contains(rawFinding, "finding recorded:") {
		t.Fatalf("report_finding failed: %q err=%v", rawFinding, err)
	}
	var recFinding db.RecordedFinding
	if lines := strings.SplitN(rawFinding, "\n", 2); len(lines) == 2 {
		if err := json.Unmarshal([]byte(lines[1]), &recFinding); err != nil || recFinding.NodeID <= 0 {
			t.Fatalf("failed to decode finding_node_id from %q: %v", rawFinding, err)
		}
	}

	if _, err := cl.Call(ctx, "prove_goal", map[string]any{
		"goal_id":     goalNodes[0].ID,
		"evidence_id": recFinding.NodeID,
		"reason":      "Verified unauthenticated access to /api/v1/admin",
	}); err != nil {
		t.Fatalf("prove_goal failed: %v", err)
	}
	rawGoalAfter, err := cl.Call(ctx, "list_goals", map[string]any{})
	if err != nil {
		t.Fatalf("list_goals after prove failed: %v", err)
	}
	var goalsAfter []db.Node
	if err := json.Unmarshal([]byte(rawGoalAfter), &goalsAfter); err != nil || len(goalsAfter) == 0 || goalsAfter[0].State != "met" {
		t.Fatalf("expected goal state met after prove_goal, got %q (err=%v)", rawGoalAfter, err)
	}

	// Verify finding landed in PostgreSQL findings AND exploration graph of that task.
	taskFindings, _, err := pg.ListFindingsPage(db.FindingFilter{TaskID: strconv.FormatInt(startRes.TaskID, 10)}, 1, 20)
	if err != nil || len(taskFindings) == 0 {
		t.Fatalf("expected persisted finding on task #%d, got len=%d err=%v", startRes.TaskID, len(taskFindings), err)
	}

	// 5. Post a Deep Agent handoff note back to the linked /chat conversation.
	if _, err := cl.Call(ctx, "post_chat_note", map[string]any{
		"summary": "Deep Agent IDE finished /api/v1/admin verification",
		"message": "Found Broken Function Level Authorization on /api/v1/admin; hand back to Graph Chat for broader API fuzzing.",
	}); err != nil {
		t.Fatalf("post_chat_note: %v", err)
	}

	acts, _, err := pg.ConvActivityList(startRes.ConversationID, 0, 50)
	if err != nil || len(acts) < 2 {
		t.Fatalf("expected linked conversation activities (intro + handoff), got %d err=%v", len(acts), err)
	}

	rawHistory, err := cl.Call(ctx, "get_chat_history", map[string]any{})
	if err != nil || !strings.Contains(rawHistory, "Broken Function Level Authorization") {
		t.Fatalf("get_chat_history missing handoff note: %q err=%v", rawHistory, err)
	}

	rawBriefing, err := cl.Call(ctx, "get_shared_briefing", map[string]any{})
	if err != nil || !strings.Contains(rawBriefing, "app.shared-e2e.example") || !strings.Contains(rawBriefing, "Unauthenticated Admin API Access") {
		t.Fatalf("get_shared_briefing missing task/finding context: %q err=%v", rawBriefing, err)
	}

	// 6. Verify HTTP shared-context API works for Unified Web UI.
	w := request(http.MethodGet, "/api/shared-context", "")
	if w.Code != http.StatusOK {
		t.Fatalf("GET /api/shared-context status = %d body=%s", w.Code, w.Body.String())
	}
	var httpCtx sharedContextResponse
	if err := json.Unmarshal(w.Body.Bytes(), &httpCtx); err != nil {
		t.Fatalf("decode GET /api/shared-context: %v", err)
	}
	if httpCtx.TaskID != startRes.TaskID || httpCtx.FindingCount < 1 {
		t.Fatalf("GET /api/shared-context unexpected payload: %+v", httpCtx)
	}
}
