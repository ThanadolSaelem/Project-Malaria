package server

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Autumn-27/artex/db"
)

const settingSharedWorkspaceContext = "shared_workspace_context_v1"

type sharedWorkspaceContext struct {
	TaskID         int64  `json:"task_id"`
	ConversationID int64  `json:"conversation_id,omitempty"`
	Target         string `json:"target,omitempty"`
	WorkspacePath  string `json:"workspace_path,omitempty"`
	BundleID       int64  `json:"bundle_id,omitempty"`
	ScanMode       string `json:"scan_mode,omitempty"`
	UpdatedAt      string `json:"updated_at,omitempty"`
	Source         string `json:"source,omitempty"`
}

type sharedTaskSummary struct {
	ID             int64  `json:"id"`
	Name           string `json:"name,omitempty"`
	Description    string `json:"description"`
	Goal           string `json:"goal,omitempty"`
	Status         string `json:"status"`
	CompanyName    string `json:"company_name,omitempty"`
	Target         string `json:"target,omitempty"`
	ConversationID int64  `json:"conversation_id,omitempty"`
	AssetCount     int    `json:"asset_count"`
	FindingCount   int    `json:"finding_count"`
	NodeCount      int    `json:"node_count"`
}

type sharedContextResponse struct {
	TaskID                int64               `json:"task_id"`
	ConversationID        int64               `json:"conversation_id,omitempty"`
	Target                string              `json:"target,omitempty"`
	WorkspacePath         string              `json:"workspace_path,omitempty"`
	BundleID              int64               `json:"bundle_id,omitempty"`
	ScanMode              string              `json:"scan_mode,omitempty"`
	Source                string              `json:"source,omitempty"`
	UpdatedAt             string              `json:"updated_at,omitempty"`
	TaskDescription       string              `json:"task_description,omitempty"`
	TaskGoal              string              `json:"task_goal,omitempty"`
	TaskStatus            string              `json:"task_status,omitempty"`
	CompanyName           string              `json:"company_name,omitempty"`
	AssetCount            int                 `json:"asset_count"`
	FindingCount          int                 `json:"finding_count"`
	NodeCount             int                 `json:"node_count"`
	TrafficCaptureEnabled bool                `json:"traffic_capture_enabled"`
	InternalProxyURL      string              `json:"internal_proxy_url,omitempty"`
	RecentTasks           []sharedTaskSummary `json:"recent_tasks"`
}

func (s *Server) loadSharedContext() sharedWorkspaceContext {
	var ctxState sharedWorkspaceContext
	if s == nil || s.m == nil || s.m.pg == nil {
		return ctxState
	}
	raw, ok, err := s.m.pg.GetSetting(settingSharedWorkspaceContext)
	if err != nil || !ok || strings.TrimSpace(raw) == "" {
		return ctxState
	}
	_ = json.Unmarshal([]byte(raw), &ctxState)
	return ctxState
}

func (s *Server) saveSharedContext(state sharedWorkspaceContext) error {
	if s == nil || s.m == nil || s.m.pg == nil {
		return nil
	}
	prev := s.loadSharedContext()
	state.Target = strings.TrimSpace(state.Target)
	state.WorkspacePath = strings.TrimSpace(state.WorkspacePath)
	if state.WorkspacePath == "" && prev.WorkspacePath != "" && (state.TaskID == 0 || state.TaskID == prev.TaskID || prev.TaskID == 0) {
		state.WorkspacePath = prev.WorkspacePath
	}
	if state.BundleID == 0 && prev.BundleID > 0 && state.Source != "bundle_clear" {
		state.BundleID = prev.BundleID
	}
	if state.ScanMode == "" && prev.ScanMode != "" {
		state.ScanMode = prev.ScanMode
	}
	state.Source = strings.TrimSpace(state.Source)
	state.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	raw, err := json.Marshal(state)
	if err != nil {
		return err
	}
	return s.m.pg.SetSetting(settingSharedWorkspaceContext, string(raw))
}

func (s *Server) resolveConversationForTask(taskID int64) int64 {
	if taskID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return 0
	}
	var cid int64
	err := s.m.pg.QueryRow(`
		SELECT l.conversation_id
		FROM conversation_links l
		JOIN conversations c ON c.id = l.conversation_id
		WHERE l.task_id = $1
		ORDER BY c.updated_at DESC, l.id DESC
		LIMIT 1`, taskID).Scan(&cid)
	if err != nil {
		return 0
	}
	return cid
}

func (s *Server) taskPrimaryMetadata(taskID int64) (companyID int64, companyName, target, ssProjectID, ssTaskID string) {
	if taskID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return 0, "", "", "", ""
	}
	_ = s.m.pg.QueryRow(`
		SELECT COALESCE(company_id, 0), target, scopesentry_project_id, scopesentry_task_id
		FROM conversation_links
		WHERE task_id = $1
		ORDER BY created_at DESC, id DESC
		LIMIT 1`, taskID).Scan(&companyID, &target, &ssProjectID, &ssTaskID)
	if companyID == 0 {
		_ = s.m.pg.QueryRow(`
			SELECT company_id FROM task_companies
			WHERE task_id = $1
			ORDER BY company_id ASC
			LIMIT 1`, taskID).Scan(&companyID)
	}
	if companyID > 0 && s.companyStore() != nil {
		if c, err := s.companyStore().GetCompany(companyID); err == nil && c != nil {
			companyName = c.Name
		}
	}
	return companyID, companyName, strings.TrimSpace(target), strings.TrimSpace(ssProjectID), strings.TrimSpace(ssTaskID)
}

func (s *Server) pickChatAgentKey(preferred string) string {
	pg := s.m.pg
	for _, key := range []string{strings.TrimSpace(preferred), "pentest", "auto"} {
		if key == "" {
			continue
		}
		if a, err := pg.GetAgentByKey(key); err == nil && a != nil {
			return key
		}
	}
	if cs, err := pg.ListAgents(); err == nil {
		for _, a := range cs {
			if a != nil && a.Role == "assistant" {
				return a.Key
			}
		}
	}
	return "pentest"
}

// ensureLinkedConversation returns an existing /chat conversation linked to taskID
// or creates a new conversation + conversation_links row so /ai, /chat, and /function/tasks
// share one continuous workspace record.
func (s *Server) ensureLinkedConversation(taskID int64, target, ssProjectID, ssTaskID string, companyID int64, preferredAgent string) (int64, bool, error) {
	if taskID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return 0, false, fmt.Errorf("task_id is required")
	}
	if existing := s.resolveConversationForTask(taskID); existing > 0 {
		// Ensure link metadata stays fresh if callers pass newly resolved fields.
		if target != "" || ssProjectID != "" || ssTaskID != "" || companyID > 0 {
			var cidPtr *int64
			if companyID > 0 {
				cid := companyID
				cidPtr = &cid
			}
			_ = s.m.pg.UpsertConversationLink(db.ConversationLink{
				ConversationID:       existing,
				TaskID:               &taskID,
				CompanyID:            cidPtr,
				ScopeSentryProjectID: ssProjectID,
				ScopeSentryTaskID:    ssTaskID,
				Target:               target,
			})
		}
		return existing, false, nil
	}

	tidStr := strconv.FormatInt(taskID, 10)
	t, ok := s.m.Task(tidStr)
	if !ok || t == nil {
		return 0, false, fmt.Errorf("task #%d not found", taskID)
	}
	if companyID == 0 || target == "" || ssProjectID == "" {
		dbCID, _, dbTarget, dbProj, dbSSTask := s.taskPrimaryMetadata(taskID)
		if companyID == 0 {
			companyID = dbCID
		}
		if target == "" {
			target = dbTarget
		}
		if ssProjectID == "" {
			ssProjectID = dbProj
		}
		if ssTaskID == "" {
			ssTaskID = dbSSTask
		}
	}

	label := strings.TrimSpace(target)
	if label == "" {
		label = strings.TrimSpace(t.Name)
	}
	if label == "" {
		label = strings.TrimSpace(t.Description)
	}
	title := fmt.Sprintf("Task #%d", taskID)
	if label != "" {
		if len(label) > 60 {
			label = label[:60] + "..."
		}
		title = fmt.Sprintf("Task #%d · %s", taskID, label)
	}

	agentKey := s.pickChatAgentKey(preferredAgent)
	var profilePtr *int64
	llmState := t.llmStateSnapshot()
	if llmState.ActiveID != nil && *llmState.ActiveID > 0 {
		id := *llmState.ActiveID
		profilePtr = &id
	}
	c, err := s.m.pg.CreateConversationGated(agentKey, title, profilePtr, false)
	if err != nil {
		return 0, false, err
	}
	var cidPtr *int64
	if companyID > 0 {
		cid := companyID
		cidPtr = &cid
	}
	if err := s.m.pg.UpsertConversationLink(db.ConversationLink{
		ConversationID:       c.ID,
		TaskID:               &taskID,
		CompanyID:            cidPtr,
		ScopeSentryProjectID: ssProjectID,
		ScopeSentryTaskID:    ssTaskID,
		Target:               target,
	}); err != nil {
		return 0, false, err
	}
	note := fmt.Sprintf("Linked to shared ARTEX Task #%d (%s). Discoveries, assets, facts, hints, and findings from Deep Agent IDE (/ai) and Graph Chat (/chat) share this task.", taskID, t.Description)
	_, _ = s.m.pg.AppendConvActivity(c.ID, db.Activity{
		Worker:  "deep-agent-ide",
		Kind:    "text",
		Summary: note,
		Detail:  note,
	})
	return c.ID, true, nil
}

func (s *Server) summarizeSharedTask(t *Task) sharedTaskSummary {
	tid, _ := strconv.ParseInt(t.ID, 10, 64)
	cid, cname, target, _, _ := s.taskPrimaryMetadata(tid)
	_ = cid
	sum := sharedTaskSummary{
		ID:             tid,
		Name:           t.Name,
		Description:    t.Description,
		Goal:           t.Goal,
		Status:         s.deriveTaskStatus(t),
		CompanyName:    cname,
		Target:         target,
		ConversationID: s.resolveConversationForTask(tid),
	}
	if counts, err := t.Store.Stats(); err == nil {
		for _, n := range counts {
			sum.NodeCount += n
		}
		sum.FindingCount = counts[db.KindFinding]
	}
	if sum.FindingCount == 0 && s.m.pg != nil {
		_ = s.m.pg.QueryRow(`SELECT count(*) FROM findings WHERE task_id=$1`, tid).Scan(&sum.FindingCount)
	}
	if as := s.assetStore(); as != nil {
		if byType, err := as.CountsByTypeForTask(tid); err == nil {
			for _, n := range byType {
				sum.AssetCount += n
			}
		}
	}
	return sum
}

func (s *Server) buildSharedContextResponse() sharedContextResponse {
	state := s.loadSharedContext()
	tasks := s.m.List()
	recent := make([]sharedTaskSummary, 0, min(len(tasks), 20))
	var activeTask *sharedTaskSummary
	for i := len(tasks) - 1; i >= 0; i-- {
		sum := s.summarizeSharedTask(tasks[i])
		if state.TaskID > 0 && sum.ID == state.TaskID {
			copySum := sum
			activeTask = &copySum
		}
		if len(recent) < 20 {
			recent = append(recent, sum)
		}
	}

	resp := sharedContextResponse{
		TaskID:                state.TaskID,
		ConversationID:        state.ConversationID,
		Target:                state.Target,
		WorkspacePath:         state.WorkspacePath,
		BundleID:              state.BundleID,
		ScanMode:              state.ScanMode,
		Source:                state.Source,
		UpdatedAt:             state.UpdatedAt,
		TrafficCaptureEnabled: s.m.TrafficEnabled(),
		RecentTasks:           recent,
	}
	if s.m.Traffic() != nil {
		resp.InternalProxyURL = "http://artex:8788"
	}
	if activeTask != nil {
		resp.TaskDescription = activeTask.Description
		resp.TaskGoal = activeTask.Goal
		resp.TaskStatus = activeTask.Status
		resp.CompanyName = activeTask.CompanyName
		resp.AssetCount = activeTask.AssetCount
		resp.FindingCount = activeTask.FindingCount
		resp.NodeCount = activeTask.NodeCount
		if resp.Target == "" {
			resp.Target = activeTask.Target
		}
		if resp.ConversationID == 0 {
			resp.ConversationID = activeTask.ConversationID
		}
	} else if state.TaskID > 0 {
		// Task was archived/deleted; keep clean empty task_id.
		resp.TaskID = 0
	}
	return resp
}

func (s *Server) getSharedContext(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	writeJSON(w, 200, s.buildSharedContextResponse())
}

func (s *Server) putSharedContext(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req struct {
		TaskID         int64  `json:"task_id"`
		ConversationID int64  `json:"conversation_id"`
		Target         string `json:"target"`
		WorkspacePath  string `json:"workspace_path"`
		BundleID       int64  `json:"bundle_id"`
		ScanMode       string `json:"scan_mode"`
		Source         string `json:"source"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, "invalid JSON: "+err.Error())
		return
	}
	if req.TaskID > 0 {
		if _, ok := s.m.Task(strconv.FormatInt(req.TaskID, 10)); !ok {
			writeErr(w, 404, fmt.Sprintf("task #%d not found", req.TaskID))
			return
		}
		if req.ConversationID <= 0 {
			req.ConversationID = s.resolveConversationForTask(req.TaskID)
		}
		if strings.TrimSpace(req.Target) == "" {
			_, _, t, _, _ := s.taskPrimaryMetadata(req.TaskID)
			req.Target = t
		}
	} else {
		req.TaskID = 0
	}
	if err := s.saveSharedContext(sharedWorkspaceContext{
		TaskID:         req.TaskID,
		ConversationID: req.ConversationID,
		Target:         req.Target,
		WorkspacePath:  req.WorkspacePath,
		BundleID:       req.BundleID,
		ScanMode:       req.ScanMode,
		Source:         req.Source,
	}); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, s.buildSharedContextResponse())
}

func (s *Server) ensureTaskChat(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req struct {
		TaskID   json.RawMessage `json:"task_id"`
		AgentKey string          `json:"agent_key"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, "invalid JSON: "+err.Error())
		return
	}
	taskID := parseProfileID(req.TaskID)
	if taskID <= 0 {
		writeErr(w, 400, "task_id must be a positive integer")
		return
	}
	convID, created, err := s.ensureLinkedConversation(taskID, "", "", "", 0, req.AgentKey)
	if err != nil {
		status := 500
		if err == sql.ErrNoRows || strings.Contains(err.Error(), "not found") {
			status = 404
		}
		writeErr(w, status, err.Error())
		return
	}
	_, _, target, _, _ := s.taskPrimaryMetadata(taskID)
	_ = s.saveSharedContext(sharedWorkspaceContext{
		TaskID:         taskID,
		ConversationID: convID,
		Target:         target,
		Source:         "ensure-chat",
	})
	writeJSON(w, 200, map[string]any{
		"ok":              true,
		"task_id":         taskID,
		"conversation_id": convID,
		"created":         created,
	})
}

type sharedChatTurn struct {
	Source    string `json:"source"` // "graph_chat" | "task_chat"
	ID        int64  `json:"id"`
	Worker    string `json:"worker"`
	Role      string `json:"role"` // "user" | "assistant" | "deep-agent-ide" | "planner"
	Text      string `json:"text"`
	CreatedAt string `json:"created_at,omitempty"`
}

type sharedNodeBrief struct {
	ID       int64  `json:"id"`
	Kind     string `json:"kind"`
	State    string `json:"state,omitempty"`
	Severity string `json:"severity,omitempty"`
	Summary  string `json:"summary"`
	Detail   string `json:"detail,omitempty"`
}

type sharedAssetBrief struct {
	ID    int64  `json:"id"`
	Type  string `json:"type"`
	Label string `json:"label"`
}

type sharedBriefingResponse struct {
	TaskID           int64              `json:"task_id"`
	ConversationID   int64              `json:"conversation_id,omitempty"`
	Target           string             `json:"target,omitempty"`
	WorkspacePath    string             `json:"workspace_path,omitempty"`
	CompanyName      string             `json:"company_name,omitempty"`
	TaskStatus       string             `json:"task_status,omitempty"`
	TaskDescription  string             `json:"task_description,omitempty"`
	TaskGoal         string             `json:"task_goal,omitempty"`
	Goals            []sharedNodeBrief  `json:"goals,omitempty"`
	Findings         []sharedNodeBrief  `json:"findings,omitempty"`
	Facts            []sharedNodeBrief  `json:"facts,omitempty"`
	Intents          []sharedNodeBrief  `json:"intents,omitempty"`
	Assets           []sharedAssetBrief `json:"assets,omitempty"`
	ChatHistory      []sharedChatTurn   `json:"chat_history,omitempty"`
	BriefingMarkdown string             `json:"briefing_markdown"`
}

func truncateUTF8(s string, maxChars int) string {
	s = strings.TrimSpace(s)
	if maxChars <= 0 || len(s) <= maxChars {
		return s
	}
	runes := []rune(s)
	if len(runes) <= maxChars {
		return s
	}
	return strings.TrimSpace(string(runes[:maxChars])) + "..."
}

func sanitizeHookText(s string) string {
	r := strings.NewReplacer("<", "[", ">", "]")
	return r.Replace(s)
}

func extractActivityReadableText(kind, summary, detail string) string {
	raw := strings.TrimSpace(detail)
	if raw == "" {
		return strings.TrimSpace(summary)
	}
	if kind == "user" && strings.HasPrefix(raw, "{") {
		var parsed struct {
			Text        string `json:"text"`
			Attachments []struct {
				Name string `json:"name"`
				Path string `json:"path"`
			} `json:"attachments"`
		}
		if json.Unmarshal([]byte(raw), &parsed) == nil {
			txt := strings.TrimSpace(parsed.Text)
			if txt == "" {
				txt = strings.TrimSpace(summary)
			}
			if len(parsed.Attachments) > 0 {
				names := make([]string, 0, len(parsed.Attachments))
				for _, att := range parsed.Attachments {
					if att.Name != "" {
						names = append(names, att.Name)
					}
				}
				if len(names) > 0 {
					txt += " [attachments: " + strings.Join(names, ", ") + "]"
				}
			}
			return strings.TrimSpace(txt)
		}
	}
	return raw
}

func (s *Server) collectSharedChatHistory(taskID, convID int64, limit int) []sharedChatTurn {
	if s == nil || s.m == nil || s.m.pg == nil {
		return nil
	}
	if limit <= 0 {
		limit = 12
	}
	if limit > 50 {
		limit = 50
	}
	if convID <= 0 && taskID > 0 {
		convID = s.resolveConversationForTask(taskID)
	}

	var out []sharedChatTurn

	if taskID > 0 {
		if t, ok := s.m.Task(strconv.FormatInt(taskID, 10)); ok && t != nil && t.Store != nil {
			expID := t.Store.ID()
			if expID > 0 {
				rows, err := s.m.pg.Query(`
					SELECT id, COALESCE(worker,''), COALESCE(kind,''), COALESCE(summary,''), COALESCE(left(detail, 1200),''), created_at
					FROM activity
					WHERE exploration_id = $1
					  AND NOT is_error
					  AND (
					    (worker = 'mainagent' AND kind IN ('user', 'result', 'text'))
					    OR (worker = 'planner' AND kind = 'result')
					  )
					ORDER BY id DESC
					LIMIT $2`, expID, limit)
				if err == nil {
					var taskTurns []sharedChatTurn
					for rows.Next() {
						var id int64
						var worker, kind, summary, detail string
						var createdAt time.Time
						if rows.Scan(&id, &worker, &kind, &summary, &detail, &createdAt) != nil {
							continue
						}
						txt := truncateUTF8(extractActivityReadableText(kind, summary, detail), 700)
						if txt == "" || strings.HasPrefix(txt, "(no text summary") {
							continue
						}
						role := worker
						if kind == "user" {
							role = "user"
						}
						taskTurns = append(taskTurns, sharedChatTurn{
							Source:    "task_chat",
							ID:        id,
							Worker:    worker,
							Role:      role,
							Text:      txt,
							CreatedAt: createdAt.UTC().Format(time.RFC3339),
						})
					}
					rows.Close()
					for i := len(taskTurns) - 1; i >= 0; i-- {
						out = append(out, taskTurns[i])
					}
				}
			}
		}
	}

	if convID > 0 {
		rows, err := s.m.pg.Query(`
			SELECT id, COALESCE(worker,''), COALESCE(kind,''), COALESCE(summary,''), COALESCE(left(detail, 1200),''), created_at
			FROM conversation_activities
			WHERE conversation_id = $1
			  AND NOT is_error
			  AND kind IN ('user', 'result', 'text')
			ORDER BY id DESC
			LIMIT $2`, convID, limit)
		if err == nil {
			var convTurns []sharedChatTurn
			for rows.Next() {
				var id int64
				var worker, kind, summary, detail string
				var createdAt time.Time
				if rows.Scan(&id, &worker, &kind, &summary, &detail, &createdAt) != nil {
					continue
				}
				txt := truncateUTF8(extractActivityReadableText(kind, summary, detail), 700)
				if txt == "" || strings.HasPrefix(txt, "Linked to shared ARTEX Task #") {
					continue
				}
				role := "assistant"
				if kind == "user" {
					role = "user"
				} else if worker == "deep-agent-ide" {
					role = "deep-agent-ide"
				}
				convTurns = append(convTurns, sharedChatTurn{
					Source:    "graph_chat",
					ID:        id,
					Worker:    worker,
					Role:      role,
					Text:      txt,
					CreatedAt: createdAt.UTC().Format(time.RFC3339),
				})
			}
			rows.Close()
			for i := len(convTurns) - 1; i >= 0; i-- {
				out = append(out, convTurns[i])
			}
		}
	}

	if len(out) > limit*2 {
		out = out[len(out)-limit*2:]
	}
	return out
}

func summarizeNodeBrief(n *db.Node) sharedNodeBrief {
	b := sharedNodeBrief{
		ID:    n.ID,
		Kind:  n.Kind,
		State: n.State,
	}
	var m map[string]any
	_ = json.Unmarshal(n.Payload, &m)
	strField := func(keys ...string) string {
		for _, k := range keys {
			if v, ok := m[k].(string); ok && strings.TrimSpace(v) != "" {
				return strings.TrimSpace(v)
			}
		}
		return ""
	}
	switch n.Kind {
	case db.KindGoal:
		b.Summary = truncateUTF8(strField("text", "summary"), 240)
	case db.KindIntent:
		b.Summary = truncateUTF8(strField("summary", "text"), 240)
	case db.KindFinding:
		b.Severity = strField("severity")
		name := strField("name", "vulnclass")
		sum := strField("summary")
		if name != "" && sum != "" && !strings.EqualFold(name, sum) {
			b.Summary = truncateUTF8(name+": "+sum, 260)
		} else if name != "" {
			b.Summary = truncateUTF8(name, 260)
		} else {
			b.Summary = truncateUTF8(sum, 260)
		}
		b.Detail = truncateUTF8(strField("evidence", "detail"), 220)
	default: // fact / hint
		b.Summary = truncateUTF8(strField("summary", "text"), 240)
		b.Detail = truncateUTF8(strField("detail", "evidence"), 220)
	}
	return b
}

func summarizeAssetBrief(a *db.Asset) sharedAssetBrief {
	parts := []string{}
	if a.Method != "" && a.URL != "" {
		parts = append(parts, a.Method+" "+a.URL)
	} else if a.URL != "" {
		parts = append(parts, a.URL)
	} else if a.Domain != "" {
		parts = append(parts, a.Domain)
	} else if a.IP != "" {
		if a.Port != nil && *a.Port > 0 {
			parts = append(parts, fmt.Sprintf("%s:%d", a.IP, *a.Port))
		} else {
			parts = append(parts, a.IP)
		}
	} else if a.RootDomain != "" {
		parts = append(parts, a.RootDomain)
	} else if a.AppName != "" {
		parts = append(parts, a.AppName)
	}
	if a.ServiceName != "" {
		parts = append(parts, "("+a.ServiceName+")")
	}
	if a.PageTitle != "" {
		parts = append(parts, "- "+truncateUTF8(a.PageTitle, 60))
	}
	return sharedAssetBrief{
		ID:    a.ID,
		Type:  a.Type,
		Label: strings.TrimSpace(strings.Join(parts, " ")),
	}
}

func (s *Server) buildSharedBriefing(taskID, convID int64, maxTurns int) sharedBriefingResponse {
	active := s.buildSharedContextResponse()
	if taskID <= 0 {
		taskID = active.TaskID
	}
	if convID <= 0 {
		if taskID > 0 && taskID != active.TaskID {
			convID = s.resolveConversationForTask(taskID)
		} else {
			convID = active.ConversationID
		}
	}
	if maxTurns <= 0 {
		maxTurns = 6
	}

	resp := sharedBriefingResponse{
		TaskID:         taskID,
		ConversationID: convID,
		WorkspacePath:  active.WorkspacePath,
	}

	if taskID <= 0 && convID <= 0 && resp.WorkspacePath == "" {
		return resp
	}

	if taskID > 0 {
		if t, ok := s.m.Task(strconv.FormatInt(taskID, 10)); ok && t != nil {
			sum := s.summarizeSharedTask(t)
			resp.Target = sum.Target
			if resp.Target == "" {
				resp.Target = active.Target
			}
			resp.CompanyName = sum.CompanyName
			resp.TaskStatus = sum.Status
			resp.TaskDescription = sum.Description
			resp.TaskGoal = sum.Goal
			if convID <= 0 {
				convID = sum.ConversationID
				resp.ConversationID = convID
			}
			if t.Store != nil {
				if goals, err := t.Store.ListByKind(db.KindGoal, 10); err == nil {
					for _, n := range goals {
						resp.Goals = append(resp.Goals, summarizeNodeBrief(n))
					}
				}
				if findings, err := t.Store.ListByKind(db.KindFinding, 10); err == nil {
					for _, n := range findings {
						resp.Findings = append(resp.Findings, summarizeNodeBrief(n))
					}
				}
				if facts, err := t.Store.ListByKind(db.KindFact, 8); err == nil {
					for _, n := range facts {
						resp.Facts = append(resp.Facts, summarizeNodeBrief(n))
					}
				}
				if intents, err := t.Store.ListByKind(db.KindIntent, 8); err == nil {
					for _, n := range intents {
						resp.Intents = append(resp.Intents, summarizeNodeBrief(n))
					}
				}
			}
			if as := s.assetStore(); as != nil {
				if assets, err := as.QueryDSLInScope("", "", taskID, 12, 0); err == nil {
					for _, a := range assets {
						resp.Assets = append(resp.Assets, summarizeAssetBrief(a))
					}
				}
			}
		}
	}

	resp.ChatHistory = s.collectSharedChatHistory(taskID, convID, maxTurns)

	var md strings.Builder
	md.WriteString("[ACTIVE SHARED ARTEX WORKSPACE CONTEXT]\n")
	if resp.TaskID > 0 {
		fmt.Fprintf(&md, "- Active Mission: ARTEX Task #%d (status: %s)\n", resp.TaskID, resp.TaskStatus)
		if resp.Target != "" {
			fmt.Fprintf(&md, "- Target: %s\n", sanitizeHookText(resp.Target))
		}
		if resp.CompanyName != "" {
			fmt.Fprintf(&md, "- Organization / Scope: %s\n", sanitizeHookText(resp.CompanyName))
		}
		if resp.TaskDescription != "" {
			fmt.Fprintf(&md, "- Description: %s\n", sanitizeHookText(resp.TaskDescription))
		}
		if resp.TaskGoal != "" {
			fmt.Fprintf(&md, "- Mission Goal: %s\n", sanitizeHookText(truncateUTF8(resp.TaskGoal, 280)))
		}
	}
	if resp.WorkspacePath != "" {
		fmt.Fprintf(&md, "- Shared Workspace Folder (mounted identically in /chat and /ai): %s\n", sanitizeHookText(resp.WorkspacePath))
	}
	activeBundleID := active.BundleID
	activeScanMode := active.ScanMode
	if resp.TaskID > 0 && s.m != nil && s.m.pg != nil {
		if prof, perr := s.m.pg.GetTaskScanProfile(resp.TaskID); perr == nil && prof != nil {
			if prof.ScanMode != "" {
				activeScanMode = prof.ScanMode
			}
			if prof.BundleID > 0 {
				activeBundleID = prof.BundleID
			}
		}
	}
	if activeScanMode != "" && activeScanMode != "full" {
		fmt.Fprintf(&md, "- Active Scan Operation Mode: %s\n", sanitizeHookText(activeScanMode))
	}
	if activeBundleID > 0 && s.m != nil && s.m.pg != nil {
		if bundle, berr := s.m.pg.GetScanBundle(activeBundleID); berr == nil && bundle != nil {
			md.WriteString(sanitizeHookText(formatScanBundleBriefing(bundle)))
		}
	}
	if _, pbBrief := s.buildPlaybookBriefingForTask(resp.TaskID, resp.Target); pbBrief != "" {
		md.WriteString("\n" + sanitizeHookText(pbBrief) + "\n")
	}
	if resp.ConversationID > 0 {
		fmt.Fprintf(&md, "- Linked Graph Chat Conversation: #%d\n", resp.ConversationID)
	}

	md.WriteString("\n[CONTEXT CONTINUITY RULE - READ BEFORE ACTING]\n")
	if resp.TaskID > 0 {
		fmt.Fprintf(&md, "The operator's message continues ARTEX Task #%d above. ", resp.TaskID)
		if resp.WorkspacePath != "" {
			fmt.Fprintf(&md, "Shared folder %s is attached to this mission and directly accessible in /workspace. ", sanitizeHookText(resp.WorkspacePath))
		}
		fmt.Fprintf(&md, "Resolve implicit references ('ในนั้น', 'ไฟล์นั้น', 'script ต่างๆในนั้น', 'เป้านั้น', 'ต่อจากเมื่อกี้') against ARTEX Task #%d (%s%s). Use get_task_node_detail(id=...) or get_chat_history() for full node text.\n",
			resp.TaskID, sanitizeHookText(resp.Target), func() string {
				if resp.WorkspacePath != "" {
					return " · " + sanitizeHookText(resp.WorkspacePath)
				}
				return ""
			}())
	} else {
		md.WriteString("The operator switched between Pentest Graph Chat (/chat) and Deep Agent IDE (/ai). Resolve follow-up questions against the shared workspace/conversation below.\n")
	}

	if len(resp.Goals) > 0 {
		md.WriteString("\n### Mission Goals\n")
		for _, g := range resp.Goals {
			fmt.Fprintf(&md, "- [goal#%d | %s] %s\n", g.ID, g.State, sanitizeHookText(g.Summary))
		}
	}
	if len(resp.Findings) > 0 {
		md.WriteString("\n### Confirmed Findings\n")
		for _, f := range resp.Findings {
			sev := ""
			if f.Severity != "" {
				sev = strings.ToUpper(f.Severity) + " · "
			}
			fmt.Fprintf(&md, "- [node#%d] %s%s\n", f.ID, sev, sanitizeHookText(f.Summary))
		}
	}
	if len(resp.Assets) > 0 {
		md.WriteString("\n### Scoped Target Assets\n")
		for _, a := range resp.Assets {
			fmt.Fprintf(&md, "- [asset#%d | %s] %s\n", a.ID, a.Type, sanitizeHookText(a.Label))
		}
	}
	if len(resp.Facts) > 0 {
		md.WriteString("\n### Key Exploration Facts (call get_task_node_detail for full text)\n")
		for _, f := range resp.Facts {
			line := sanitizeHookText(f.Summary)
			if f.Detail != "" {
				line += " — " + sanitizeHookText(f.Detail)
			}
			fmt.Fprintf(&md, "- [fact#%d] %s\n", f.ID, line)
		}
	}
	if len(resp.Intents) > 0 {
		md.WriteString("\n### Recent Exploration Intents\n")
		for _, it := range resp.Intents {
			fmt.Fprintf(&md, "- [intent#%d | %s] %s\n", it.ID, it.State, sanitizeHookText(it.Summary))
		}
	}
	if len(resp.ChatHistory) > 0 {
		md.WriteString("\n### Recent Shared Conversation History (/chat & Task Chat)\n")
		for _, turn := range resp.ChatHistory {
			fmt.Fprintf(&md, "- [%s/%s]: %s\n", turn.Source, turn.Role, sanitizeHookText(turn.Text))
		}
	}

	resp.BriefingMarkdown = strings.TrimSpace(md.String())
	return resp
}

func (s *Server) syncSharedContextFromChat(convID int64) {
	if convID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return
	}
	var taskID int64
	var target string
	_ = s.m.pg.QueryRow(`
		SELECT COALESCE(task_id, 0), COALESCE(target, '')
		FROM conversation_links
		WHERE conversation_id = $1
		ORDER BY id DESC
		LIMIT 1`, convID).Scan(&taskID, &target)
	cur := s.loadSharedContext()
	if taskID > 0 {
		if strings.TrimSpace(target) == "" {
			_, _, target, _, _ = s.taskPrimaryMetadata(taskID)
		}
		_ = s.saveSharedContext(sharedWorkspaceContext{
			TaskID:         taskID,
			ConversationID: convID,
			Target:         target,
			Source:         "chat",
		})
		return
	}
	if cur.TaskID == 0 {
		_ = s.saveSharedContext(sharedWorkspaceContext{
			TaskID:         0,
			ConversationID: convID,
			Source:         "chat",
		})
	}
}

func (s *Server) syncSharedContextFromTaskChat(taskID int64) {
	if taskID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return
	}
	convID := s.resolveConversationForTask(taskID)
	_, _, target, _, _ := s.taskPrimaryMetadata(taskID)
	_ = s.saveSharedContext(sharedWorkspaceContext{
		TaskID:         taskID,
		ConversationID: convID,
		Target:         target,
		Source:         "task_chat",
	})
}

func (s *Server) buildDeepAgentHandoffForChat(convID int64) string {
	if convID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return ""
	}
	var lastChatResultID int64
	_ = s.m.pg.QueryRow(`
		SELECT COALESCE(MAX(id), 0)
		FROM conversation_activities
		WHERE conversation_id = $1 AND kind = 'result' AND COALESCE(worker, '') <> 'deep-agent-ide'`,
		convID).Scan(&lastChatResultID)

	rows, err := s.m.pg.Query(`
		SELECT COALESCE(summary, ''), COALESCE(left(detail, 1800), '')
		FROM conversation_activities
		WHERE conversation_id = $1
		  AND id > $2
		  AND worker = 'deep-agent-ide'
		  AND NOT is_error
		ORDER BY id DESC
		LIMIT 5`, convID, lastChatResultID)
	if err != nil {
		return ""
	}
	var notes []string
	for rows.Next() {
		var sum, det string
		if rows.Scan(&sum, &det) != nil {
			continue
		}
		txt := strings.TrimSpace(det)
		if txt == "" {
			txt = strings.TrimSpace(sum)
		}
		if txt == "" || strings.HasPrefix(txt, "Linked to shared ARTEX Task #") {
			continue
		}
		notes = append(notes, txt)
	}
	rows.Close()
	if len(notes) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("[Shared Context Update from Deep Agent IDE (/ai)]\n")
	b.WriteString("While on this conversation/task, the operator also worked in Deep Agent IDE (/ai). Use the exchanges below as direct prior conversation context:\n\n")
	for i := len(notes) - 1; i >= 0; i-- {
		b.WriteString("---\n")
		b.WriteString(notes[i])
		b.WriteString("\n")
	}
	b.WriteString("---\n")
	return b.String()
}

func (s *Server) buildDeepAgentHandoffForTask(taskID int64) string {
	if taskID <= 0 || s == nil || s.m == nil || s.m.pg == nil {
		return ""
	}
	convID := s.resolveConversationForTask(taskID)
	if convID <= 0 {
		return ""
	}
	rows, err := s.m.pg.Query(`
		SELECT COALESCE(summary, ''), COALESCE(left(detail, 1600), '')
		FROM conversation_activities
		WHERE conversation_id = $1
		  AND worker = 'deep-agent-ide'
		  AND NOT is_error
		ORDER BY id DESC
		LIMIT 4`, convID)
	if err != nil {
		return ""
	}
	var notes []string
	for rows.Next() {
		var sum, det string
		if rows.Scan(&sum, &det) != nil {
			continue
		}
		txt := strings.TrimSpace(det)
		if txt == "" {
			txt = strings.TrimSpace(sum)
		}
		if txt == "" || strings.HasPrefix(txt, "Linked to shared ARTEX Task #") {
			continue
		}
		notes = append(notes, txt)
	}
	rows.Close()
	if len(notes) == 0 {
		return ""
	}
	var b strings.Builder
	fmt.Fprintf(&b, "[Shared Context Update from Deep Agent IDE (/ai) on Task #%d]\n", taskID)
	for i := len(notes) - 1; i >= 0; i-- {
		b.WriteString("---\n")
		b.WriteString(notes[i])
		b.WriteString("\n")
	}
	b.WriteString("---\n")
	return b.String()
}
