package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/intercept"
	actool "github.com/Autumn-27/norma/tool"
)

func sandboxManagerBaseURL() string {
	if u := strings.TrimSpace(os.Getenv("SANDBOX_MANAGER_URL")); u != "" {
		return strings.TrimRight(u, "/")
	}
	return "http://host.docker.internal:8010/api/model-studio/sandboxes"
}

func (s *Server) resolveToolTaskID(ctx context.Context, rawTaskID json.RawMessage) int64 {
	tid := parseProfileID(rawTaskID)
	if tid <= 0 {
		if cid := intercept.ConvIDFromContext(ctx); cid > 0 && s.m != nil && s.m.pg != nil {
			if links, err := s.m.pg.ListConversationLinks(cid); err == nil {
				for _, l := range links {
					if l.TaskID != nil && *l.TaskID > 0 {
						tid = *l.TaskID
						break
					}
				}
			}
		}
	}
	if tid <= 0 {
		tid = s.loadSharedContext().TaskID
	}
	return tid
}

// --- 1. pgvector Semantic Playbook Memory Core Tools ---

func (s *Server) toolSearchPlaybookMemory() actool.CoreTool {
	return roTool(
		"search_playbook_memory",
		"Query Project-Malaria's pgvector Semantic Playbook Memory for previously verified exploitation techniques, WAF/CMS bypasses, and architectural patterns matching a target's tech stack (e.g. 'Laravel', 'WordPress', 'custom PHP PHPSESSID', 'JWT HMAC', 'IDOR') before testing from scratch.",
		objSchema(map[string]any{
			"query":     strParam("technology stack, CMS signature, endpoint behavior, or vulnerability class to search"),
			"tech_tags": map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "optional canonical tech tags (e.g. ['laravel', 'php', 'wordpress', 'jwt'])"},
			"limit":     map[string]any{"type": "integer", "description": "max results (1-20, default 6)"},
		}, "query"),
		func(_ context.Context, in json.RawMessage) (actool.Result, error) {
			if s.m == nil || s.m.pg == nil {
				return actool.Errorf("PostgreSQL playbook store unavailable"), nil
			}
			var a struct {
				Query    string   `json:"query"`
				TechTags []string `json:"tech_tags"`
				Limit    int      `json:"limit"`
			}
			if err := json.Unmarshal(in, &a); err != nil {
				return actool.Errorf(err.Error()), nil
			}
			items, err := s.m.pg.SearchSemanticPlaybooks(a.Query, a.TechTags, a.Limit)
			if err != nil {
				return actool.Errorf("playbook search failed: " + err.Error()), nil
			}
			return jsonResult(map[string]any{
				"ok":          true,
				"total_store": s.m.pg.CountSemanticPlaybooks(),
				"count":       len(items),
				"playbooks":   items,
			})
		},
	)
}

func (s *Server) toolSavePlaybookMemory() actool.CoreTool {
	return wrTool(
		"save_playbook_memory",
		"Persist a verified exploitation technique, CMS/framework quirk, WAF bypass, or high-value tactical lesson into pgvector Semantic Playbook Memory so future missions on similar tech stacks retrieve it automatically.",
		objSchema(map[string]any{
			"title":         strParam("concise playbook title (e.g. 'Laravel XSRF + Custom Admin Route Enumeration')"),
			"playbook_text": strParam("actionable steps, verified behavior, safe payload pattern, or defensive quirk"),
			"vuln_class":    strParam("optional vulnerability class or CWE"),
			"tactic":        strParam("optional tactic category (e.g. 'Reconnaissance', 'Auth Bypass', 'WAF Evasion')"),
			"tech_tags":     map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "optional tech tags"},
			"task_id":       strParam("optional source task id"),
		}, "title", "playbook_text"),
		func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
			if s.m == nil || s.m.pg == nil {
				return actool.Errorf("PostgreSQL playbook store unavailable"), nil
			}
			var a struct {
				Title        string          `json:"title"`
				PlaybookText string          `json:"playbook_text"`
				VulnClass    string          `json:"vuln_class"`
				Tactic       string          `json:"tactic"`
				TechTags     []string        `json:"tech_tags"`
				TaskID       json.RawMessage `json:"task_id"`
			}
			if err := json.Unmarshal(in, &a); err != nil {
				return actool.Errorf(err.Error()), nil
			}
			tid := s.resolveToolTaskID(ctx, a.TaskID)
			var tidPtr *int64
			if tid > 0 {
				tidPtr = &tid
			}
			saved, err := s.m.pg.UpsertSemanticPlaybook(db.SemanticPlaybook{
				Title:        a.Title,
				PlaybookText: a.PlaybookText,
				VulnClass:    a.VulnClass,
				Tactic:       a.Tactic,
				TechTags:     a.TechTags,
				SourceKind:   "manual",
				SourceTaskID: tidPtr,
			})
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			return jsonResult(map[string]any{"ok": true, "playbook": saved})
		},
	)
}

// --- 2. Per-Task Isolated Ephemeral Kali Sandbox Core Tools ---

func (s *Server) toolSandboxExec() actool.CoreTool {
	return wrTool(
		"sandbox_exec",
		"Execute a shell command, custom exploit compilation (gcc/python3), temporary package install, or Kali tool (nmap, sqlmap, nuclei, ffuf, gobuster, nikto, hydra) inside an isolated, resource-capped per-task Kali Linux container (malaria-kali-task-<id>). Scratch files live in /sandbox without polluting the main platform container; shared /workspace is mounted read-only at /workspace.",
		objSchema(map[string]any{
			"command":     strParam("shell command to execute inside the isolated Kali task container"),
			"task_id":     strParam("optional ARTEX task id (defaults to current linked/active task)"),
			"timeout_sec": map[string]any{"type": "integer", "description": "command timeout in seconds (5-600, default 120)"},
			"workdir":     strParam("working directory inside container (default: /sandbox)"),
		}, "command"),
		func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
			var a struct {
				Command    string          `json:"command"`
				TaskID     json.RawMessage `json:"task_id"`
				TimeoutSec int             `json:"timeout_sec"`
				Workdir    string          `json:"workdir"`
			}
			if err := json.Unmarshal(in, &a); err != nil {
				return actool.Errorf(err.Error()), nil
			}
			tid := s.resolveToolTaskID(ctx, a.TaskID)
			if tid <= 0 {
				tid = 1
			}
			if a.TimeoutSec <= 0 {
				a.TimeoutSec = 120
			}
			payload, _ := json.Marshal(map[string]any{
				"task_id":     tid,
				"command":     a.Command,
				"timeout_sec": a.TimeoutSec,
				"workdir":     a.Workdir,
			})
			httpTimeout := time.Duration(a.TimeoutSec+20) * time.Second
			reqCtx, cancel := context.WithTimeout(ctx, httpTimeout)
			defer cancel()
			req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, sandboxManagerBaseURL()+"/exec", bytes.NewReader(payload))
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			req.Header.Set("Content-Type", "application/json")
			cl := &http.Client{Timeout: httpTimeout}
			resp, err := cl.Do(req)
			if err != nil {
				return actool.Errorf("sandbox manager unreachable: " + err.Error()), nil
			}
			defer resp.Body.Close()
			raw, _ := io.ReadAll(resp.Body)
			return actool.Text(string(raw)), nil
		},
	)
}

func (s *Server) toolSandboxManage() actool.CoreTool {
	return wrTool(
		"sandbox_manage",
		"Check status, pre-spawn, or destroy a task's isolated ephemeral Kali Linux sandbox container (malaria-kali-task-<id>).",
		objSchema(map[string]any{
			"action":      strParam("status | spawn | destroy"),
			"task_id":     strParam("optional ARTEX task id (defaults to current linked/active task)"),
			"wipe_files":  map[string]any{"type": "boolean", "description": "for destroy: also delete /sandbox scratch files (default false)"},
			"ttl_minutes": map[string]any{"type": "integer", "description": "for spawn: idle auto-cleanup TTL in minutes (default 90)"},
		}, "action"),
		func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
			var a struct {
				Action     string          `json:"action"`
				TaskID     json.RawMessage `json:"task_id"`
				WipeFiles  bool            `json:"wipe_files"`
				TTLMinutes int             `json:"ttl_minutes"`
			}
			_ = json.Unmarshal(in, &a)
			tid := s.resolveToolTaskID(ctx, a.TaskID)
			if tid <= 0 {
				tid = 1
			}
			act := strings.ToLower(strings.TrimSpace(a.Action))
			reqCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			cl := &http.Client{Timeout: 30 * time.Second}

			var req *http.Request
			var err error
			switch act {
			case "spawn":
				body, _ := json.Marshal(map[string]any{"task_id": tid, "ttl_minutes": a.TTLMinutes})
				req, err = http.NewRequestWithContext(reqCtx, http.MethodPost, sandboxManagerBaseURL()+"/spawn", bytes.NewReader(body))
				if req != nil {
					req.Header.Set("Content-Type", "application/json")
				}
			case "destroy":
				body, _ := json.Marshal(map[string]any{"task_id": tid, "wipe_files": a.WipeFiles})
				req, err = http.NewRequestWithContext(reqCtx, http.MethodPost, sandboxManagerBaseURL()+"/destroy", bytes.NewReader(body))
				if req != nil {
					req.Header.Set("Content-Type", "application/json")
				}
			default:
				req, err = http.NewRequestWithContext(reqCtx, http.MethodGet, fmt.Sprintf("%s?task_id=%d", sandboxManagerBaseURL(), tid), nil)
			}
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			resp, err := cl.Do(req)
			if err != nil {
				return actool.Errorf("sandbox manager unreachable: " + err.Error()), nil
			}
			defer resp.Body.Close()
			raw, _ := io.ReadAll(resp.Body)
			return actool.Text(string(raw)), nil
		},
	)
}

// buildPlaybookBriefingForTask retrieves top matching semantic playbooks for a task's
// discovered tech stack, target, and facts so agents immediately leverage past wins.
func (s *Server) buildPlaybookBriefingForTask(taskID int64, targetHint string) ([]db.SemanticPlaybook, string) {
	if s == nil || s.m == nil || s.m.pg == nil {
		return nil, ""
	}
	var parts []string
	if targetHint != "" {
		parts = append(parts, targetHint)
	}
	if taskID > 0 {
		if t, ok := s.m.Task(fmt.Sprintf("%d", taskID)); ok && t != nil {
			parts = append(parts, t.Name, t.Description, t.Goal)
			if t.Store != nil {
				if facts, err := t.Store.ListByKind(db.KindFact, 6); err == nil {
					for _, f := range facts {
						parts = append(parts, string(f.Payload))
					}
				}
			}
		}
	}
	q := strings.TrimSpace(strings.Join(parts, " "))
	if q == "" {
		return nil, ""
	}
	items, err := s.m.pg.SearchSemanticPlaybooks(q, nil, 4)
	if err != nil || len(items) == 0 {
		return nil, ""
	}
	var filtered []db.SemanticPlaybook
	for _, it := range items {
		if it.Similarity >= 0.16 && (it.SourceTaskID == nil || *it.SourceTaskID != taskID || it.SourceKind == "manual" || it.SourceKind == "rsi_lesson") {
			filtered = append(filtered, it)
		}
	}
	if len(filtered) == 0 {
		filtered = items[:minInt(2, len(items))]
	}
	var sb strings.Builder
	sb.WriteString("[PGVECTOR SEMANTIC PLAYBOOK MEMORY — REUSABLE TACTICS FROM PAST ENGAGEMENTS]\n")
	for i, p := range filtered {
		if i >= 3 {
			break
		}
		txt := p.PlaybookText
		if len(txt) > 320 {
			txt = txt[:320] + "…"
		}
		fmt.Fprintf(&sb, "- Playbook #%d (%d%% match, tags: %s): %s\n  %s\n",
			p.ID, int(p.Similarity*100), strings.Join(p.TechTags, ","), p.Title, strings.ReplaceAll(txt, "\n", " "))
	}
	return filtered, strings.TrimSpace(sb.String())
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// --- Enterprise REST Handlers for Playbook Memory ---

func (s *Server) enterpriseListPlaybooks(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	rawTid := strings.TrimSpace(r.URL.Query().Get("task_id"))
	tid := int64(0)
	if rawTid != "" {
		fmt.Sscanf(rawTid, "%d", &tid)
	}
	if q == "" && tid > 0 {
		items, _ := s.buildPlaybookBriefingForTask(tid, "")
		if len(items) > 0 {
			writeJSON(w, 200, map[string]any{
				"ok":          true,
				"total_store": s.m.pg.CountSemanticPlaybooks(),
				"playbooks":   items,
			})
			return
		}
	}
	items, err := s.m.pg.SearchSemanticPlaybooks(q, nil, 15)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{
		"ok":          true,
		"total_store": s.m.pg.CountSemanticPlaybooks(),
		"playbooks":   items,
	})
}

func (s *Server) enterpriseSavePlaybook(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req struct {
		Title        string   `json:"title"`
		PlaybookText string   `json:"playbook_text"`
		VulnClass    string   `json:"vuln_class"`
		Tactic       string   `json:"tactic"`
		TechTags     []string `json:"tech_tags"`
		TaskID       int64    `json:"task_id"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	var tidPtr *int64
	if req.TaskID > 0 {
		tidPtr = &req.TaskID
	}
	saved, err := s.m.pg.UpsertSemanticPlaybook(db.SemanticPlaybook{
		Title:        req.Title,
		PlaybookText: req.PlaybookText,
		VulnClass:    req.VulnClass,
		Tactic:       req.Tactic,
		TechTags:     req.TechTags,
		SourceKind:   "manual",
		SourceTaskID: tidPtr,
	})
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{
		"ok":          true,
		"playbook":    saved,
		"total_store": s.m.pg.CountSemanticPlaybooks(),
	})
}

func (s *Server) enterpriseSyncPlaybooks(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req struct {
		TaskID int64 `json:"task_id"`
	}
	_ = decode(r, &req)
	synced, err := s.m.pg.SyncPlaybooksFromHistory(req.TaskID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{
		"ok":          true,
		"synced":      synced,
		"total_store": s.m.pg.CountSemanticPlaybooks(),
	})
}

func (s *Server) enterpriseDeletePlaybook(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	id := parsePathTaskID(r)
	if id <= 0 {
		writeErr(w, 400, "invalid playbook id")
		return
	}
	if err := s.m.pg.DeleteSemanticPlaybook(id); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "deleted_id": id, "total_store": s.m.pg.CountSemanticPlaybooks()})
}
