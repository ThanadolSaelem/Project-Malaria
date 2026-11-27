package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"

	"github.com/Autumn-27/artex/agent"
	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/intercept"
	actool "github.com/Autumn-27/norma/tool"
)

func TestPipelineSplitAndBuildTargetMeta(t *testing.T) {
	got := splitTargets("https://www.nectec.or.th/foo, 10.0.0.1", []string{
		"10.0.0.1\napi.nectec.or.th;10.0.0.0/24",
		"https://www.nectec.or.th/foo",
	})
	want := []string{
		"https://www.nectec.or.th/foo",
		"10.0.0.1",
		"api.nectec.or.th",
		"10.0.0.0/24",
	}
	if len(got) != len(want) {
		t.Fatalf("splitTargets len = %d (%v), want %d (%v)", len(got), got, len(want), want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("splitTargets[%d] = %q, want %q", i, got[i], want[i])
		}
	}

	company, scopes, ssTargets, primary := buildTargetMeta(
		[]string{"https://www.nectec.or.th/portal", "192.168.1.50:8443", "10.20.0.0/16"},
		"intranet.nectec.or.th; 10.21.0.0/24",
		"",
	)
	if company != "nectec.or.th" {
		t.Fatalf("company = %q, want %q", company, "nectec.or.th")
	}
	if primary != "https://www.nectec.or.th/portal" {
		t.Fatalf("primary = %q, want %q", primary, "https://www.nectec.or.th/portal")
	}
	scopeJoin := strings.Join(scopes, "|")
	for _, sub := range []string{"nectec.or.th", "www.nectec.or.th", "192.168.1.50", "10.20.0.0/16", "intranet.nectec.or.th", "10.21.0.0/24"} {
		if !strings.Contains(scopeJoin, sub) {
			t.Fatalf("expected scope %q in %v", sub, scopes)
		}
	}
	if len(ssTargets) != 3 {
		t.Fatalf("ssTargets = %v, want 3 entries", ssTargets)
	}

	overrideCompany, _, _, _ := buildTargetMeta([]string{"https://www.nectec.or.th"}, "", "NECTEC Org")
	if overrideCompany != "NECTEC Org" {
		t.Fatalf("overrideCompany = %q, want %q", overrideCompany, "NECTEC Org")
	}
}

type mockSSRecorder struct {
	createProjectArgs  map[string]any
	createScanTaskArgs map[string]any
}

func startMockScopeSentryMCP(t *testing.T, rec *mockSSRecorder) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodDelete {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			JSONRPC string          `json:"jsonrpc"`
			ID      json.RawMessage `json:"id"`
			Method  string          `json:"method"`
			Params  json.RawMessage `json:"params"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if req.Method == "notifications/initialized" || len(req.ID) == 0 || string(req.ID) == "null" {
			w.WriteHeader(http.StatusAccepted)
			return
		}

		writeRPC := func(res any) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Mcp-Session-Id", "mock-ss-session")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      json.RawMessage(req.ID),
				"result":  res,
			})
		}

		switch req.Method {
		case "initialize":
			writeRPC(map[string]any{
				"protocolVersion": "2025-06-18",
				"capabilities":    map[string]any{"tools": map[string]any{}},
				"serverInfo":      map[string]any{"name": "mock-scopesentry", "version": "1.0"},
			})
		case "tools/list":
			writeRPC(map[string]any{"tools": []any{}})
		case "tools/call":
			var call struct {
				Name      string         `json:"name"`
				Arguments map[string]any `json:"arguments"`
			}
			_ = json.Unmarshal(req.Params, &call)
			toolText := func(payload any) {
				b, _ := json.Marshal(payload)
				writeRPC(map[string]any{
					"content": []map[string]any{{"type": "text", "text": string(b)}},
					"isError": false,
				})
			}
			switch call.Name {
			case "list_nodes":
				toolText(map[string]any{
					"list": []map[string]any{
						{"name": "node-malaria", "state": "1"},
					},
				})
			case "list_scan_templates":
				toolText(map[string]any{
					"list": []map[string]any{
						{"id": "tpl-custom", "name": "quick"},
						{"id": "6af7c25e801c8cc361293b2a", "name": "default"},
					},
				})
			case "create_project":
				rec.createProjectArgs = call.Arguments
				toolText(map[string]any{"id": "proj-nectec-1", "message": "ok"})
			case "create_scan_task":
				rec.createScanTaskArgs = call.Arguments
				toolText(map[string]any{"id": "sstask-nectec-1", "message": "ok"})
			case "get_task":
				toolText(map[string]any{"name": "artex-nectec.or.th", "status": 1, "progress": 65})
			case "list_assets":
				at, _ := call.Arguments["asset_type"].(string)
				switch at {
				case "project":
					toolText(map[string]any{
						"total": 1,
						"list": []map[string]any{
							{"id": "proj-nectec-1", "name": "nectec.or.th", "target": "https://www.nectec.or.th/portal"},
						},
					})
				case "subdomain":
					toolText(map[string]any{
						"total": 1,
						"list": []map[string]any{
							{"host": "api.nectec.or.th", "ip": []string{"203.185.132.10"}},
						},
					})
				case "asset", "service":
					toolText(map[string]any{
						"total": 1,
						"list": []map[string]any{
							{"url": "https://api.nectec.or.th", "domain": "api.nectec.or.th", "ip": "203.185.132.10", "port": "443", "service": "https", "title": "NECTEC API", "status": 200},
						},
					})
				case "app":
					toolText(map[string]any{"total": 0, "list": []any{}})
				case "vulnerability":
					toolText(map[string]any{
						"total": 1,
						"list": []map[string]any{
							{
								"vulnerability": "Reflected XSS",
								"url":           "https://www.nectec.or.th/search?q=1",
								"matched":       "https://www.nectec.or.th/search?q=1",
								"level":         "high",
								"rootDomain":    "nectec.or.th",
							},
						},
					})
				default:
					toolText(map[string]any{"total": 0, "list": []any{}})
				}
			default:
				toolText(map[string]any{})
			}
		default:
			writeRPC(map[string]any{})
		}
	}))
}

func TestStartTargetAssessmentAndConversationPipeline(t *testing.T) {
	s, _, request := trafficEvidenceServer(t)
	pg := s.m.pg

	// Ensure pipeline schema and migration helpers succeed.
	if err := pg.EnsurePipelineTables(); err != nil {
		t.Fatalf("EnsurePipelineTables: %v", err)
	}
	s.migratePipelineToolsAndPrompts()
	for _, flag := range []string{"tool_schema_refresh_v8_pipeline_tools", "pipeline_integration_auto_pentest_v1"} {
		val, ok, err := pg.GetSetting(flag)
		if err != nil || !ok || val != "true" {
			t.Fatalf("setting %s = %q (ok=%v, err=%v), want true", flag, val, ok, err)
		}
	}
	for _, key := range []string{"start_target_assessment", "sync_scopesentry_assets", "add_company_scope", "report_finding", "list_findings"} {
		toolRow, err := pg.GetTool(key)
		if err != nil || toolRow == nil {
			t.Fatalf("expected seeded/migrated tool %q, err=%v", key, err)
		}
		if !slices.Contains(toolRow.Agents, "auto") || !slices.Contains(toolRow.Agents, "pentest") {
			t.Fatalf("tool %q agents = %+v, want both auto and pentest bound", key, toolRow.Agents)
		}
	}

	// Preserve any existing ScopeSentry MCP server row and swap in a mock HTTP MCP server.
	prevSS, _ := s.findMCPByName(scopeSentryMCPName)
	rec := &mockSSRecorder{}
	mockSS := startMockScopeSentryMCP(t, rec)
	defer mockSS.Close()

	mockEnv, _ := json.Marshal(map[string]string{"X-API-Key": "mock-ss-key"})
	mockSSRow := &db.MCPServer{
		Name:           scopeSentryMCPName,
		Transport:      "http",
		URL:            mockSS.URL,
		Env:            mockEnv,
		Enabled:        true,
		TimeoutSeconds: 15,
	}
	if prevSS != nil {
		mockSSRow.ID = prevSS.ID
	}
	ssID, err := pg.SaveMCP(mockSSRow)
	if err != nil {
		t.Fatalf("SaveMCP ScopeSentry mock: %v", err)
	}
	t.Cleanup(func() {
		if prevSS != nil {
			prevSS.ID = ssID
			_, _ = pg.SaveMCP(prevSS)
		} else {
			_ = pg.DeleteMCP(ssID)
		}
	})

	conv, err := pg.CreateConversation("auto", "Pipeline E2E test", nil)
	if err != nil {
		t.Fatalf("CreateConversation: %v", err)
	}
	t.Cleanup(func() { _ = pg.DeleteConversation(conv.ID) })

	ctx := intercept.WithConvID(context.Background(), conv.ID)
	resStr := workflowCall(t, ctx, s.toolStartTargetAssessment(), map[string]any{
		"target":          "https://www.nectec.or.th/portal",
		"seed_first_intent": false,
	}, false)

	var startOut struct {
		CompanyID            int64             `json:"company_id"`
		CompanyName          string            `json:"company_name"`
		Scope                []string          `json:"scope"`
		AssetIDs             []int64           `json:"asset_ids"`
		TaskAssetsLinked     int64             `json:"task_assets_linked"`
		ScopeSentryProjectID string            `json:"scopesentry_project_id"`
		ScopeSentryTaskID    string            `json:"scopesentry_task_id"`
		ScopeSentryNode      string            `json:"scopesentry_node"`
		ScopeSentryTemplate  string            `json:"scopesentry_template"`
		TaskID               int64             `json:"task_id"`
		Routes               map[string]string `json:"routes"`
	}
	if err := json.Unmarshal([]byte(resStr), &startOut); err != nil {
		t.Fatalf("decode start_target_assessment output: %v\nraw: %s", err, resStr)
	}

	t.Cleanup(func() {
		if startOut.TaskID > 0 {
			_, _ = s.m.DeleteTask(strconv.FormatInt(startOut.TaskID, 10), DeleteTaskOptions{DeleteFiles: true})
		}
		if startOut.CompanyID > 0 {
			_, _ = pg.Exec(`DELETE FROM companies WHERE id=$1`, startOut.CompanyID)
		}
	})

	if startOut.CompanyID <= 0 || startOut.CompanyName != "nectec.or.th" {
		t.Fatalf("unexpected company result: %+v", startOut)
	}
	if startOut.TaskID <= 0 {
		t.Fatalf("expected ARTEX task_id > 0, got %+v", startOut)
	}
	if len(startOut.AssetIDs) == 0 || startOut.TaskAssetsLinked == 0 {
		t.Fatalf("expected seeded asset IDs and task_assets_linked > 0, got %+v", startOut)
	}
	if startOut.ScopeSentryProjectID != "proj-nectec-1" || startOut.ScopeSentryTaskID != "sstask-nectec-1" {
		t.Fatalf("unexpected ScopeSentry IDs: %+v", startOut)
	}
	if startOut.ScopeSentryNode != "node-malaria" || startOut.ScopeSentryTemplate != "6af7c25e801c8cc361293b2a" {
		t.Fatalf("unexpected ScopeSentry node/template: %+v", startOut)
	}
	if wantRoute := fmt.Sprintf("/function/tasks/detail?id=%d", startOut.TaskID); startOut.Routes["tasks"] != wantRoute {
		t.Fatalf("routes[tasks] = %q, want %q", startOut.Routes["tasks"], wantRoute)
	}
	if gotSrc, _ := rec.createScanTaskArgs["targetSource"].(string); gotSrc != "project" {
		t.Fatalf("create_scan_task targetSource = %q, want project", gotSrc)
	}
	if gotBind, _ := rec.createScanTaskArgs["bindProject"].(string); gotBind != "proj-nectec-1" {
		t.Fatalf("create_scan_task bindProject = %q, want proj-nectec-1", gotBind)
	}

	// Pause the spawned task engine cleanly before inspecting/cleaning up.
	_ = s.m.ApplyTaskPause(strconv.FormatInt(startOut.TaskID, 10))

	links, err := pg.ListConversationLinks(conv.ID)
	if err != nil || len(links) != 1 {
		t.Fatalf("ListConversationLinks = (%+v, %v), want 1 row", links, err)
	}

	// Verify GET /api/conversations/{id}/links?live=1 enrichment.
	linksResp := request(http.MethodGet, fmt.Sprintf("/api/conversations/%d/links?live=1", conv.ID), "")
	if linksResp.Code != http.StatusOK {
		t.Fatalf("GET links status = %d: %s", linksResp.Code, linksResp.Body.String())
	}
	var linksPayload struct {
		Links []enrichedConversationLink `json:"links"`
	}
	if err := json.Unmarshal(linksResp.Body.Bytes(), &linksPayload); err != nil || len(linksPayload.Links) != 1 {
		t.Fatalf("decode links payload: %v body=%s", err, linksResp.Body.String())
	}
	if linksPayload.Links[0].SSTaskName != "artex-nectec.or.th" || linksPayload.Links[0].SSProgress == nil || *linksPayload.Links[0].SSProgress != 65 {
		t.Fatalf("unexpected live ScopeSentry enrichment: %+v", linksPayload.Links[0])
	}

	// Clean any leftover test findings with this mock title so repeated runs remain deterministic.
	_, _ = pg.Exec(`DELETE FROM findings WHERE name LIKE $1`, "[ScopeSentry] Reflected XSS%")
	t.Cleanup(func() {
		_, _ = pg.Exec(`DELETE FROM findings WHERE name LIKE $1`, "[ScopeSentry] Reflected XSS%")
	})

	// Verify POST /api/conversations/{id}/sync pulls ScopeSentry assets AND vulnerabilities into ARTEX.
	syncResp := request(http.MethodPost, fmt.Sprintf("/api/conversations/%d/sync", conv.ID), `{}`)
	if syncResp.Code != http.StatusOK {
		t.Fatalf("POST sync status = %d: %s", syncResp.Code, syncResp.Body.String())
	}
	var syncPayload struct {
		OK   bool          `json:"ok"`
		Sync *ssSyncResult `json:"sync"`
	}
	if err := json.Unmarshal(syncResp.Body.Bytes(), &syncPayload); err != nil || !syncPayload.OK || syncPayload.Sync == nil {
		t.Fatalf("decode sync payload: %v body=%s", err, syncResp.Body.String())
	}
	if syncPayload.Sync.Synced["subdomain"] == 0 || syncPayload.Sync.Synced["service"] == 0 || syncPayload.Sync.Synced["vulnerability"] == 0 {
		t.Fatalf("expected synced subdomain, service, and vulnerability > 0, got %+v", syncPayload.Sync.Synced)
	}

	findings, _, err := pg.ListFindingsPage(db.FindingFilter{TaskID: strconv.FormatInt(startOut.TaskID, 10)}, 1, 50)
	if err != nil {
		t.Fatalf("ListFindings: %v", err)
	}
	hasSSVuln := false
	for _, f := range findings {
		if strings.Contains(f.Name, "[ScopeSentry] Reflected XSS") {
			hasSSVuln = true
			break
		}
	}
	if !hasSSVuln {
		t.Fatalf("expected ScopeSentry vulnerability finding linked to task %d, got %+v", startOut.TaskID, findings)
	}

	// Verify taskless report_finding inside /chat conversation auto-attributes to linked task
	// and update_finding_report falls back to standalone finding ID.
	ts := agent.NewToolSet(nil, "auto")
	ts.SetDB(pg)
	ts.SetAssetStore(s.assetStore(), s.companyStore())
	ts.SetFindingRecorder(s.evidenceStore())
	domainTools := ts.AllDomainTools()
	var reportTool actool.CoreTool
	for _, dt := range domainTools {
		if dt.Name() == "report_finding" {
			reportTool = dt
			break
		}
	}
	if reportTool == nil {
		t.Fatal("report_finding missing from ToolSet.AllDomainTools()")
	}

	// Ensure auto-binding does not block standalone chat finding without traffic_refs.
	if r := request("PUT", "/api/settings", `{"agent_traffic_binding":false}`); r.Code != 200 {
		t.Fatalf("disable traffic binding setting: %d %s", r.Code, r.Body.String())
	}
	repStr := workflowCall(t, ctx, reportTool, map[string]any{
		"vulnclass": "CONFIG",
		"name":      "Missing Security Headers",
		"severity":  "low",
		"summary":   "X-Frame-Options missing on https://www.nectec.or.th/portal",
		"target":    "https://www.nectec.or.th/portal",
		"evidence":  "HTTP/1.1 200 OK without X-Frame-Options",
	}, false)
	var repOut struct {
		FindingID json.RawMessage `json:"finding_id"`
		NodeID    json.RawMessage `json:"finding_node_id"`
		TaskID    int64           `json:"task_id"`
	}
	jsonPart := repStr
	if idx := strings.Index(repStr, "{"); idx >= 0 {
		jsonPart = repStr[idx:]
	}
	if err := json.Unmarshal([]byte(jsonPart), &repOut); err != nil {
		t.Fatalf("decode report_finding output: %v\nraw: %s", err, repStr)
	}
	fid := parseProfileID(repOut.FindingID)
	nid := parseProfileID(repOut.NodeID)
	if fid <= 0 || nid <= 0 || repOut.TaskID != startOut.TaskID {
		t.Fatalf("expected chat finding attributed to task %d, got fid=%d nid=%d task_id=%d raw=%s", startOut.TaskID, fid, nid, repOut.TaskID, repStr)
	}
	t.Cleanup(func() { _, _ = pg.Exec(`DELETE FROM findings WHERE id=$1`, fid) })

	// update_finding_report using the linked finding_id / node_id.
	workflowCall(t, ctx, s.toolUpdateFindingReport(), map[string]any{
		"finding_id": fid,
		"report":     "## Updated Chat Finding Report\nVerified header omission.",
	}, false)

	// True taskless standalone report_finding (outside any linked task) + standalone update_finding_report fallback.
	standaloneStr := workflowCall(t, context.Background(), reportTool, map[string]any{
		"vulnclass": "INFO",
		"name":      "Standalone Banner Disclosure",
		"severity":  "low",
		"summary":   "Standalone /chat finding without task_id",
		"target":    "https://www.nectec.or.th/portal",
		"evidence":  "Server: nginx",
	}, false)
	var stOut struct {
		FindingID json.RawMessage `json:"finding_id"`
		NodeID    json.RawMessage `json:"finding_node_id"`
		TaskID    int64           `json:"task_id"`
	}
	stJSON := standaloneStr
	if idx := strings.Index(standaloneStr, "{"); idx >= 0 {
		stJSON = standaloneStr[idx:]
	}
	if err := json.Unmarshal([]byte(stJSON), &stOut); err != nil {
		t.Fatalf("decode standalone report_finding: %v\nraw: %s", err, standaloneStr)
	}
	stFID := parseProfileID(stOut.FindingID)
	stNID := parseProfileID(stOut.NodeID)
	if stFID <= 0 || stNID != 0 || stOut.TaskID != 0 {
		t.Fatalf("expected standalone taskless finding, got fid=%d nid=%d task_id=%d raw=%s", stFID, stNID, stOut.TaskID, standaloneStr)
	}
	t.Cleanup(func() { _, _ = pg.Exec(`DELETE FROM findings WHERE id=$1`, stFID) })
	workflowCall(t, context.Background(), s.toolUpdateFindingReport(), map[string]any{
		"finding_id": stFID,
		"report":     "## Updated Standalone Report\nFallback by finding.id worked.",
	}, false)

	// Verify spawn_task compatibility (without target vs with target).
	plainSpawn := workflowCall(t, ctx, s.toolSpawnTask(), map[string]any{
		"description": "plain spawned task",
		"goal":        "check compatibility",
	}, false)
	plainIDStr, hasPrefix := strings.CutPrefix(plainSpawn, "task created: ")
	if !hasPrefix {
		t.Fatalf("plain spawn_task output = %q, want prefix 'task created: '", plainSpawn)
	}
	if plainID, err := strconv.ParseInt(strings.TrimSpace(plainIDStr), 10, 64); err == nil && plainID > 0 {
		t.Cleanup(func() {
			_, _ = s.m.DeleteTask(strconv.FormatInt(plainID, 10), DeleteTaskOptions{DeleteFiles: true})
		})
	}

	targetSpawn := workflowCall(t, ctx, s.toolSpawnTask(), map[string]any{
		"description": "scoped spawned task",
		"goal":        "assess portal.example.org",
		"target":      "https://portal.example.org",
		"company":     "Example Pipeline Org",
	}, false)
	if !strings.HasPrefix(targetSpawn, "task created: ") {
		t.Fatalf("targeted spawn_task missing 'task created: ' prefix: %q", targetSpawn)
	}
	targetSpawnJSON := targetSpawn
	if idx := strings.Index(targetSpawn, "{"); idx >= 0 {
		targetSpawnJSON = targetSpawn[idx:]
	}
	var targetSpawnOut struct {
		TaskID    json.RawMessage `json:"task_id"`
		CompanyID int64           `json:"company_id"`
		Company   string          `json:"company_name"`
	}
	if err := json.Unmarshal([]byte(targetSpawnJSON), &targetSpawnOut); err != nil {
		t.Fatalf("decode targeted spawn_task: %v raw=%s", err, targetSpawn)
	}
	spawnTID := parseProfileID(targetSpawnOut.TaskID)
	t.Cleanup(func() {
		if spawnTID > 0 {
			_, _ = s.m.DeleteTask(strconv.FormatInt(spawnTID, 10), DeleteTaskOptions{DeleteFiles: true})
		}
		if targetSpawnOut.CompanyID > 0 {
			_, _ = pg.Exec(`DELETE FROM companies WHERE id=$1`, targetSpawnOut.CompanyID)
		}
	})
	if spawnTID <= 0 || targetSpawnOut.CompanyID <= 0 || targetSpawnOut.Company != "Example Pipeline Org" {
		t.Fatalf("unexpected targeted spawn_task result: tid=%d out=%+v raw=%s", spawnTID, targetSpawnOut, targetSpawn)
	}
}

func TestAutoOnboardChatTargetsAndTrafficDefault(t *testing.T) {
	s, _, request := trafficEvidenceServer(t)
	pg := s.m.pg

	// Reference sites, self UI URLs, and filenames should never trigger onboarding,
	// whereas real operator target URLs (even inside short Thai prompts) must.
	msg := "ลองเช็ค payload จาก https://portswigger.net/web-security และเปิดดู http://127.0.0.1:3000/function/findings และ probe.py แล้วตรวจสอบอย่างระมัดระวังที่ link https://app-4d8a418511352e55.up.railway.app"
	gotTargets := s.extractUnlinkedChatTargets(0, msg)
	if len(gotTargets) != 1 || gotTargets[0] != "https://app-4d8a418511352e55.up.railway.app" {
		t.Fatalf("extractUnlinkedChatTargets = %v, want [https://app-4d8a418511352e55.up.railway.app]", gotTargets)
	}

	// Preserve any existing ScopeSentry MCP server row and swap in a mock HTTP MCP server.
	prevSS, _ := s.findMCPByName(scopeSentryMCPName)
	rec := &mockSSRecorder{}
	mockSS := startMockScopeSentryMCP(t, rec)
	defer mockSS.Close()

	mockEnv, _ := json.Marshal(map[string]string{"X-API-Key": "mock-ss-key"})
	mockSSRow := &db.MCPServer{
		Name:           scopeSentryMCPName,
		Transport:      "http",
		URL:            mockSS.URL,
		Env:            mockEnv,
		Enabled:        true,
		TimeoutSeconds: 15,
	}
	if prevSS != nil {
		mockSSRow.ID = prevSS.ID
	}
	ssID, err := pg.SaveMCP(mockSSRow)
	if err != nil {
		t.Fatalf("SaveMCP ScopeSentry mock: %v", err)
	}
	t.Cleanup(func() {
		if prevSS != nil {
			prevSS.ID = ssID
			_, _ = pg.SaveMCP(prevSS)
		} else {
			_ = pg.DeleteMCP(ssID)
		}
	})

	conv, err := pg.CreateConversation("auto", "Auto-onboard test", nil)
	if err != nil {
		t.Fatalf("CreateConversation: %v", err)
	}
	t.Cleanup(func() { _ = pg.DeleteConversation(conv.ID) })

	ctx := intercept.WithConvID(context.Background(), conv.ID)
	note := s.maybeAutoOnboardChatTurn(ctx, conv, "ตรวจสอบอย่างระมัดระวังที่ link https://app-auto-onboard.example.test")
	if !strings.Contains(note, "[System Auto-Onboard Pipeline]") {
		t.Fatalf("expected auto-onboard context note, got %q", note)
	}

	links, err := pg.ListConversationLinks(conv.ID)
	if err != nil || len(links) != 1 || links[0].TaskID == nil || *links[0].TaskID <= 0 || links[0].CompanyID == nil {
		t.Fatalf("expected 1 auto-onboarded link with task/company, got %+v (err=%v)", links, err)
	}
	tid := *links[0].TaskID
	cid := *links[0].CompanyID
	_ = s.m.ApplyTaskPause(strconv.FormatInt(tid, 10))
	t.Cleanup(func() {
		_, _ = s.m.DeleteTask(strconv.FormatInt(tid, 10), DeleteTaskOptions{DeleteFiles: true})
		_, _ = pg.Exec(`DELETE FROM companies WHERE id=$1`, cid)
	})

	// Follow-up mention of the same target must NOT spawn duplicate tasks.
	if dupNote := s.maybeAutoOnboardChatTurn(ctx, conv, "สรุปสถานะของ https://app-auto-onboard.example.test"); dupNote != "" {
		t.Fatalf("follow-up on linked target should not duplicate onboarding, got %q", dupNote)
	}
	// Redundant start_target_assessment in the same conversation reuses the link.
	dupToolOut := workflowCall(t, ctx, s.toolStartTargetAssessment(), map[string]any{
		"target": "https://app-auto-onboard.example.test/api",
	}, false)
	var dupRes targetAssessmentResult
	if err := json.Unmarshal([]byte(dupToolOut), &dupRes); err != nil || !dupRes.AlreadyOnboarded || dupRes.TaskID != tid {
		t.Fatalf("expected start_target_assessment dedup reuse of task %d, got err=%v raw=%s", tid, err, dupToolOut)
	}

	// Idempotent default enabling of agent_traffic_binding respects later user opt-out.
	_, _ = pg.Exec(`DELETE FROM settings WHERE key IN ($1, 'project_malaria_traffic_binding_v1')`, settingAgentTrafficBinding)
	s.seedProjectMalariaTrafficBinding()
	if !pg.GetBool(settingAgentTrafficBinding, false) {
		t.Fatal("expected project_malaria_traffic_binding_v1 to enable agent_traffic_binding when unset")
	}
	if r := request(http.MethodPut, "/api/settings", `{"agent_traffic_binding":false}`); r.Code != 200 {
		t.Fatalf("disable agent_traffic_binding failed: %d %s", r.Code, r.Body.String())
	}
	s.seedProjectMalariaTrafficBinding()
	if pg.GetBool(settingAgentTrafficBinding, true) {
		t.Fatal("seedProjectMalariaTrafficBinding must respect later user opt-out")
	}
}

func TestCompletenessWebSearchFloorAndAutoSync(t *testing.T) {
	s, _, _ := trafficEvidenceServer(t)
	pg := s.m.pg
	if err := pg.EnsurePipelineTables(); err != nil {
		t.Fatalf("EnsurePipelineTables: %v", err)
	}

	// 1. Default web_search seeding (global + agent-level) & user opt-out preservation.
	_, _ = pg.Exec(`DELETE FROM settings WHERE key IN ($1, 'project_malaria_web_search_v1')`, settingWebSearchOn)
	for _, k := range []string{"worker", "planner", "pentest", "auto", "mainagent"} {
		_ = pg.SetAgentWebSearch(k, false)
	}
	s.seedProjectMalariaWebSearch()
	if !pg.GetBool(settingWebSearchOn, false) {
		t.Fatal("expected project_malaria_web_search_v1 to enable web_search_enabled when unset")
	}
	for _, k := range []string{"worker", "planner", "pentest", "auto", "mainagent"} {
		a, err := pg.GetAgentByKey(k)
		if err != nil || a == nil || !a.WebSearch {
			t.Fatalf("agent %s WebSearch = %+v (err=%v), want true", k, a, err)
		}
	}
	_ = pg.SetAgentWebSearch("worker", false)
	s.seedProjectMalariaWebSearch()
	if a, _ := pg.GetAgentByKey("worker"); a == nil || a.WebSearch {
		t.Fatal("seedProjectMalariaWebSearch must respect user disabling agent web_search later")
	}

	// 2. Hard-floor intent synthesis & loop cap on untested assets.
	prevSS, _ := s.findMCPByName(scopeSentryMCPName)
	rec := &mockSSRecorder{}
	mockSS := startMockScopeSentryMCP(t, rec)
	defer mockSS.Close()
	ssRow := &db.MCPServer{Name: scopeSentryMCPName, Transport: "http", URL: mockSS.URL, Env: json.RawMessage(`{"X-API-Key":"test"}`), Enabled: true, TimeoutSeconds: 10}
	if prevSS != nil {
		ssRow.ID = prevSS.ID
		t.Cleanup(func() { _, _ = pg.SaveMCP(prevSS) })
	}
	if _, err := pg.SaveMCP(ssRow); err != nil {
		t.Fatalf("save mock scopesentry mcp: %v", err)
	}

	compID, err := pg.Companies().UpsertByName("ss-autosync-test")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = pg.Exec(`DELETE FROM companies WHERE id=$1`, compID) })

	taskObj, err := s.m.CreateTaskWithOptions("completeness-floor-task", "assess portal.nectec.or.th", db.TaskCreateOptions{
		CompanyIDs: []int64{compID},
	})
	if err != nil || taskObj == nil {
		t.Fatalf("CreateTaskWithOptions: %v", err)
	}
	taskID, _ := strconv.ParseInt(taskObj.ID, 10, 64)
	_ = s.m.ApplyTaskPause(taskObj.ID)
	t.Cleanup(func() {
		_, _ = s.m.DeleteTask(taskObj.ID, DeleteTaskOptions{DeleteFiles: true})
	})

	subID, err := pg.Assets().UpsertSubdomain(db.UpsertSubdomainReq{
		Domain: "portal.nectec.or.th",
		TaskID: taskID,
	})
	if err != nil {
		t.Fatal(err)
	}
	_ = pg.Assets().AddAutoScope(taskID, "subdomain", "portal.nectec.or.th", "", "")

	synthesized, err := s.engine.synthesizeFloorIntent(taskObj, taskID)
	if err != nil || !synthesized {
		t.Fatalf("synthesizeFloorIntent = (%v, %v), want (true, nil)", synthesized, err)
	}
	if active, err := taskObj.Store.HasActiveIntent(); err != nil || !active {
		t.Fatalf("HasActiveIntent after synthesizeFloorIntent = (%v, %v), want true", active, err)
	}
	// Mark attempts exhausted for subID -> loop cap stops infinite synthesis.
	for i := 0; i < 2; i++ {
		id, _ := taskObj.Store.AddIntent(map[string]any{"summary": "retry", "asset_ids": []int64{subID}}, 5, []int64{subID}, "engine_floor")
		_ = taskObj.Store.SetNodeState(id, "done")
	}
	synthesizedAgain, err := s.engine.synthesizeFloorIntent(taskObj, taskID)
	if err != nil || synthesizedAgain {
		t.Fatalf("expected synthesizeFloorIntent loop cap to return (false, nil), got (%v, %v)", synthesizedAgain, err)
	}

	// 3. Periodic ScopeSentry auto-sync discovers new subdomain/service/vuln into linked running task.
	conv, err := pg.CreateConversation("auto", "AutoSync Chat", nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = pg.DeleteConversation(conv.ID) })
	_ = pg.UpsertConversationLink(db.ConversationLink{
		ConversationID:       conv.ID,
		TaskID:               &taskID,
		CompanyID:            &compID,
		ScopeSentryProjectID: "proj-nectec-1",
		ScopeSentryTaskID:    "sstask-nectec-1",
		Target:               "https://www.nectec.or.th",
	})
	if links, lerr := pg.ListTaskScopeSentryLinks(); lerr != nil || len(links) == 0 {
		t.Fatalf("ListTaskScopeSentryLinks = (%+v, %v), want >= 1", links, lerr)
	}

	// Clear paused state so auto-sync recognizes the task as live (without starting goroutines).
	_ = s.m.SetTaskPaused(taskObj.ID, false)
	s.engine.paused.Delete(taskObj.ID)
	_ = s.m.SetTaskStatus(taskObj.ID, "running")
	var completed sync.Map
	s.syncActiveTasksScopeSentry(context.Background(), &completed)

	byType, err := pg.Assets().CountsByTypeForTask(taskID)
	if err != nil || byType["subdomain"] < 2 || byType["service"] < 1 {
		t.Fatalf("expected auto-synced ScopeSentry subdomains/services on task %d, got %+v (err=%v)", taskID, byType, err)
	}
	select {
	case <-taskObj.notify:
	default:
		t.Fatal("expected syncActiveTasksScopeSentry to notify task when new ASM discoveries landed")
	}
}
