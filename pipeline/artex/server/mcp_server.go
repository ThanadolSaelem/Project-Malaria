package server

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"

	"github.com/Autumn-27/artex/agent"
	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/traffic"
	actool "github.com/Autumn-27/norma/tool"
)

const (
	defaultARTEXMCPKey  = "ak_project_malaria_artex_mcp_key_2026"
	mcpWorkerOriginName = "deep-agent-ide"
)

type mcpToolEntry struct {
	name        string
	description string
	inputSchema map[string]any
	call        func(ctx context.Context, args json.RawMessage) (actool.Result, error)
}

func (s *Server) mcpAPIKey() string {
	if strings.EqualFold(strings.TrimSpace(os.Getenv("ARTEX_MCP_ENABLED")), "0") ||
		strings.EqualFold(strings.TrimSpace(os.Getenv("ARTEX_MCP_ENABLED")), "false") {
		return ""
	}
	if v := strings.TrimSpace(os.Getenv("ARTEX_MCP_KEY")); v != "" {
		return v
	}
	return defaultARTEXMCPKey
}

// requireMCPAuth authenticates Streamable HTTP MCP requests from Deep Agent IDE
// (/ai) using X-API-Key or Authorization: Bearer <key>.
func (s *Server) requireMCPAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		expected := s.mcpAPIKey()
		if expected == "" {
			writeErr(w, http.StatusServiceUnavailable, "ARTEX MCP endpoint is disabled")
			return
		}
		provided := strings.TrimSpace(r.Header.Get("X-API-Key"))
		if provided == "" {
			if auth := strings.TrimSpace(r.Header.Get("Authorization")); strings.HasPrefix(auth, "Bearer ") {
				provided = strings.TrimSpace(strings.TrimPrefix(auth, "Bearer "))
			}
		}
		if len(provided) != len(expected) || subtle.ConstantTimeCompare([]byte(provided), []byte(expected)) != 1 {
			writeErr(w, http.StatusUnauthorized, "invalid ARTEX MCP API key")
			return
		}
		next.ServeHTTP(w, r)
	})
}

type mcpRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

func writeMCPRPCResult(w http.ResponseWriter, id json.RawMessage, result any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"jsonrpc": "2.0",
		"id":      id,
		"result":  result,
	})
}

func writeMCPRPCError(w http.ResponseWriter, status int, id json.RawMessage, code int, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	if status != http.StatusOK {
		w.WriteHeader(status)
	}
	idVal := any(nil)
	if len(id) > 0 && string(id) != "null" {
		idVal = id
	}
	_ = json.NewEncoder(w).Encode(map[string]any{
		"jsonrpc": "2.0",
		"id":      idVal,
		"error":   map[string]any{"code": code, "message": msg},
	})
}

func negotiateMCPProtocol(clientVersion string) string {
	switch strings.TrimSpace(clientVersion) {
	case "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05":
		return strings.TrimSpace(clientVersion)
	default:
		return "2025-03-26"
	}
}

func cloneSchemaMap(src any) map[string]any {
	raw, err := json.Marshal(src)
	if err != nil {
		return map[string]any{"type": "object", "properties": map[string]any{}}
	}
	var out map[string]any
	if json.Unmarshal(raw, &out) != nil || out == nil {
		return map[string]any{"type": "object", "properties": map[string]any{}}
	}
	if _, ok := out["properties"].(map[string]any); !ok {
		out["properties"] = map[string]any{}
	}
	return out
}

func withOptionalTaskIDSchema(orig any) map[string]any {
	out := cloneSchemaMap(orig)
	props := out["properties"].(map[string]any)
	if _, exists := props["task_id"]; !exists {
		props["task_id"] = map[string]any{
			"type":        "string",
			"description": "optional ARTEX task id (defaults to active shared task_id from get_active_context when omitted)",
		}
	}
	return out
}

func stripTaskIDField(in json.RawMessage) json.RawMessage {
	if len(in) == 0 {
		return json.RawMessage(`{}`)
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(in, &m); err != nil || m == nil {
		return in
	}
	delete(m, "task_id")
	b, err := json.Marshal(m)
	if err != nil {
		return in
	}
	return b
}

// mcpResolveTaskID reads explicit task_id from arguments or falls back to the active
// shared task_id persisted in settings. explicitProvided reports whether task_id was
// supplied explicitly by the caller (so nonexistent explicit IDs error clearly).
func (s *Server) mcpResolveTaskID(in json.RawMessage) (taskID int64, explicit bool, err error) {
	if len(in) > 0 {
		var head struct {
			TaskID json.RawMessage `json:"task_id"`
		}
		if json.Unmarshal(in, &head) == nil && len(head.TaskID) > 0 && string(head.TaskID) != "null" {
			var asStr string
			if json.Unmarshal(head.TaskID, &asStr) == nil {
				if trimmed := strings.TrimSpace(asStr); trimmed != "" {
					id, perr := strconv.ParseInt(trimmed, 10, 64)
					if perr != nil || id <= 0 {
						return 0, true, fmt.Errorf("invalid task_id %q", trimmed)
					}
					return id, true, nil
				}
			} else if id := parseProfileID(head.TaskID); id > 0 {
				return id, true, nil
			}
		}
	}
	shared := s.loadSharedContext()
	if shared.TaskID > 0 {
		if _, ok := s.m.Task(strconv.FormatInt(shared.TaskID, 10)); ok {
			return shared.TaskID, false, nil
		}
	}
	return 0, false, nil
}

func (s *Server) mcpTaskToolSet(taskID int64) (*agent.ToolSet, *Task, error) {
	var t *Task
	var ts *db.ExplorationStore
	if taskID > 0 {
		resolved, ok := s.m.Task(strconv.FormatInt(taskID, 10))
		if !ok || resolved == nil {
			return nil, nil, fmt.Errorf("task #%d not found", taskID)
		}
		t = resolved
		ts = resolved.Store
	}
	tsx := agent.NewToolSet(ts, mcpWorkerOriginName)
	if s.m.pg != nil {
		tsx.SetDB(s.m.pg)
	}
	if s.m.Assets() != nil {
		tsx.SetAssetStore(s.m.Assets(), s.m.Assets().Companies())
	}
	if s.m.pg != nil {
		tsx.SetFindingRecorder(s.evidenceStore())
	}
	if taskID > 0 {
		tsx.SetTaskID(taskID)
	} else {
		tsx.SetOnStandaloneFinding(s.notifyReporterForStandaloneFinding)
	}
	if t != nil {
		tsx.SetCoverageEnabled(t.CoverageEnabled)
		tsx.SetNotify(t.Notify)
		tsx.SetNotifyGoal(t.NotifyGoal)
		tsx.SetNotifyHint(t.NotifyHint)
		tsx.SetNotifyFinding(func(int64, string) { t.Notify() })
	}
	return tsx, t, nil
}

func (s *Server) mcpToolByName(tsx *agent.ToolSet, name string) (actool.CoreTool, bool) {
	for _, tool := range tsx.AllDomainTools() {
		if tool.Name() == name {
			return tool, true
		}
	}
	return nil, false
}

func (s *Server) mcpCallDomainTool(ctx context.Context, in json.RawMessage, requireTask bool, toolName string) (actool.Result, error) {
	taskID, _, err := s.mcpResolveTaskID(in)
	if err != nil {
		return actool.Errorf(err.Error()), nil
	}
	if requireTask && taskID <= 0 {
		return actool.Errorf("no active ARTEX task selected; pass task_id or call start_target_assessment / set_active_context first"), nil
	}
	tsx, _, err := s.mcpTaskToolSet(taskID)
	if err != nil {
		return actool.Errorf(err.Error()), nil
	}
	coreTool, ok := s.mcpToolByName(tsx, toolName)
	if !ok {
		return actool.Errorf("domain tool unavailable: " + toolName), nil
	}
	return coreTool.Call(ctx, stripTaskIDField(in), nil)
}

func (s *Server) mcpTriggerReporterFromReportOutput(taskID int64, rawIn json.RawMessage, res actool.Result) {
	if res.IsError || s == nil || s.m == nil || s.m.pg == nil {
		return
	}
	lines := strings.SplitN(res.Flatten(), "\n", 2)
	if len(lines) < 2 {
		return
	}
	var rec db.RecordedFinding
	if err := json.Unmarshal([]byte(lines[1]), &rec); err != nil || rec.FindingID <= 0 {
		return
	}
	var a struct {
		VulnClass string `json:"vulnclass"`
		Name      string `json:"name"`
		Severity  string `json:"severity"`
		Summary   string `json:"summary"`
		Evidence  string `json:"evidence"`
	}
	_ = json.Unmarshal(rawIn, &a)
	s.notifyReporterForStandaloneFinding(taskID, &rec, db.RecordFindingInput{
		TaskID:    taskID,
		VulnClass: a.VulnClass,
		Name:      a.Name,
		Severity:  a.Severity,
		Summary:   a.Summary,
		Evidence:  a.Evidence,
		Worker:    mcpWorkerOriginName,
	})
}

func (s *Server) mcpToolCatalog() []mcpToolEntry {
	var serverTS *agent.ToolSet
	if s.m != nil {
		serverTS = agent.NewToolSet(nil, mcpWorkerOriginName)
		if s.m.pg != nil {
			serverTS.SetDB(s.m.pg)
		}
		if s.m.Assets() != nil {
			serverTS.SetAssetStore(s.m.Assets(), s.m.Assets().Companies())
		}
	}

	domainSchema := func(name string, withTask bool) map[string]any {
		if serverTS != nil {
			if t, ok := s.mcpToolByName(serverTS, name); ok {
				if withTask {
					return withOptionalTaskIDSchema(t.InputSchema())
				}
				return cloneSchemaMap(t.InputSchema())
			}
		}
		return map[string]any{"type": "object", "properties": map[string]any{}}
	}
	domainDesc := func(name, fallback string) string {
		if serverTS != nil {
			if t, ok := s.mcpToolByName(serverTS, name); ok {
				return t.Description()
			}
		}
		return fallback
	}

	entries := []mcpToolEntry{
		{
			name:        "get_active_context",
			description: "Get the currently shared ARTEX Task context (task_id, conversation_id, target, asset/finding counts, recent tasks, and recording proxy URL). Call this first in Deep Agent IDE to align with what the user is working on in Graph Chat or Tasks.",
			inputSchema: objSchema(map[string]any{}),
			call: func(context.Context, json.RawMessage) (actool.Result, error) {
				return jsonResult(s.buildSharedContextResponse())
			},
		},
		{
			name:        "get_shared_briefing",
			description: "Get a complete continuity briefing for the active shared ARTEX Task & Graph Chat conversation: task metadata, goals, confirmed findings, key facts, scoped assets, intents, recent conversation turns from /chat & Task Chat, and ready-to-use Markdown context.",
			inputSchema: objSchema(map[string]any{
				"task_id":         map[string]any{"type": "integer", "description": "optional ARTEX task id (defaults to active shared task)"},
				"conversation_id": map[string]any{"type": "integer", "description": "optional /chat conversation id (defaults to linked/active conversation)"},
				"max_turns":       map[string]any{"type": "integer", "description": "max recent conversation turns per channel (default 10)"},
			}),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					TaskID         json.RawMessage `json:"task_id"`
					ConversationID json.RawMessage `json:"conversation_id"`
					MaxTurns       int             `json:"max_turns"`
				}
				_ = json.Unmarshal(in, &a)
				return jsonResult(s.buildSharedBriefing(parseProfileID(a.TaskID), parseProfileID(a.ConversationID), a.MaxTurns))
			},
		},
		{
			name:        "get_chat_history",
			description: "Read chronological conversation messages from both Pentest Graph Chat (/chat) and Task Detail Chat for the active shared ARTEX task/conversation so follow-up questions in Deep Agent IDE continue seamlessly.",
			inputSchema: objSchema(map[string]any{
				"task_id":         map[string]any{"type": "integer", "description": "optional ARTEX task id (defaults to active shared task)"},
				"conversation_id": map[string]any{"type": "integer", "description": "optional /chat conversation id (defaults to active/linked conversation)"},
				"limit":           map[string]any{"type": "integer", "description": "max turns per channel (default 20, max 50)"},
			}),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					TaskID         json.RawMessage `json:"task_id"`
					ConversationID json.RawMessage `json:"conversation_id"`
					Limit          int             `json:"limit"`
				}
				_ = json.Unmarshal(in, &a)
				tid := parseProfileID(a.TaskID)
				cid := parseProfileID(a.ConversationID)
				if tid <= 0 && cid <= 0 {
					active := s.buildSharedContextResponse()
					tid = active.TaskID
					cid = active.ConversationID
				}
				if a.Limit <= 0 {
					a.Limit = 20
				}
				turns := s.collectSharedChatHistory(tid, cid, a.Limit)
				return jsonResult(map[string]any{
					"task_id":         tid,
					"conversation_id": cid,
					"count":           len(turns),
					"turns":           turns,
				})
			},
		},
		{
			name:        "set_active_context",
			description: "Switch the shared active ARTEX task_id (and optional conversation_id/target) so UI switchers and subsequent Deep Agent & Graph Chat actions share this exact task.",
			inputSchema: objSchema(map[string]any{
				"task_id":         map[string]any{"type": "integer", "description": "ARTEX task id (0 clears selection)"},
				"conversation_id": map[string]any{"type": "integer", "description": "optional linked /chat conversation id"},
				"target":          strParam("optional target URL/domain"),
			}, "task_id"),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					TaskID         json.RawMessage `json:"task_id"`
					ConversationID json.RawMessage `json:"conversation_id"`
					Target         string          `json:"target"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				tid := parseProfileID(a.TaskID)
				if tid > 0 {
					if _, ok := s.m.Task(strconv.FormatInt(tid, 10)); !ok {
						return actool.Errorf(fmt.Sprintf("task #%d not found", tid)), nil
					}
				}
				cid := parseProfileID(a.ConversationID)
				if tid > 0 && cid <= 0 {
					cid = s.resolveConversationForTask(tid)
				}
				target := strings.TrimSpace(a.Target)
				if tid > 0 && target == "" {
					_, _, target, _, _ = s.taskPrimaryMetadata(tid)
				}
				if err := s.saveSharedContext(sharedWorkspaceContext{
					TaskID:         tid,
					ConversationID: cid,
					Target:         target,
					Source:         mcpWorkerOriginName,
				}); err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(s.buildSharedContextResponse())
			},
		},
		{
			name:        "list_tasks",
			description: "List all ARTEX tasks with id, description, goal, status, linked conversation_id, asset counts, and finding counts.",
			inputSchema: objSchema(map[string]any{}),
			call: func(context.Context, json.RawMessage) (actool.Result, error) {
				tasks := s.m.List()
				out := make([]sharedTaskSummary, 0, len(tasks))
				for i := len(tasks) - 1; i >= 0; i-- {
					out = append(out, s.summarizeSharedTask(tasks[i]))
				}
				return jsonResult(map[string]any{"count": len(out), "tasks": out})
			},
		},
		{
			name:        "list_companies",
			description: domainDesc("list_companies", "List companies and their registered scopes & asset counts."),
			inputSchema: domainSchema("list_companies", false),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, false, "list_companies")
			},
		},
		{
			name:        "start_target_assessment",
			description: "Onboard or attach a target to the unified ARTEX pipeline: creates/reuses Company & Scope, Assets, ScopeSentry ASM scan, ARTEX Task + Exploration Graph, linked /chat Conversation, and sets the active shared task_id. By default attaches to an existing non-terminal task matching the same target unless force_new_task=true, and defaults start_autonomous_workers=false so Deep Agent IDE drives without colliding with local LLM workers (set true to also run ARTEX background workers immediately).",
			inputSchema: objSchema(map[string]any{
				"target":                   strParam("single target URL, domain, IP, or CIDR"),
				"targets":                  map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "optional list of targets"},
				"company":                  strParam("optional organization/company name"),
				"company_id":               map[string]any{"type": "integer", "description": "optional existing company id"},
				"scope":                    strParam("optional extra scope rules"),
				"description":              strParam("optional task title/description"),
				"goal":                     strParam("optional assessment objective"),
				"launch_scopesentry":       map[string]any{"type": "boolean", "description": "launch ScopeSentry ASM project & scan (default true)"},
				"launch_artex_task":        map[string]any{"type": "boolean", "description": "create/attach ARTEX task & exploration graph (default true)"},
				"start_autonomous_workers": map[string]any{"type": "boolean", "description": "immediately run ARTEX planner/workers in parallel (default false when driven by Deep Agent IDE; resume anytime later via control_task or UI)"},
				"force_new_task":           map[string]any{"type": "boolean", "description": "create a new task even if an active non-terminal task for the same target already exists (default false)"},
			}),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					Target                 string          `json:"target"`
					Targets                []string        `json:"targets"`
					Company                string          `json:"company"`
					CompanyID              json.RawMessage `json:"company_id"`
					Scope                  string          `json:"scope"`
					Description            string          `json:"description"`
					Goal                   string          `json:"goal"`
					LaunchScopeSentry      *bool           `json:"launch_scopesentry"`
					LaunchArtexTask        *bool           `json:"launch_artex_task"`
					StartAutonomousWorkers *bool           `json:"start_autonomous_workers"`
					ForceNewTask           bool            `json:"force_new_task"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				startWorkers := a.StartAutonomousWorkers != nil && *a.StartAutonomousWorkers
				res, err := s.runTargetAssessment(ctx, targetAssessmentParams{
					Target:             a.Target,
					Targets:            a.Targets,
					Company:            a.Company,
					CompanyID:          parseProfileID(a.CompanyID),
					Scope:              a.Scope,
					Description:        a.Description,
					Goal:               a.Goal,
					LaunchScopeSentry:  a.LaunchScopeSentry == nil || *a.LaunchScopeSentry,
					LaunchArtexTask:    a.LaunchArtexTask == nil || *a.LaunchArtexTask,
					PauseArtexTask:     !startWorkers,
					SeedFirstIntent:    startWorkers,
					AttachExisting:     !a.ForceNewTask,
					EnsureConversation: true,
					ConversationAgent:  "pentest",
				})
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(res)
			},
		},
		{
			name:        "control_task",
			description: "Pause or resume ARTEX's autonomous exploration workers for a task (use resume to hand over exploration to ARTEX autonomous planner/workers, or pause before taking manual Deep Agent control).",
			inputSchema: objSchema(map[string]any{
				"task_id": map[string]any{"type": "string", "description": "ARTEX task id (defaults to active shared task)"},
				"action":  map[string]any{"type": "string", "enum": []string{"pause", "resume"}, "description": "pause | resume"},
			}, "action"),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					TaskID json.RawMessage `json:"task_id"`
					Action string          `json:"action"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				if tid <= 0 {
					return actool.Errorf("task_id is required"), nil
				}
				t, ok := s.m.Task(strconv.FormatInt(tid, 10))
				if !ok || t == nil {
					return actool.Errorf(fmt.Sprintf("task #%d not found", tid)), nil
				}
				res, err := s.applyTaskControl(t, strings.ToLower(strings.TrimSpace(a.Action)))
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(res)
			},
		},
		{
			name:        "get_task_graph",
			description: "Read the Exploration Graph overview of a task (goals, intents, findings, coverage %, tested/untested asset counts, frontier). Defaults to active shared task_id.",
			inputSchema: objSchema(map[string]any{
				"task_id": strParam("optional ARTEX task id (defaults to active shared task)"),
			}),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "graph_overview")
			},
		},
		{
			name:        "set_goals",
			description: domainDesc("set_goals", "Add verifiable exploration goals to the active ARTEX Pentest Mission so they appear in Pentest Missions and the Exploration Graph."),
			inputSchema: domainSchema("set_goals", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "set_goals")
			},
		},
		{
			name:        "list_goals",
			description: domainDesc("list_goals", "List the active ARTEX task's goal nodes and their states (open/met)."),
			inputSchema: domainSchema("list_goals", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "list_goals")
			},
		},
		{
			name:        "prove_goal",
			description: domainDesc("prove_goal", "Link an observed fact or confirmed finding node to a goal node and mark the goal met."),
			inputSchema: domainSchema("prove_goal", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "prove_goal")
			},
		},
		{
			name:        "set_constraints",
			description: domainDesc("set_constraints", "Add allow/deny operational constraints to the active ARTEX task to bound exploration."),
			inputSchema: domainSchema("set_constraints", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "set_constraints")
			},
		},
		{
			name:        "add_intent",
			description: domainDesc("add_intent", "Create one or more exploration intent nodes in the active ARTEX task's Exploration Graph (returns intent node id(s) so subsequent record_fact/report_finding calls can link to intent_id)."),
			inputSchema: domainSchema("add_intent", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "add_intent")
			},
		},
		{
			name:        "update_intent_state",
			description: "Update the execution state of an exploration intent node (open|running|done|stopped) when Deep Agent IDE executes an intent directly while ARTEX autonomous workers are paused.",
			inputSchema: withOptionalTaskIDSchema(objSchema(map[string]any{
				"intent_id": map[string]any{"type": "integer", "description": "intent node id returned by add_intent"},
				"state":     map[string]any{"type": "string", "enum": []string{"open", "running", "done", "stopped"}, "description": "new intent state"},
			}, "intent_id", "state")),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				if tid <= 0 {
					return actool.Errorf("no active ARTEX task selected; pass task_id or call start_target_assessment / set_active_context first"), nil
				}
				var a struct {
					IntentID json.RawMessage `json:"intent_id"`
					State    string          `json:"state"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				intentID := parseProfileID(a.IntentID)
				if intentID <= 0 {
					return actool.Errorf("intent_id is required"), nil
				}
				state := strings.ToLower(strings.TrimSpace(a.State))
				switch state {
				case "open", "running", "done", "stopped":
				default:
					return actool.Errorf("state must be one of: open, running, done, stopped"), nil
				}
				t, ok := s.m.Task(strconv.FormatInt(tid, 10))
				if !ok || t == nil || t.Store == nil {
					return actool.Errorf(fmt.Sprintf("task #%d not found", tid)), nil
				}
				node, err := t.Store.GetNode(intentID)
				if err != nil || node == nil || node.Kind != db.KindIntent {
					return actool.Errorf(fmt.Sprintf("intent node #%d not found in task #%d", intentID, tid)), nil
				}
				if err := t.Store.SetNodeState(intentID, state); err != nil {
					return actool.Errorf("failed to update intent state: " + err.Error()), nil
				}
				return jsonResult(map[string]any{
					"ok":        true,
					"task_id":   tid,
					"intent_id": intentID,
					"state":     state,
				})
			},
		},
		{
			name:        "list_assets",
			description: "Query ARTEX Target Assets (root domains, subdomains, IPs, ports/services, HTTP services, endpoints, apps) scoped to task_id (defaults to active shared task; supports optional DSL filter or empty DSL inside a task).",
			inputSchema: withOptionalTaskIDSchema(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"dsl":    strParam("optional DSL query (e.g. domain=example or status_code>=400; may be omitted when task_id is active)"),
					"type":   strParam("optional asset type filter: root_domain|ip|subdomain|app|service|endpoint"),
					"id":     map[string]any{"type": "integer", "description": "optional single asset id"},
					"ids":    map[string]any{"type": "array", "items": map[string]any{"type": "integer"}},
					"limit":  map[string]any{"type": "integer", "description": "max rows (default 25)"},
					"offset": map[string]any{"type": "integer", "description": "pagination offset"},
				},
			}),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				as := s.assetStore()
				if as == nil {
					return actool.Errorf("AssetStore is not initialized"), nil
				}
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				var a struct {
					DSL    string  `json:"dsl"`
					Type   string  `json:"type"`
					ID     int64   `json:"id"`
					IDs    []int64 `json:"ids"`
					Limit  int     `json:"limit"`
					Offset int     `json:"offset"`
				}
				_ = json.Unmarshal(in, &a)
				if a.Limit <= 0 {
					a.Limit = 25
				}
				var assets []*db.Asset
				switch {
				case a.ID > 0:
					assets, err = as.GetByIDsInScope(tid, []int64{a.ID})
				case len(a.IDs) > 0:
					assets, err = as.GetByIDsInScope(tid, a.IDs)
				case tid > 0 || strings.TrimSpace(a.DSL) != "":
					assets, err = as.QueryDSLInScope(a.DSL, a.Type, tid, a.Limit, a.Offset)
				default:
					return actool.Errorf("provide task_id (or active context) or a non-empty dsl filter"), nil
				}
				if err != nil {
					return actool.Errorf("asset query failed: " + err.Error()), nil
				}
				return jsonResult(map[string]any{"task_id": tid, "count": len(assets), "assets": assets})
			},
		},
		{
			name:        "list_untested_assets",
			description: domainDesc("list_untested_assets", "List untested assets within a task's scope."),
			inputSchema: domainSchema("list_untested_assets", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "list_untested_assets")
			},
		},
		{
			name:        "insert_assets",
			description: domainDesc("insert_assets", "Register newly discovered subdomains, IPs, HTTP/TCP services, endpoints, and technologies into ARTEX Assets & bind to task_id."),
			inputSchema: domainSchema("insert_assets", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, false, "insert_assets")
			},
		},
		{
			name:        "list_facts",
			description: domainDesc("list_facts", "Read recorded exploration facts/observations for a task."),
			inputSchema: domainSchema("list_facts", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "list_facts")
			},
		},
		{
			name:        "record_fact",
			description: domainDesc("record_fact", "Record verified exploration facts, code audit observations, or negative conclusions into the shared Task Exploration Graph (origin=deep-agent-ide)."),
			inputSchema: domainSchema("record_fact", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "record_fact")
			},
		},
		{
			name:        "add_task_hint",
			description: "Inject strategic hint(s) into a task's Exploration Graph so ARTEX Planner and Graph Chat can act on Deep Agent discoveries (set wake_planner=true to notify running planner immediately).",
			inputSchema: withOptionalTaskIDSchema(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"hints":        map[string]any{"type": "array", "items": objSchema(map[string]any{"text": strParam("hint content"), "asset_ids": map[string]any{"type": "array", "items": map[string]any{"type": "integer"}}})},
					"text":         strParam("single hint text"),
					"asset_ids":    map[string]any{"type": "array", "items": map[string]any{"type": "integer"}},
					"wake_planner": map[string]any{"type": "boolean", "description": "wake the task engine if running (default false)"},
				},
			}),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				res, err := s.mcpCallDomainTool(ctx, in, true, "add_hint")
				if err != nil || res.IsError {
					return res, err
				}
				var opt struct {
					WakePlanner bool `json:"wake_planner"`
				}
				if json.Unmarshal(in, &opt) == nil && opt.WakePlanner {
					if tid, _, rerr := s.mcpResolveTaskID(in); rerr == nil && tid > 0 {
						if t, ok := s.m.Task(strconv.FormatInt(tid, 10)); ok && t != nil {
							t.Notify()
						}
					}
				}
				return res, nil
			},
		},
		{
			name:        "list_task_findings",
			description: domainDesc("list_findings", "Read confirmed vulnerabilities recorded in a task."),
			inputSchema: domainSchema("list_findings", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "list_findings")
			},
		},
		{
			name:        "get_task_node_detail",
			description: domainDesc("node_detail", "Read full detail/evidence/PoC of an exploration graph node (fact/finding/intent/goal) by node id."),
			inputSchema: domainSchema("node_detail", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "node_detail")
			},
		},
		{
			name:        "report_finding",
			description: domainDesc("report_finding", "Record a confirmed vulnerability into both the unified Findings table (/function/findings) and the active Task Exploration Graph, automatically triggering verification/reporting."),
			inputSchema: domainSchema("report_finding", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				res, callErr := s.mcpCallDomainTool(ctx, in, false, "report_finding")
				if callErr == nil && !res.IsError {
					// When ts != nil (inside a task), agent/tools.go does not call onStandaloneFinding;
					// trigger reporter explicitly because MCP calls do not emit worker tool_result rows.
					if tid > 0 {
						s.mcpTriggerReporterFromReportOutput(tid, in, res)
					}
				}
				return res, callErr
			},
		},
		{
			name:        "update_finding_report",
			description: s.toolUpdateFindingReport().Description(),
			inputSchema: cloneSchemaMap(s.toolUpdateFindingReport().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolUpdateFindingReport().Call(ctx, in, nil)
			},
		},
		{
			name:        "get_finding_traffic",
			description: s.toolGetFindingTraffic().Description(),
			inputSchema: cloneSchemaMap(s.toolGetFindingTraffic().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolGetFindingTraffic().Call(ctx, in, nil)
			},
		},
		{
			name:        "bind_finding_traffic",
			description: s.toolBindFindingTraffic().Description(),
			inputSchema: cloneSchemaMap(s.toolBindFindingTraffic().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolBindFindingTraffic().Call(ctx, in, nil)
			},
		},
		{
			name:        "list_task_worker_traces",
			description: domainDesc("list_worker_traces", "List executed intents and step counts from ARTEX workers in a task."),
			inputSchema: domainSchema("list_worker_traces", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "list_worker_traces")
			},
		},
		{
			name:        "get_task_worker_trace",
			description: domainDesc("get_worker_trace", "Inspect detailed execution trace steps of one ARTEX worker intent."),
			inputSchema: domainSchema("get_worker_trace", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "get_worker_trace")
			},
		},
		{
			name:        "search_task_worker_traces",
			description: domainDesc("search_all_worker_traces", "Search ARTEX worker execution traces in a task by keyword."),
			inputSchema: domainSchema("search_all_worker_traces", true),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.mcpCallDomainTool(ctx, in, true, "search_all_worker_traces")
			},
		},
		{
			name:        "sync_scopesentry_assets",
			description: s.toolSyncScopeSentryAssets().Description(),
			inputSchema: cloneSchemaMap(s.toolSyncScopeSentryAssets().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				var m map[string]any
				_ = json.Unmarshal(in, &m)
				if m == nil {
					m = map[string]any{}
				}
				if _, hasTID := m["task_id"]; !hasTID {
					if tid, _, err := s.mcpResolveTaskID(in); err == nil && tid > 0 {
						m["task_id"] = strconv.FormatInt(tid, 10)
					}
				}
				b, _ := json.Marshal(m)
				return s.toolSyncScopeSentryAssets().Call(ctx, b, nil)
			},
		},
		{
			name:        "ingest_traffic",
			description: "Store an HTTP request/response exchange executed inside Deep Agent IDE into ARTEX's Traffic Store and full-text index. Returns traffic_id so you can attach it to report_finding(..., traffic_refs=[{traffic_id, role:'proof'}]) for PoE verification.",
			inputSchema: objSchema(map[string]any{
				"method":           strParam("HTTP method (GET, POST, PUT, DELETE, etc.)"),
				"url":              strParam("Full request URL including scheme and host"),
				"status":           map[string]any{"type": "integer", "description": "HTTP response status code (default 200)"},
				"request_headers":  map[string]any{"type": "object", "description": "Request headers map"},
				"request_body":     strParam("Raw request body"),
				"response_headers": map[string]any{"type": "object", "description": "Response headers map"},
				"response_body":    strParam("Raw response body"),
			}, "method", "url"),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				tr := s.m.Traffic()
				if tr == nil {
					return actool.Errorf("traffic store unavailable"), nil
				}
				var a struct {
					Method          string            `json:"method"`
					URL             string            `json:"url"`
					Status          int               `json:"status"`
					RequestHeaders  map[string]string `json:"request_headers"`
					RequestBody     string            `json:"request_body"`
					ResponseHeaders map[string]string `json:"response_headers"`
					ResponseBody    string            `json:"response_body"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				id, err := tr.RecordExternalWithID(traffic.ExternalExchange{
					Method:          a.Method,
					URL:             a.URL,
					Status:          a.Status,
					RequestHeaders:  a.RequestHeaders,
					RequestBody:     truncateBody(a.RequestBody),
					ResponseHeaders: a.ResponseHeaders,
					ResponseBody:    truncateBody(a.ResponseBody),
				})
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(map[string]any{"traffic_id": id, "url": a.URL, "status": a.Status})
			},
		},
		{
			name:        "post_chat_note",
			description: "Post a concise handoff summary from Deep Agent IDE into the /chat conversation linked to task_id (auto-creates a linked Graph Chat conversation if none exists yet). Keeps the user and Graph Chat LLM seamlessly synchronized when switching modes.",
			inputSchema: withOptionalTaskIDSchema(objSchema(map[string]any{
				"conversation_id": map[string]any{"type": "integer", "description": "optional explicit /chat conversation id"},
				"summary":         strParam("short title/one-line summary for the chat timeline"),
				"message":         strParam("detailed Markdown handoff summary (tested paths, artifacts, findings, recommended next checks)"),
			}, "message")),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				if s.m.pg == nil {
					return actool.Errorf("database unavailable"), nil
				}
				var a struct {
					ConversationID json.RawMessage `json:"conversation_id"`
					Summary        string          `json:"summary"`
					Message        string          `json:"message"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				msg := strings.TrimSpace(a.Message)
				if msg == "" {
					return actool.Errorf("message cannot be empty"), nil
				}
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				cid := parseProfileID(a.ConversationID)
				if cid <= 0 && tid > 0 {
					cid, _, err = s.ensureLinkedConversation(tid, "", "", "", 0, "pentest")
					if err != nil {
						return actool.Errorf(err.Error()), nil
					}
				}
				if cid <= 0 {
					return actool.Errorf("task_id or conversation_id is required to post a chat handoff note"), nil
				}
				sum := strings.TrimSpace(a.Summary)
				if sum == "" {
					sum = firstLine(msg, 180)
				}
				if _, err := s.m.pg.AppendConvActivity(cid, db.Activity{
					Worker:  mcpWorkerOriginName,
					Kind:    "text",
					Summary: sum,
					Detail:  msg,
				}); err != nil {
					return actool.Errorf(err.Error()), nil
				}
				_ = s.m.pg.TouchConversation(cid)
				return jsonResult(map[string]any{"ok": true, "task_id": tid, "conversation_id": cid})
			},
		},
		{
			name:        "ensure_auto_pipeline",
			description: "Deterministically create or attach an ARTEX Mission Task + linked Graph Chat conversation from an operator prompt and optional shared /workspace folder path (zero-touch auto-pipeline).",
			inputSchema: objSchema(map[string]any{
				"prompt":          strParam("operator prompt describing the target URL/IP/domain or file/folder assessment"),
				"workspace_path":  strParam("optional shared /workspace/... directory path"),
				"conversation_id": map[string]any{"type": "integer", "description": "optional existing /chat conversation id"},
			}, "prompt"),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					Prompt         string          `json:"prompt"`
					WorkspacePath  string          `json:"workspace_path"`
					ConversationID json.RawMessage `json:"conversation_id"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf("invalid input: " + err.Error()), nil
				}
				cid := parseProfileID(a.ConversationID)
				res, err := s.ensureAutoPipeline(ctx, a.Prompt, a.WorkspacePath, cid, "pentest", nil, true)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				if res == nil {
					return jsonResult(map[string]any{"ok": false, "task_id": 0})
				}
				return jsonResult(res)
			},
		},
		{
			name:        "list_report_templates",
			description: s.toolListReportTemplates().Description(),
			inputSchema: cloneSchemaMap(s.toolListReportTemplates().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolListReportTemplates().Call(ctx, in, nil)
			},
		},
		{
			name:        "generate_task_report",
			description: s.toolGenerateTaskReport().Description(),
			inputSchema: cloneSchemaMap(s.toolGenerateTaskReport().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolGenerateTaskReport().Call(ctx, in, nil)
			},
		},
		{
			name:        "triage_finding",
			description: "Update AppScan-style finding lifecycle triage_status (new/open/in_progress/noise/fixed/reopened), VEX disposition (affected/not_affected/fixed/under_investigation), and FixGroup key. Marking a finding 'noise' suppresses that fingerprint on future scans.",
			inputSchema: objSchema(map[string]any{
				"finding_id":        map[string]any{"type": "integer", "description": "standalone finding record ID"},
				"triage_status":     strParam("new | open | in_progress | noise | fixed | reopened"),
				"triage_note":       strParam("optional reason or analyst note"),
				"vex_status":        strParam("optional VEX status: affected | not_affected | fixed | under_investigation"),
				"vex_justification": strParam("optional VEX justification explaining whether vulnerable code is actually reachable"),
				"fix_group_key":     strParam("optional custom root-cause FixGroup key"),
			}, "finding_id"),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					FindingID        json.RawMessage `json:"finding_id"`
					TriageStatus     string          `json:"triage_status"`
					TriageNote       string          `json:"triage_note"`
					VexStatus        string          `json:"vex_status"`
					VexJustification string          `json:"vex_justification"`
					FixGroupKey      string          `json:"fix_group_key"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf(err.Error()), nil
				}
				fid := parseProfileID(a.FindingID)
				if fid <= 0 {
					return actool.Errorf("finding_id is required"), nil
				}
				if err := s.m.pg.UpdateFindingTriage(fid, a.TriageStatus, a.TriageNote, a.VexStatus, a.VexJustification, a.FixGroupKey); err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(map[string]any{"ok": true, "finding_id": fid, "triage_status": a.TriageStatus, "vex_status": a.VexStatus})
			},
		},
		{
			name:        "correlate_task_findings",
			description: "Run AppScan-style cross-run fingerprint correlation for a task: suppresses recurring Noise fingerprints, detects Reopened regressions, marks absent baseline issues as Fixed, and returns enriched findings + FixGroup clusters.",
			inputSchema: withOptionalTaskIDSchema(objSchema(map[string]any{})),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				tid, _, _ := s.mcpResolveTaskID(in)
				corr, err := s.m.pg.CorrelateTaskFindings(tid)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				groups, _ := s.m.pg.BuildFixGroups(tid)
				findings, _ := s.m.pg.ListEnterpriseFindings(tid, true)
				return jsonResult(map[string]any{"ok": true, "correlation": corr, "fix_groups": groups, "findings": findings})
			},
		},
		{
			name:        "evaluate_quality_gate",
			description: "Run Control-Plane Quality Gate (Engine != Ready) on a task: verifies Auth health, WAF/429 rate-limit status, Asset coverage completeness, Evidence integrity, and Mission Goals, returning gate_status (ready / ready_incomplete / pending_support) and structured exit_code.",
			inputSchema: withOptionalTaskIDSchema(objSchema(map[string]any{})),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil || tid <= 0 {
					return actool.Errorf("valid task_id is required"), nil
				}
				gate, err := s.EvaluateTaskQualityGate(tid, "control_plane")
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(map[string]any{"ok": true, "gate": gate})
			},
		},
		{
			name:        "list_fix_groups",
			description: "Aggregate findings into Root-Cause FixGroups (FixLocation / OpenSourceLib / ApiEndpoint / SecurityControl) showing how many vulnerabilities each single remediation closes.",
			inputSchema: withOptionalTaskIDSchema(objSchema(map[string]any{})),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				tid, _, _ := s.mcpResolveTaskID(in)
				groups, err := s.m.pg.BuildFixGroups(tid)
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(map[string]any{"ok": true, "task_id": tid, "fix_groups": groups})
			},
		},
		{
			name:        "run_scan_operation",
			description: "Execute an AppScan-style ScanOperation on a task: full, explore_only (saves Reference Baseline), test_only (inherits baseline assets & skips recon), retest (re-verifies open findings only), or report_only.",
			inputSchema: withOptionalTaskIDSchema(objSchema(map[string]any{
				"operation":        strParam("full | explore_only | test_only | retest | report_only"),
				"baseline_task_id": map[string]any{"type": "integer", "description": "optional reference baseline task_id for test_only/retest"},
				"bundle_id":        map[string]any{"type": "integer", "description": "optional reusable ScanContextBundle id"},
			}, "operation")),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					Operation      string          `json:"operation"`
					BaselineTaskID json.RawMessage `json:"baseline_task_id"`
					BundleID       json.RawMessage `json:"bundle_id"`
				}
				if err := json.Unmarshal(in, &a); err != nil {
					return actool.Errorf(err.Error()), nil
				}
				tid, _, err := s.mcpResolveTaskID(in)
				if err != nil || tid <= 0 {
					return actool.Errorf("valid task_id is required"), nil
				}
				res, err := s.executeScanOperation(ctx, tid, a.Operation, parseProfileID(a.BaselineTaskID), parseProfileID(a.BundleID), "")
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(res)
			},
		},
		{
			name:        "list_scan_bundles",
			description: "List saved reusable Scan Context Bundles (Auth/Login/API Key profiles, OpenAPI/Postman specs, Test Policies, Exclude paths, and Rate Limits).",
			inputSchema: objSchema(map[string]any{}),
			call: func(_ context.Context, _ json.RawMessage) (actool.Result, error) {
				items, err := s.m.pg.ListScanBundles()
				if err != nil {
					return actool.Errorf(err.Error()), nil
				}
				return jsonResult(map[string]any{"ok": true, "bundles": items})
			},
		},
		{
			name:        "get_scan_bundle",
			description: "Read the full configuration (auth headers/cookies/login steps, OpenAPI/Postman paths, test policy, exclude paths) of a saved Scan Context Bundle.",
			inputSchema: objSchema(map[string]any{
				"id": map[string]any{"type": "integer", "description": "bundle id"},
			}, "id"),
			call: func(_ context.Context, in json.RawMessage) (actool.Result, error) {
				var a struct {
					ID json.RawMessage `json:"id"`
				}
				_ = json.Unmarshal(in, &a)
				bid := parseProfileID(a.ID)
				if bid <= 0 {
					bid = s.loadSharedContext().BundleID
				}
				b, err := s.m.pg.GetScanBundle(bid)
				if err != nil || b == nil {
					return actool.Errorf("scan bundle not found"), nil
				}
				return jsonResult(map[string]any{"ok": true, "bundle": b})
			},
		},
		{
			name:        "search_playbook_memory",
			description: s.toolSearchPlaybookMemory().Description(),
			inputSchema: cloneSchemaMap(s.toolSearchPlaybookMemory().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolSearchPlaybookMemory().Call(ctx, in, nil)
			},
		},
		{
			name:        "save_playbook_memory",
			description: s.toolSavePlaybookMemory().Description(),
			inputSchema: cloneSchemaMap(s.toolSavePlaybookMemory().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolSavePlaybookMemory().Call(ctx, in, nil)
			},
		},
		{
			name:        "sandbox_exec",
			description: s.toolSandboxExec().Description(),
			inputSchema: cloneSchemaMap(s.toolSandboxExec().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolSandboxExec().Call(ctx, in, nil)
			},
		},
		{
			name:        "sandbox_manage",
			description: s.toolSandboxManage().Description(),
			inputSchema: cloneSchemaMap(s.toolSandboxManage().InputSchema()),
			call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
				return s.toolSandboxManage().Call(ctx, in, nil)
			},
		},
	}

	if tr := s.m.Traffic(); tr != nil {
		for _, tt := range tr.Tools() {
			tTool := tt
			entries = append(entries, mcpToolEntry{
				name:        tTool.Name(),
				description: tTool.Description(),
				inputSchema: cloneSchemaMap(tTool.InputSchema()),
				call: func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
					return tTool.Call(ctx, in, nil)
				},
			})
		}
	}

	return entries
}

func (s *Server) handleMCPRPC(ctx context.Context, catalog map[string]mcpToolEntry, order []mcpToolEntry, req mcpRPCRequest) (result any, rpcErr map[string]any, isNotif bool) {
	hasID := len(req.ID) > 0 && string(req.ID) != "null"
	if strings.HasPrefix(req.Method, "notifications/") || (!hasID && req.Method == "initialized") {
		return nil, nil, true
	}
	if !hasID {
		return nil, nil, true
	}

	switch req.Method {
	case "initialize":
		var p struct {
			ProtocolVersion string `json:"protocolVersion"`
		}
		_ = json.Unmarshal(req.Params, &p)
		return map[string]any{
			"protocolVersion": negotiateMCPProtocol(p.ProtocolVersion),
			"capabilities": map[string]any{
				"tools": map[string]any{"listChanged": false},
			},
			"serverInfo": map[string]any{
				"name":    "artex",
				"version": BuildVersion,
			},
			"instructions": "Shared ARTEX pentest orchestration, assets, exploration graph, traffic, and findings store. Call get_active_context or start_target_assessment first, then manage mission progress via set_goals, set_constraints, add_intent, update_intent_state, record_fact, report_finding, prove_goal, and post_chat_note.",
		}, nil, false

	case "ping":
		return map[string]any{}, nil, false

	case "tools/list":
		tools := make([]map[string]any, 0, len(order))
		for _, t := range order {
			tools = append(tools, map[string]any{
				"name":        t.name,
				"description": t.description,
				"inputSchema": t.inputSchema,
			})
		}
		return map[string]any{"tools": tools}, nil, false

	case "tools/call":
		var call struct {
			Name      string          `json:"name"`
			Arguments json.RawMessage `json:"arguments"`
		}
		if err := json.Unmarshal(req.Params, &call); err != nil {
			return nil, map[string]any{"code": -32602, "message": "invalid params: " + err.Error()}, false
		}
		entry, ok := catalog[strings.TrimSpace(call.Name)]
		if !ok {
			return nil, map[string]any{"code": -32602, "message": "unknown tool: " + call.Name}, false
		}
		args := call.Arguments
		if len(args) == 0 || string(args) == "null" {
			args = json.RawMessage(`{}`)
		}
		res, err := entry.call(ctx, args)
		if err != nil {
			return map[string]any{
				"content": []map[string]any{{"type": "text", "text": err.Error()}},
				"isError": true,
			}, nil, false
		}
		return map[string]any{
			"content": []map[string]any{{"type": "text", "text": res.Flatten()}},
			"isError": res.IsError,
		}, nil, false

	default:
		return nil, map[string]any{"code": -32601, "message": "method not found: " + req.Method}, false
	}
}

func (s *Server) mcpHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			// POST-only stateless Streamable HTTP MCP per MCP transport spec.
			w.Header().Set("Allow", "POST, DELETE")
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		case http.MethodDelete:
			w.WriteHeader(http.StatusOK)
			return
		case http.MethodPost:
		default:
			w.Header().Set("Allow", "POST, DELETE")
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		order := s.mcpToolCatalog()
		catalog := make(map[string]mcpToolEntry, len(order))
		for _, t := range order {
			catalog[t.name] = t
		}

		r.Body = http.MaxBytesReader(w, r.Body, 4<<20)
		var raw json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			writeMCPRPCError(w, http.StatusBadRequest, nil, -32700, "parse error: "+err.Error())
			return
		}
		trimmed := strings.TrimSpace(string(raw))
		if strings.HasPrefix(trimmed, "[") {
			var batch []mcpRPCRequest
			if err := json.Unmarshal(raw, &batch); err != nil {
				writeMCPRPCError(w, http.StatusBadRequest, nil, -32600, "invalid JSON-RPC batch")
				return
			}
			var responses []map[string]any
			for _, req := range batch {
				res, rpcErr, isNotif := s.handleMCPRPC(r.Context(), catalog, order, req)
				if isNotif {
					continue
				}
				item := map[string]any{"jsonrpc": "2.0", "id": req.ID}
				if rpcErr != nil {
					item["error"] = rpcErr
				} else {
					item["result"] = res
				}
				responses = append(responses, item)
			}
			if len(responses) == 0 {
				w.WriteHeader(http.StatusAccepted)
				return
			}
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Header().Set("Cache-Control", "no-store")
			_ = json.NewEncoder(w).Encode(responses)
			return
		}

		var req mcpRPCRequest
		if err := json.Unmarshal(raw, &req); err != nil {
			writeMCPRPCError(w, http.StatusBadRequest, nil, -32600, "invalid JSON-RPC request")
			return
		}
		res, rpcErr, isNotif := s.handleMCPRPC(r.Context(), catalog, order, req)
		if isNotif {
			w.WriteHeader(http.StatusAccepted)
			return
		}
		if rpcErr != nil {
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.Header().Set("Cache-Control", "no-store")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      req.ID,
				"error":   rpcErr,
			})
			return
		}
		writeMCPRPCResult(w, req.ID, res)
	})
}
