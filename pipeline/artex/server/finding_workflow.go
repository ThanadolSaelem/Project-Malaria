package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strconv"
	"strings"

	"github.com/Autumn-27/artex/agent"
	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/traffic"
	actool "github.com/Autumn-27/norma/tool"
)

func (s *Server) seedFindingWorkflowTools() {
	const hostSearchDescriptionFlag = "finding_workflow_tools_v3_host_search_description"
	if value, _, _ := s.m.pg.GetSetting(hostSearchDescriptionFlag); value != "true" {
		// Only replace the original built-in text. A user-edited description is
		// authoritative and must survive upgrades.
		legacy := "Query the target traffic already captured by the recording proxy (host is required; URL substrings or body keywords can further filter). body_contains runs a full-text search across captured request/response headers and bodies, supporting any substring and Chinese (at least 3 characters) — useful for finding passwords, keys, errors, intranet addresses, etc. in responses. Only an ultra-light index (id/method/url/status/resp_len) is returned, without any response content. By default only 3 entries are returned, at most 10 per page; use page to paginate when there are many results (page starts at 0); use traffic_get(id) to see the raw request/response of an entry. Use it first to review visited resources and find endpoints, avoiding repeated curl of the same URL."
		if _, err := s.m.pg.Exec(`UPDATE tools SET description=$1,updated_at=now() WHERE key='traffic_search' AND system AND description=$2`, traffic.TrafficSearchDescription, legacy); err != nil {
			// Log and leave the flag unset so the next startup retries; do not
			// return, or a transient error here would also skip the reporter
			// migration below — the two are independent.
			log.Printf("[evidence] upgrade traffic_search description: %v", err)
		} else {
			_ = s.m.pg.SetSetting(hostSearchDescriptionFlag, "true")
		}
	}
	const flag = "finding_workflow_tools_v2_reporter"
	if value, _, _ := s.m.pg.GetSetting(flag); value == "true" {
		return
	}
	for _, key := range []string{"report_finding", "add_hint", "add_task_hint"} {
		row, err := s.m.pg.GetTool(key)
		if err != nil {
			log.Printf("[evidence] load %s: %v", key, err)
			return
		}
		if row == nil || !row.System {
			continue
		}
		var schema map[string]any
		if err := json.Unmarshal(row.Schema, &schema); err != nil {
			log.Printf("[evidence] invalid schema for %s: %v", key, err)
			return
		}
		if schema == nil {
			log.Printf("[evidence] missing object schema for %s", key)
			return
		}
		props := objectProperty(schema, "properties")
		if key == "report_finding" {
			if _, exists := props["evidence_hint_id"]; !exists {
				props["evidence_hint_id"] = map[string]any{"type": "integer", "description": "optional: the hint ID in this task corresponding to this finding; the traffic_refs saved with that hint are bound as well; omit when there is no hint"}
			}
		} else {
			if _, exists := props["traffic_refs"]; !exists {
				props["traffic_refs"] = agent.HintTrafficSchema()
			}
			hints := objectProperty(props, "hints")
			if _, exists := hints["type"]; !exists {
				hints["type"] = "array"
			}
			items := objectProperty(hints, "items")
			if _, ok := items["type"]; !ok {
				items["type"] = "object"
			}
			itemProps := objectProperty(items, "properties")
			for name, value := range map[string]any{"text": strParam("hint content"), "asset_ids": map[string]any{"type": "array", "items": map[string]any{"type": "integer"}}, "traffic_refs": agent.HintTrafficSchema()} {
				if _, exists := itemProps[name]; !exists {
					itemProps[name] = value
				}
			}
		}
		raw, _ := json.Marshal(schema)
		result, err := s.m.pg.Exec(`UPDATE tools SET schema=$2::jsonb,updated_at=now() WHERE key=$1 AND system AND schema=$3::jsonb`, key, string(raw), string(row.Schema))
		if err != nil {
			log.Printf("[evidence] upgrade %s: %v", key, err)
			return
		}
		if n, _ := result.RowsAffected(); n != 1 {
			return
		} // preserve concurrent user edits
	}
	// Upgrade only the original default binding. Customized lists and enabled
	// flags survive; the one-time flag also preserves future user unbinding.
	readers := `["worker","reporter"]`
	for _, key := range []string{"traffic_search", "traffic_get", "traffic_blob"} {
		if _, err := s.m.pg.Exec(`UPDATE tools SET agents=$2::jsonb WHERE key=$1 AND system AND (agents='["worker"]'::jsonb OR (agents @> '["worker","planner","mainagent","auto","pentest"]'::jsonb AND jsonb_array_length(agents)=5))`, key, readers); err != nil {
			return
		}
	}
	if _, err := s.m.pg.Exec(`UPDATE tools SET agents=$1::jsonb WHERE key='get_finding_traffic' AND system AND agents @> '["auto","reporter"]'::jsonb AND jsonb_array_length(agents)=2`, `["auto","reporter","worker","planner","mainagent","pentest"]`); err != nil {
		return
	}
	// Replace the previous code default only; preserve customized binding lists.
	if _, err := s.m.pg.Exec(`UPDATE tools SET agents='["reporter"]'::jsonb WHERE key='bind_finding_traffic' AND system AND agents @> '["worker","planner","mainagent","auto","pentest"]'::jsonb AND jsonb_array_length(agents)=5`); err != nil {
		return
	}
	if err := s.m.pg.AddAgentToToolBinding("reporter", []string{"bind_finding_traffic"}); err != nil {
		return
	}
	_ = s.m.pg.SetSetting(flag, "true")
}

func objectProperty(parent map[string]any, key string) map[string]any {
	value, ok := parent[key].(map[string]any)
	if !ok {
		value = map[string]any{}
		parent[key] = value
	}
	return value
}

func (s *Server) agentFindingTrafficAccess(ctx context.Context, id int64, write bool) error {
	if id <= 0 {
		return errors.New("finding_id must be the standalone finding record ID, not an exploration node ID")
	}
	f, err := s.m.pg.GetFinding(id)
	if err != nil {
		return err
	}
	if f == nil {
		return fmt.Errorf("%w: finding_id=%d. Evidence tools use the standalone finding record ID; read it from the finding_id field of list_task_findings / get_task_node_detail; do not pass id / finding_node_id", db.ErrFindingNotFound, id)
	}
	if ri := agent.RunInfoFrom(ctx); ri.TaskID > 0 {
		task := s.m.ResolveTask(strconv.FormatInt(ri.TaskID, 10))
		if task == nil {
			return errors.New("task not found")
		}
		_, inherited, allowed := findingProvenanceInTask(task, f.TaskID)
		if !allowed {
			return errors.New("the current task cannot read this finding")
		}
		if write && inherited {
			return errors.New("traffic evidence of an inherited finding is read-only; modify it in the source task")
		}
	}
	return nil
}

func (s *Server) toolBindFindingTraffic() actool.CoreTool {
	return wrTool("bind_finding_traffic", "Bind verified real HTTP traffic to an already-registered finding. finding_id is the standalone finding record ID; do not pass an exploration node ID. All refs in a batch succeed or fail together; duplicate refs do not overwrite existing notes. Binding marks any existing report as pending update; do not re-probe or create duplicate findings just to attach more evidence.",
		objSchema(map[string]any{"finding_id": strParam("standalone finding record ID, read from the finding_id field of list_task_findings / get_task_node_detail"), "traffic_refs": agent.HintTrafficSchema()}, "finding_id", "traffic_refs"),
		func(ctx context.Context, raw json.RawMessage) (actool.Result, error) {
			if !s.m.pg.GetBool(settingAgentTrafficBinding, false) {
				return actool.Errorf("agent automatic traffic binding is disabled; enable it in system settings, or bind manually on the page."), nil
			}
			var args struct {
				FindingID json.RawMessage `json:"finding_id"`
				Refs      []db.TrafficRef `json:"traffic_refs"`
			}
			if err := json.Unmarshal(raw, &args); err != nil {
				return actool.Errorf(err.Error()), nil
			}
			id := parseProfileID(args.FindingID)
			if err := s.agentFindingTrafficAccess(ctx, id, true); err != nil {
				return actool.Errorf(err.Error()), nil
			}
			if len(args.Refs) == 0 {
				return actool.Errorf("binding requires at least one verified traffic_refs entry; no need to call this tool when there is no traffic"), nil
			}
			list, err := s.evidenceStore().Bind(ctx, id, args.Refs)
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			return jsonResult(trafficSummary(list))
		})
}

// seedProjectMalariaTrafficBinding enables automatic agent traffic binding once
// for Project-Malaria installations when no explicit setting exists yet, and gives
// reporter read access to list_findings for standalone chat findings.
func (s *Server) seedProjectMalariaTrafficBinding() {
	const flag = "project_malaria_traffic_binding_v1"
	if v, _, _ := s.m.pg.GetSetting(flag); v == "done" {
		return
	}
	if _, hasExplicit, _ := s.m.pg.GetSetting(settingAgentTrafficBinding); !hasExplicit {
		if err := s.m.pg.SetBool(settingAgentTrafficBinding, true); err != nil {
			log.Printf("[evidence] default agent_traffic_binding failed: %v", err)
			return
		}
	}
	_ = s.m.pg.AddAgentToToolBinding("reporter", []string{"list_findings"})
	_ = s.m.pg.SetSetting(flag, "done")
}

// notifyReporterForStandaloneFinding mirrors task-mode tool triggers when /chat
// agents (auto/pentest) persist a confirmed finding directly via report_finding.
func (s *Server) notifyReporterForStandaloneFinding(taskID int64, recorded *db.RecordedFinding, input db.RecordFindingInput) {
	if s == nil || s.m == nil || s.m.pg == nil || recorded == nil || recorded.FindingID <= 0 {
		return
	}
	triggers, err := s.m.pg.ListTriggersFor("reporter")
	if err != nil {
		return
	}
	var active *db.AgentTrigger
	for _, tr := range triggers {
		if tr != nil && tr.Enabled && tr.OnToolCall && containsFold(tr.ToolNames, "report_finding") {
			active = tr
			break
		}
	}
	if active == nil {
		return
	}
	var taskDesc, taskGoal string
	if taskID > 0 {
		if t, ok := s.m.Task(strconv.FormatInt(taskID, 10)); ok && t != nil {
			taskDesc, taskGoal = t.Description, t.Goal
		} else {
			_ = s.m.pg.QueryRow(`SELECT description, goal FROM tasks WHERE id=$1`, taskID).Scan(&taskDesc, &taskGoal)
		}
	}
	evPreview := strings.TrimSpace(input.Evidence)
	if len(evPreview) > 1500 {
		evPreview = evPreview[:1500] + "…"
	}
	targetHandle := recorded.NodeID
	if targetHandle <= 0 {
		targetHandle = recorded.FindingID
	}
	msg := active.ToolCallMessage + fmt.Sprintf(
		"\n\n[Triggered from /chat standalone report_finding]\nStandalone finding_id: %d\nExploration finding_node_id: %d\nTask ID: %d\nVulnClass: %s\nName: %s\nSeverity: %s\nSummary: %s\nEvidence: %s\nNote: If finding_node_id is 0, there is no exploration node — inspect traffic via get_finding_traffic(finding_id=%d), verify/bind matching HTTP traffic if auto-binding is on, and save the report with update_finding_report(finding_id=%d, report=..., evidence_version=..., poe_level=..., evidence_quotes=...).",
		recorded.FindingID, recorded.NodeID, taskID, input.VulnClass, input.Name, input.Severity, input.Summary, evPreview, recorded.FindingID, targetHandle,
	)
	title := fmt.Sprintf("Tool trigger · report_finding · finding#%d", recorded.FindingID)
	s.StartTriggeredRun("reporter", title, msg, taskID, true, taskDesc, taskGoal)
}
