package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/Autumn-27/artex/agent"
	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/intercept"
	"github.com/Autumn-27/artex/mcphttp"
	actool "github.com/Autumn-27/norma/tool"
)

func splitTargets(single string, list []string) []string {
	var raw []string
	if strings.TrimSpace(single) != "" {
		raw = append(raw, single)
	}
	raw = append(raw, list...)
	seen := map[string]bool{}
	var out []string
	for _, entry := range raw {
		for _, tok := range strings.FieldsFunc(entry, func(r rune) bool {
			return r == ',' || r == '\n' || r == '\r' || r == ';' || r == ' ' || r == '\t'
		}) {
			t := strings.TrimSpace(tok)
			if t == "" || seen[t] {
				continue
			}
			seen[t] = true
			out = append(out, t)
		}
	}
	return out
}

func appendUniqueStr(dst *[]string, seen map[string]bool, val string) {
	v := strings.TrimSpace(val)
	if v == "" || seen[v] {
		return
	}
	seen[v] = true
	*dst = append(*dst, v)
}

func buildTargetMeta(targets []string, extraScope, explicitCompany string) (companyName string, scopeLines []string, ssTargets []string, primary string) {
	seenScope := map[string]bool{}
	seenSS := map[string]bool{}
	var derivedCompany string

	for _, t := range targets {
		if primary == "" {
			primary = t
		}
		if _, _, err := net.ParseCIDR(t); err == nil {
			appendUniqueStr(&scopeLines, seenScope, t)
			appendUniqueStr(&ssTargets, seenSS, t)
			if derivedCompany == "" {
				derivedCompany = t
			}
			continue
		}
		if strings.Contains(t, "://") {
			if u, err := url.Parse(t); err == nil && u.Hostname() != "" {
				host := strings.ToLower(u.Hostname())
				root, _ := db.RootDomain(host)
				if derivedCompany == "" {
					if root != "" {
						derivedCompany = root
					} else {
						derivedCompany = host
					}
				}
				if root != "" {
					appendUniqueStr(&scopeLines, seenScope, root)
				}
				appendUniqueStr(&scopeLines, seenScope, host)
				appendUniqueStr(&ssTargets, seenSS, t)
				continue
			}
		}
		if _, host, _, ok := parseTarget(t); ok && host != "" {
			if net.ParseIP(host) != nil {
				appendUniqueStr(&scopeLines, seenScope, host)
				appendUniqueStr(&ssTargets, seenSS, host)
				if derivedCompany == "" {
					derivedCompany = host
				}
			} else {
				root, _ := db.RootDomain(host)
				if derivedCompany == "" {
					if root != "" {
						derivedCompany = root
					} else {
						derivedCompany = host
					}
				}
				if root != "" {
					appendUniqueStr(&scopeLines, seenScope, root)
				}
				appendUniqueStr(&scopeLines, seenScope, host)
				appendUniqueStr(&ssTargets, seenSS, host)
			}
			continue
		}
		appendUniqueStr(&scopeLines, seenScope, t)
		appendUniqueStr(&ssTargets, seenSS, t)
		if derivedCompany == "" {
			derivedCompany = t
		}
	}

	if strings.TrimSpace(extraScope) != "" {
		for _, line := range strings.FieldsFunc(extraScope, func(r rune) bool {
			return r == ',' || r == '\n' || r == '\r' || r == ';'
		}) {
			appendUniqueStr(&scopeLines, seenScope, line)
		}
	}

	companyName = strings.TrimSpace(explicitCompany)
	if companyName == "" {
		companyName = derivedCompany
	}
	return companyName, scopeLines, ssTargets, primary
}

func (s *Server) seedTargetAssets(as *db.AssetStore, targets []string, taskID int64) []int64 {
	if as == nil {
		return nil
	}
	seen := map[int64]bool{}
	var ids []int64
	addID := func(id int64) {
		if id > 0 && !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	for _, raw := range targets {
		if _, _, err := net.ParseCIDR(raw); err == nil {
			continue
		}
		if strings.Contains(raw, "://") {
			if u, err := url.Parse(raw); err == nil && u.Hostname() != "" {
				scheme := strings.ToLower(u.Scheme)
				if scheme == "http" || scheme == "https" {
					if id, err := as.UpsertHTTPService(db.UpsertHTTPServiceReq{URL: raw, TaskID: taskID}); err == nil {
						addID(id)
					}
					continue
				}
				raw = u.Hostname()
			}
		}
		scheme, host, port, ok := parseTarget(raw)
		if !ok || host == "" {
			continue
		}
		if net.ParseIP(host) != nil {
			if id, err := as.UpsertIP(db.UpsertIPReq{IP: host, TaskID: taskID}); err == nil {
				addID(id)
			}
			if port > 0 && (strings.Contains(raw, ":") || scheme == "http" || scheme == "https") {
				if id, err := as.UpsertHTTPService(db.UpsertHTTPServiceReq{
					URL:    fmt.Sprintf("%s://%s", scheme, net.JoinHostPort(host, strconv.Itoa(port))),
					IP:     host,
					TaskID: taskID,
				}); err == nil {
					addID(id)
				}
			}
			continue
		}
		if id, err := as.UpsertSubdomain(db.UpsertSubdomainReq{Domain: host, TaskID: taskID}); err == nil {
			addID(id)
		}
		if strings.Contains(raw, ":") && (scheme == "http" || scheme == "https") {
			if id, err := as.UpsertHTTPService(db.UpsertHTTPServiceReq{
				URL:    fmt.Sprintf("%s://%s:%d", scheme, host, port),
				TaskID: taskID,
			}); err == nil {
				addID(id)
			}
		}
	}
	return ids
}

func (s *Server) registerCompanyScopeAndAssets(
	targets []string,
	companyName string,
	explicitCompanyID int64,
	extraScope string,
	taskID int64,
	reason string,
) (companyID int64, finalCompany string, assetIDs []int64, err error) {
	as := s.assetStore()
	cs := s.companyStore()
	if as == nil || cs == nil {
		return 0, "", nil, fmt.Errorf("asset/company store unavailable")
	}
	derivedName, scopeLines, _, _ := buildTargetMeta(targets, extraScope, companyName)
	finalCompany = derivedName

	if explicitCompanyID > 0 {
		c, gerr := cs.GetCompany(explicitCompanyID)
		if gerr != nil || c == nil {
			return 0, "", nil, fmt.Errorf("company #%d not found", explicitCompanyID)
		}
		companyID = c.ID
		finalCompany = c.Name
	} else {
		if finalCompany == "" {
			return 0, "", nil, fmt.Errorf("company name or target is required")
		}
		companyID, err = cs.UpsertByName(finalCompany)
		if err != nil {
			return 0, "", nil, err
		}
	}
	if len(scopeLines) > 0 {
		if reason == "" {
			reason = "pipeline:" + finalCompany
		}
		cs.AddScope(companyID, scopeLines, reason)
	}
	assetIDs = s.seedTargetAssets(as, targets, taskID)
	_ = cs.RecomputeAttribution()
	if taskID > 0 && s.m.pg != nil {
		_, _ = s.m.pg.SyncTaskCompanyAssets(taskID)
	}
	return companyID, finalCompany, assetIDs, nil
}

func (s *Server) resolveInheritedGateRules(ctx context.Context) (*bool, []db.TaskInterceptRuleInput, error) {
	scope, ok := intercept.TargetScopeFromContext(ctx)
	if !ok || scope.Enabled == nil || !scope.Enabled() {
		return nil, nil, nil
	}
	on := true
	var blockRules []db.TaskInterceptRuleInput
	if callerID, err := strconv.ParseInt(scope.TaskID, 10, 64); err == nil && callerID > 0 {
		block, _, err := s.m.Assets().TaskInterceptRulesSplit(callerID)
		if err != nil {
			return nil, nil, fmt.Errorf("read the block rules of the calling task: %w", err)
		}
		for _, r := range block {
			blockRules = append(blockRules, db.TaskInterceptRuleInput{
				Enabled: r.Enabled, Action: r.Action, Kind: r.Kind, Pattern: r.Pattern, Note: r.Note,
			})
		}
	}
	return &on, blockRules, nil
}

func (s *Server) launchScopeSentryAssessment(ctx context.Context, projectName, ssTargetText, scanName string) (projID, taskID, nodeName, templateID string, warnings []string) {
	if strings.TrimSpace(ssTargetText) == "" {
		return "", "", "", "", []string{"ScopeSentry skipped: no valid targets extracted"}
	}
	ssCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()

	_, _ = s.ensureScopeSentryMCP(ssCtx)
	cl, err := s.scopeSentryClient(ssCtx)
	if err != nil {
		return "", "", "", "", []string{"ScopeSentry unreachable: " + err.Error()}
	}
	defer cl.Close()

	// Pick first online node (fallback to any registered node).
	for _, onlineOnly := range []bool{true, false} {
		if text, nerr := cl.Call(ssCtx, "list_nodes", map[string]any{"online_only": onlineOnly}); nerr == nil {
			var env struct {
				List []struct {
					Name  string `json:"name"`
					State string `json:"state"`
				} `json:"list"`
			}
			if json.Unmarshal([]byte(text), &env) == nil && len(env.List) > 0 {
				nodeName = env.List[0].Name
				break
			}
		}
	}
	if nodeName == "" {
		warnings = append(warnings, "ScopeSentry has no registered scanner nodes; created project only without starting scan task")
	}

	// Pick "default" scan template (fallback to first template).
	if text, terr := cl.Call(ssCtx, "list_scan_templates", map[string]any{"pageIndex": 1, "pageSize": 20}); terr == nil {
		var env struct {
			List []struct {
				ID   string `json:"id"`
				Name string `json:"name"`
			} `json:"list"`
		}
		if json.Unmarshal([]byte(text), &env) == nil && len(env.List) > 0 {
			templateID = env.List[0].ID
			for _, tpl := range env.List {
				if strings.EqualFold(strings.TrimSpace(tpl.Name), "default") {
					templateID = tpl.ID
					break
				}
			}
		}
	}

	projArgs := map[string]any{
		"name":    projectName,
		"target":  ssTargetText,
		"tag":     "artex-pipeline",
		"allNode": true,
	}
	if templateID != "" {
		projArgs["template"] = templateID
	}
	if nodeName != "" {
		projArgs["node"] = []string{nodeName}
	}
	if text, perr := cl.Call(ssCtx, "create_project", projArgs); perr != nil {
		warnings = append(warnings, "ScopeSentry create_project failed: "+perr.Error())
		return "", "", nodeName, templateID, warnings
	} else {
		var resp struct {
			ID      string `json:"id"`
			Message string `json:"message"`
		}
		if json.Unmarshal([]byte(text), &resp) == nil {
			projID = resp.ID
		}
	}

	if nodeName == "" {
		return projID, "", nodeName, templateID, warnings
	}

	uniqueScanName := fmt.Sprintf("%s-%s", strings.TrimSpace(scanName), time.Now().UTC().Format("0102-150405"))
	scanArgs := map[string]any{
		"name":    uniqueScanName,
		"target":  ssTargetText,
		"node":    []string{nodeName},
		"allNode": true,
	}
	if templateID != "" {
		scanArgs["template"] = templateID
	}
	if projID != "" {
		scanArgs["project"] = []string{projID}
		scanArgs["bindProject"] = projID
		scanArgs["targetSource"] = "project"
	} else {
		scanArgs["targetSource"] = "general"
	}
	if text, serr := cl.Call(ssCtx, "create_scan_task", scanArgs); serr != nil {
		warnings = append(warnings, "ScopeSentry create_scan_task failed: "+serr.Error())
	} else {
		var resp struct {
			ID string `json:"id"`
		}
		if json.Unmarshal([]byte(text), &resp) == nil {
			taskID = resp.ID
		}
	}
	return projID, taskID, nodeName, templateID, warnings
}

func (s *Server) pushMemoryObservation(ctx context.Context, entityName, entityType string, observations []string) {
	if strings.TrimSpace(entityName) == "" || len(observations) == 0 {
		return
	}
	memURL := strings.TrimSpace(os.Getenv("MEMORY_MCP_URL"))
	if memURL == "" {
		memURL = "http://memory-mcp:8002/mcp"
	}
	mctx, cancel := context.WithTimeout(ctx, 2500*time.Millisecond)
	defer cancel()
	cl, err := mcphttp.New(mctx, "memory", memURL, nil, false, 3)
	if err != nil {
		return
	}
	defer cl.Close()
	_, _ = cl.Call(mctx, "memory_add", map[string]any{
		"name":         entityName,
		"entity_type":  entityType,
		"observations": observations,
	})
}

type targetAssessmentParams struct {
	Target             string
	Targets            []string
	Company            string
	CompanyID          int64
	Scope              string
	Description        string
	Goal               string
	LaunchScopeSentry  bool
	LaunchArtexTask    bool
	PauseArtexTask     bool
	SeedFirstIntent    bool
	AttachExisting     bool
	EnsureConversation bool
	ConversationID     int64
	ConversationAgent  string
	WorkspacePath      string
	LLMProfileID       int64
}

type targetAssessmentResult struct {
	CompanyID            int64             `json:"company_id"`
	CompanyName          string            `json:"company_name"`
	Scope                []string          `json:"scope,omitempty"`
	AssetIDs             []int64           `json:"asset_ids,omitempty"`
	TaskAssetsLinked     int64             `json:"task_assets_linked"`
	ScopeSentryProjectID string            `json:"scopesentry_project_id,omitempty"`
	ScopeSentryTaskID    string            `json:"scopesentry_task_id,omitempty"`
	ScopeSentryNode      string            `json:"scopesentry_node,omitempty"`
	ScopeSentryTemplate  string            `json:"scopesentry_template,omitempty"`
	TaskID               int64             `json:"task_id"`
	ConversationID       int64             `json:"conversation_id,omitempty"`
	AlreadyOnboarded     bool              `json:"already_onboarded,omitempty"`
	Routes               map[string]string `json:"routes"`
	Warnings             []string          `json:"warnings,omitempty"`
}

func targetHostKey(raw string) string {
	s := strings.TrimSpace(raw)
	if s == "" {
		return ""
	}
	if strings.Contains(s, "://") {
		if u, err := url.Parse(s); err == nil && u.Hostname() != "" {
			return strings.ToLower(u.Hostname())
		}
	}
	if _, host, _, ok := parseTarget(s); ok && host != "" {
		return strings.ToLower(host)
	}
	return strings.ToLower(s)
}

func sameTargetOrRoot(a, b string) bool {
	ha, hb := targetHostKey(a), targetHostKey(b)
	if ha == "" || hb == "" {
		return false
	}
	if ha == hb {
		return true
	}
	ra, _ := db.RootDomain(ha)
	rb, _ := db.RootDomain(hb)
	return ra != "" && ra == rb
}

func isPlatformSelfURL(raw string, host string, port int) bool {
	lh := strings.ToLower(host)
	isLocal := lh == "127.0.0.1" || lh == "localhost" || lh == "::1" || lh == "host.docker.internal"
	if !isLocal {
		return false
	}
	switch port {
	case 3000, 3080, 4000, 5432, 5433, 8001, 8002, 8003, 8004, 8007, 8009, 8082, 8787, 8788, 9000:
		return true
	}
	if strings.Contains(raw, "://") {
		if u, err := url.Parse(raw); err == nil {
			p := u.Port()
			if p == "3000" || p == "8787" || p == "3080" || p == "8082" {
				return true
			}
			// Default HTTP without explicit lab port on localhost UI paths.
			if p == "" && (strings.HasPrefix(u.Path, "/function/") || strings.HasPrefix(u.Path, "/system/") || strings.HasPrefix(u.Path, "/scopesentry/")) {
				return true
			}
		}
	}
	return false
}

func isReferenceHost(host string) bool {
	h := strings.ToLower(strings.TrimSuffix(strings.TrimSpace(host), "."))
	switch h {
	case "github.com", "gist.github.com", "raw.githubusercontent.com",
		"nvd.nist.gov", "cve.org", "www.cve.org", "cve.mitre.org", "cwe.mitre.org",
		"owasp.org", "www.owasp.org", "portswigger.net", "exploit-db.com", "www.exploit-db.com",
		"hackerone.com", "developer.mozilla.org", "stackoverflow.com",
		"google.com", "www.google.com", "bing.com", "duckduckgo.com", "wikipedia.org", "en.wikipedia.org":
		return true
	}
	return false
}

// extractUnlinkedChatTargets returns target URLs/hosts/IPs found in an operator
// chat message that are not already tracked in this conversation's links.
func (s *Server) extractUnlinkedChatTargets(convID int64, userMsg string) []string {
	targets, urls := intercept.ExtractTextTargets(userMsg)
	if len(targets) == 0 && len(urls) == 0 {
		return nil
	}
	var existingLinks []db.ConversationLink
	if convID > 0 && s.m.pg != nil {
		existingLinks, _ = s.m.pg.ListConversationLinks(convID)
	}
	alreadyLinked := func(candidate string) bool {
		for _, l := range existingLinks {
			if sameTargetOrRoot(l.Target, candidate) {
				return true
			}
		}
		return false
	}

	var out []string
	seenHost := map[string]bool{}
	for _, rawURL := range urls {
		u, err := url.Parse(strings.TrimSpace(rawURL))
		if err != nil || u.Hostname() == "" {
			continue
		}
		scheme := strings.ToLower(u.Scheme)
		if scheme != "http" && scheme != "https" {
			continue
		}
		port := 0
		if p := u.Port(); p != "" {
			port, _ = strconv.Atoi(p)
		}
		host := strings.ToLower(u.Hostname())
		if isPlatformSelfURL(rawURL, host, port) || isReferenceHost(host) || seenHost[host] || alreadyLinked(rawURL) {
			continue
		}
		seenHost[host] = true
		out = append(out, strings.TrimSpace(rawURL))
	}
	for _, t := range targets {
		host := strings.ToLower(t.Host)
		if host == "" || seenHost[host] || isPlatformSelfURL("", host, t.Port) || isReferenceHost(host) || alreadyLinked(host) {
			continue
		}
		seenHost[host] = true
		val := t.Host
		if t.Port > 0 && !strings.Contains(val, "/") {
			val = net.JoinHostPort(t.Host, strconv.Itoa(t.Port))
		}
		out = append(out, val)
	}
	return out
}

func (s *Server) findMatchingActiveTaskLinkByTarget(primaryTarget string) *db.ConversationLink {
	if s == nil || s.m == nil || s.m.pg == nil || strings.TrimSpace(primaryTarget) == "" {
		return nil
	}
	rows, qerr := s.m.pg.Query(`
		SELECT l.conversation_id, l.task_id, COALESCE(l.company_id, 0), l.scopesentry_project_id, l.scopesentry_task_id, l.target
		FROM conversation_links l
		JOIN tasks t ON t.id = l.task_id
		WHERE l.task_id IS NOT NULL AND t.deleted_at IS NULL
		ORDER BY l.created_at DESC, l.id DESC
		LIMIT 50`)
	if qerr != nil {
		return nil
	}
	defer rows.Close()
	for rows.Next() {
		var row db.ConversationLink
		var rtid, rcid int64
		if scanErr := rows.Scan(&row.ConversationID, &rtid, &rcid, &row.ScopeSentryProjectID, &row.ScopeSentryTaskID, &row.Target); scanErr != nil {
			continue
		}
		if !sameTargetOrRoot(row.Target, primaryTarget) {
			continue
		}
		if t, ok := s.m.Task(strconv.FormatInt(rtid, 10)); ok && t != nil && !isTerminalStatus(s.deriveTaskStatus(t)) {
			row.TaskID = &rtid
			if rcid > 0 {
				row.CompanyID = &rcid
			}
			return &row
		}
	}
	return nil
}

func (s *Server) runTargetAssessment(ctx context.Context, params targetAssessmentParams) (*targetAssessmentResult, error) {
	targets := splitTargets(params.Target, params.Targets)
	if len(targets) == 0 {
		return nil, fmt.Errorf("target or targets is required")
	}

	derivedName, scopeLines, ssTargets, primaryTarget := buildTargetMeta(targets, params.Scope, params.Company)
	convID := intercept.ConvIDFromContext(ctx)
	if convID == 0 && params.ConversationID > 0 {
		convID = params.ConversationID
	}

	var existingLink *db.ConversationLink
	if convID > 0 && s.m.pg != nil {
		if links, err := s.m.pg.ListConversationLinks(convID); err == nil {
			for i := range links {
				if sameTargetOrRoot(links[i].Target, primaryTarget) {
					l := links[i]
					existingLink = &l
					break
				}
			}
		}
	} else if convID == 0 && params.AttachExisting && s.m.pg != nil {
		existingLink = s.findMatchingActiveTaskLinkByTarget(primaryTarget)
	}

	// If this conversation (or active shared workspace) already onboarded the same target and satisfies task creation,
	// return the existing links rather than duplicating companies, tasks, and scans.
	if existingLink != nil && (!params.LaunchArtexTask || (existingLink.TaskID != nil && *existingLink.TaskID > 0)) {
		var cid, tid, linkedAssets int64
		if existingLink.CompanyID != nil {
			cid = *existingLink.CompanyID
		}
		if existingLink.TaskID != nil {
			tid = *existingLink.TaskID
		}
		if tid > 0 && s.assetStore() != nil {
			if byType, cerr := s.assetStore().CountsByTypeForTask(tid); cerr == nil {
				for _, cnt := range byType {
					linkedAssets += int64(cnt)
				}
			}
		}
		cname := derivedName
		if cid > 0 && s.companyStore() != nil {
			if c, cerr := s.companyStore().GetCompany(cid); cerr == nil && c != nil {
				cname = c.Name
			}
		}
		linkedConv := existingLink.ConversationID
		if linkedConv == 0 && tid > 0 && params.EnsureConversation {
			linkedConv, _, _ = s.ensureLinkedConversation(tid, primaryTarget, existingLink.ScopeSentryProjectID, existingLink.ScopeSentryTaskID, cid, params.ConversationAgent)
		}
		if tid > 0 && (params.EnsureConversation || linkedConv > 0) {
			_ = s.saveSharedContext(sharedWorkspaceContext{
				TaskID:         tid,
				ConversationID: linkedConv,
				Target:         primaryTarget,
				WorkspacePath:  params.WorkspacePath,
				Source:         "start_target_assessment",
			})
		}
		routes := map[string]string{
			"assets":      "/function/assets",
			"tasks":       fmt.Sprintf("/function/tasks/detail?id=%d", tid),
			"scopesentry": "/scopesentry/asset-information/index",
			"findings":    "/function/findings",
		}
		if linkedConv > 0 {
			routes["chat"] = fmt.Sprintf("/chat?c=%d", linkedConv)
		}
		return &targetAssessmentResult{
			CompanyID:            cid,
			CompanyName:          cname,
			Scope:                scopeLines,
			TaskAssetsLinked:     linkedAssets,
			ScopeSentryProjectID: existingLink.ScopeSentryProjectID,
			ScopeSentryTaskID:    existingLink.ScopeSentryTaskID,
			TaskID:               tid,
			ConversationID:       linkedConv,
			AlreadyOnboarded:     true,
			Routes:               routes,
		}, nil
	}

	explicitCID := params.CompanyID
	if explicitCID == 0 && existingLink != nil && existingLink.CompanyID != nil {
		explicitCID = *existingLink.CompanyID
	}

	companyID, finalCompany, assetIDs, err := s.registerCompanyScopeAndAssets(
		targets, derivedName, explicitCID, params.Scope, 0, "assessment:"+primaryTarget,
	)
	if err != nil {
		return nil, err
	}

	var warnings []string
	var ssProjectID, ssTaskID, ssNode, ssTemplate string
	if existingLink != nil && existingLink.ScopeSentryProjectID != "" {
		ssProjectID = existingLink.ScopeSentryProjectID
		ssTaskID = existingLink.ScopeSentryTaskID
	} else if params.LaunchScopeSentry {
		ssTargetText := strings.Join(ssTargets, "\n")
		ssProjectID, ssTaskID, ssNode, ssTemplate, warnings = s.launchScopeSentryAssessment(
			ctx, finalCompany, ssTargetText, "artex-"+finalCompany,
		)
	}

	var artexTaskID int64
	var linkedAssetCount int64
	if params.LaunchArtexTask {
		var llmIDs []int64
		if params.LLMProfileID > 0 {
			if _, ok := s.loadProfileConfig(params.LLMProfileID); !ok {
				return nil, fmt.Errorf("LLM profile #%d not found or not usable", params.LLMProfileID)
			}
			llmIDs = []int64{params.LLMProfileID}
		}
		gate, blockRules, gerr := s.resolveInheritedGateRules(ctx)
		if gerr != nil {
			return nil, gerr
		}
		desc := strings.TrimSpace(params.Description)
		if desc == "" {
			desc = fmt.Sprintf("Assessment: %s (%s)", finalCompany, primaryTarget)
		}
		goal := strings.TrimSpace(params.Goal)
		if goal == "" {
			goal = fmt.Sprintf("Assess attack surface, exposed services, configuration weaknesses, and exploitable vulnerabilities on %s (%s). Register discovered assets and confirmed findings with evidence.", strings.Join(targets, ", "), strings.Join(scopeLines, ", "))
		}
		t, terr := s.m.CreateTaskWithOptions(desc, goal, db.TaskCreateOptions{
			Name:           desc,
			CompanyIDs:     []int64{companyID},
			LLMProfileIDs:  llmIDs,
			InterceptRules: blockRules,
			TargetGate:     gate,
		})
		if terr != nil {
			return nil, fmt.Errorf("create ARTEX task failed: %w", terr)
		}
		artexTaskID, _ = strconv.ParseInt(t.ID, 10, 64)
		if artexTaskID > 0 {
			extraIDs := s.seedTargetAssets(s.assetStore(), targets, artexTaskID)
			if len(extraIDs) > 0 {
				assetIDs = extraIDs
			}
			if cs := s.companyStore(); cs != nil {
				_ = cs.RecomputeAttribution()
			}
			_, _ = s.m.pg.SyncTaskCompanyAssets(artexTaskID)
			if as := s.assetStore(); as != nil {
				if byType, cerr := as.CountsByTypeForTask(artexTaskID); cerr == nil {
					for _, cnt := range byType {
						linkedAssetCount += int64(cnt)
					}
				}
			}
		}
		if params.PauseArtexTask {
			s.seed(t, desc+" "+goal)
			s.engine.Pause(t.ID, agent.AbortPausedByUser)
			_ = s.m.ApplyTaskPause(t.ID)
		} else {
			s.launchTask(t, desc+" "+goal, params.SeedFirstIntent)
		}
	}

	if convID > 0 && s.m.pg != nil {
		var tidPtr *int64
		if artexTaskID > 0 {
			tidPtr = &artexTaskID
			// Upgrade an earlier taskless pentest/chat link instead of leaving two rows.
			if existingLink != nil && (existingLink.TaskID == nil || *existingLink.TaskID <= 0) {
				_, _ = s.m.pg.Exec(`DELETE FROM conversation_links WHERE id=$1 AND task_id IS NULL`, existingLink.ID)
			}
		}
		cid := companyID
		if lerr := s.m.pg.UpsertConversationLink(db.ConversationLink{
			ConversationID:       convID,
			TaskID:               tidPtr,
			CompanyID:            &cid,
			ScopeSentryProjectID: ssProjectID,
			ScopeSentryTaskID:    ssTaskID,
			Target:               primaryTarget,
		}); lerr != nil {
			log.Printf("[pipeline] upsert conversation link failed (conv=%d): %v", convID, lerr)
		}
	} else if convID == 0 && artexTaskID > 0 && params.EnsureConversation && s.m.pg != nil {
		if cid, _, cerr := s.ensureLinkedConversation(artexTaskID, primaryTarget, ssProjectID, ssTaskID, companyID, params.ConversationAgent); cerr == nil {
			convID = cid
		}
	}

	if artexTaskID > 0 && (convID > 0 || params.EnsureConversation) {
		_ = s.saveSharedContext(sharedWorkspaceContext{
			TaskID:         artexTaskID,
			ConversationID: convID,
			Target:         primaryTarget,
			WorkspacePath:  params.WorkspacePath,
			Source:         "start_target_assessment",
		})
	}

	go s.pushMemoryObservation(context.Background(), finalCompany, "target_organization", []string{
		fmt.Sprintf("primary_target=%s company_id=%d scopes=%s", primaryTarget, companyID, strings.Join(scopeLines, ",")),
		fmt.Sprintf("scopesentry_project_id=%s scopesentry_task_id=%s artex_task_id=%d", ssProjectID, ssTaskID, artexTaskID),
	})

	routes := map[string]string{
		"assets":      "/function/assets",
		"tasks":       fmt.Sprintf("/function/tasks/detail?id=%d", artexTaskID),
		"scopesentry": "/scopesentry/asset-information/index",
		"findings":    "/function/findings",
	}
	if convID > 0 {
		routes["chat"] = fmt.Sprintf("/chat?c=%d", convID)
	}

	return &targetAssessmentResult{
		CompanyID:            companyID,
		CompanyName:          finalCompany,
		Scope:                scopeLines,
		AssetIDs:             assetIDs,
		TaskAssetsLinked:     linkedAssetCount,
		ScopeSentryProjectID: ssProjectID,
		ScopeSentryTaskID:    ssTaskID,
		ScopeSentryNode:      ssNode,
		ScopeSentryTemplate:  ssTemplate,
		TaskID:               artexTaskID,
		ConversationID:       convID,
		Routes:               routes,
		Warnings:             warnings,
	}, nil
}

type autoPipelineResult struct {
	TaskID           int64             `json:"task_id"`
	ConversationID   int64             `json:"conversation_id,omitempty"`
	Target           string            `json:"target,omitempty"`
	WorkspacePath    string            `json:"workspace_path,omitempty"`
	Created          bool              `json:"created"`
	AlreadyOnboarded bool              `json:"already_onboarded,omitempty"`
	Routes           map[string]string `json:"routes,omitempty"`
}

func firstWorkspacePathFromAttachments(atts []chatAttachment) string {
	for _, a := range atts {
		p := strings.TrimSpace(a.Path)
		if strings.HasPrefix(p, sharedWorkspaceRoot) {
			return p
		}
		abs := strings.TrimSpace(a.Abs)
		if strings.HasPrefix(abs, sharedWorkspaceRoot) {
			return abs
		}
	}
	return ""
}

// ensureAutoPipeline deterministically creates or attaches an ARTEX Mission + linked
// conversation for ANY actionable prompt — whether it contains URLs/IPs/domains OR
// attached files / shared /workspace folders — so the operator never has to manually
// instruct the model to "create task".
func (s *Server) ensureAutoPipeline(ctx context.Context, prompt, workspacePath string, convID int64, agentKey string, atts []chatAttachment, allowPromptOnly bool) (*autoPipelineResult, error) {
	if s == nil || s.m == nil || s.m.pg == nil {
		return nil, fmt.Errorf("server unavailable")
	}
	wsPath := strings.TrimSpace(workspacePath)
	if wsPath == "" {
		wsPath = firstWorkspacePathFromAttachments(atts)
	}
	if wsPath == "" {
		cur := s.loadSharedContext()
		wsPath = strings.TrimSpace(cur.WorkspacePath)
	}

	targets := s.extractUnlinkedChatTargets(convID, prompt)
	goal := strings.TrimSpace(prompt)
	if goal == "" && len(atts) > 0 {
		goal = fmt.Sprintf("Inspect and audit attached artifact(s): %s", atts[0].Name)
	}
	if len(goal) > 450 {
		goal = goal[:450] + "..."
	}

	if len(targets) > 0 {
		runWorkers := agentKey == "auto"
		res, err := s.runTargetAssessment(ctx, targetAssessmentParams{
			Targets:            targets,
			Goal:               fmt.Sprintf("Assess target(s) %s per operator request: %s", strings.Join(targets, ", "), goal),
			LaunchScopeSentry:  true,
			LaunchArtexTask:    true,
			PauseArtexTask:     !runWorkers,
			SeedFirstIntent:    runWorkers,
			AttachExisting:     convID == 0,
			EnsureConversation: true,
			ConversationID:     convID,
			ConversationAgent:  agentKey,
			WorkspacePath:      wsPath,
		})
		if err != nil {
			return nil, err
		}
		return &autoPipelineResult{
			TaskID:           res.TaskID,
			ConversationID:   res.ConversationID,
			Target:           strings.Join(targets, ", "),
			WorkspacePath:    wsPath,
			Created:          !res.AlreadyOnboarded,
			AlreadyOnboarded: res.AlreadyOnboarded,
			Routes:           res.Routes,
		}, nil
	}

	// File / Folder / Workspace-only audit pipeline: if the conversation already has a task, reuse it.
	if convID > 0 {
		if links, err := s.m.pg.ListConversationLinks(convID); err == nil {
			for _, l := range links {
				if l.TaskID != nil && *l.TaskID > 0 {
					if _, ok := s.m.Task(strconv.FormatInt(*l.TaskID, 10)); ok {
						_ = s.saveSharedContext(sharedWorkspaceContext{
							TaskID:         *l.TaskID,
							ConversationID: convID,
							Target:         l.Target,
							WorkspacePath:  wsPath,
							Source:         "auto_pipeline",
						})
						return &autoPipelineResult{
							TaskID:           *l.TaskID,
							ConversationID:   convID,
							Target:           l.Target,
							WorkspacePath:    wsPath,
							Created:          false,
							AlreadyOnboarded: true,
						}, nil
					}
				}
			}
		}
	}

	if len(atts) == 0 && wsPath == "" && !allowPromptOnly {
		return nil, nil
	}

	label := ""
	if wsPath != "" {
		label = filepath.Base(wsPath)
	} else if len(atts) > 0 {
		label = strings.TrimSpace(atts[0].Name)
	} else {
		label = firstLine(goal, 48)
	}
	if label == "" || label == "." || label == "/" {
		label = "workspace"
	}

	title := fmt.Sprintf("Audit: %s", label)
	if len(title) > 96 {
		title = title[:96]
	}
	fullGoal := goal
	if wsPath != "" {
		fullGoal = fmt.Sprintf("%s (Shared Workspace: %s)", goal, wsPath)
	}
	t, terr := s.m.CreateTaskWithOptions(title, fullGoal, db.TaskCreateOptions{
		Name: title,
	})
	if terr != nil {
		return nil, fmt.Errorf("create ARTEX audit task failed: %w", terr)
	}
	tid, _ := strconv.ParseInt(t.ID, 10, 64)
	s.seed(t, title+" "+fullGoal)
	// Keep background workers paused so Graph Chat / Deep Agent IDE runs directly without double GPU contention.
	s.engine.Pause(t.ID, agent.AbortPausedByUser)
	_ = s.m.ApplyTaskPause(t.ID)

	targetLabel := wsPath
	if targetLabel == "" {
		targetLabel = label
	}
	if convID > 0 {
		_ = s.m.pg.UpsertConversationLink(db.ConversationLink{
			ConversationID: convID,
			TaskID:         &tid,
			Target:         targetLabel,
		})
	} else {
		if cid, _, cerr := s.ensureLinkedConversation(tid, targetLabel, "", "", 0, agentKey); cerr == nil {
			convID = cid
		}
	}

	_ = s.saveSharedContext(sharedWorkspaceContext{
		TaskID:         tid,
		ConversationID: convID,
		Target:         targetLabel,
		WorkspacePath:  wsPath,
		Source:         "auto_pipeline",
	})

	routes := map[string]string{
		"tasks":    fmt.Sprintf("/function/tasks/detail?id=%d", tid),
		"findings": "/function/findings",
	}
	if convID > 0 {
		routes["chat"] = fmt.Sprintf("/chat?c=%d", convID)
	}
	return &autoPipelineResult{
		TaskID:         tid,
		ConversationID: convID,
		Target:         targetLabel,
		WorkspacePath:  wsPath,
		Created:        true,
		Routes:         routes,
	}, nil
}

// maybeAutoOnboardChatTurn deterministically registers targets/assets/tasks for
// human /chat messages on auto/pentest (both URL/IP targets AND uploaded folders/files)
// so pipeline data never depends on the LLM remembering to create a task first.
func (s *Server) maybeAutoOnboardChatTurn(ctx context.Context, c *db.Conversation, userMsg string, atts []chatAttachment) string {
	if s == nil || s.m == nil || s.m.pg == nil || c == nil {
		return ""
	}
	if c.AgentKey != "auto" && c.AgentKey != "pentest" {
		return ""
	}
	res, err := s.ensureAutoPipeline(ctx, userMsg, "", c.ID, c.AgentKey, atts, false)
	if err != nil {
		log.Printf("[pipeline] auto-onboard chat conv=%d failed: %v", c.ID, err)
		return ""
	}
	if res == nil || res.AlreadyOnboarded || res.TaskID <= 0 {
		return ""
	}
	summary := fmt.Sprintf("[Auto-Pipeline] Created ARTEX Mission Task #%d (%s)", res.TaskID, res.Target)
	if res.WorkspacePath != "" {
		summary += fmt.Sprintf(" · Shared Folder: %s", res.WorkspacePath)
	}
	detailRaw, _ := json.Marshal(res)
	_, _ = s.m.pg.AppendConvActivity(c.ID, db.Activity{
		Worker:  c.AgentKey,
		Kind:    "text",
		Summary: summary,
		Detail:  string(detailRaw),
	})
	return fmt.Sprintf(
		"[System Auto-Onboard Pipeline] Mission Task #%d is ALREADY created and linked for %s:\n%s\n"+
			"End-to-End Pipeline Instructions:\n"+
			"1. Do NOT ask the user to create a task or call start_target_assessment again for this target.\n"+
			"2. Inspect the target or attached files/shared workspace thoroughly using Read/Bash/Skill/MCP tools; record confirmed technical observations via record_fact and vulnerabilities via report_finding on Task #%d.\n"+
			"3. When producing a formal/detailed report (or when the user requested a full end-to-end report), call generate_task_report(task_id=\"%d\") so Report Studio launches a persistent background job filling every template section & table via the Completeness Gate and immediately returns job_id + report_tab_url without blocking.\n\n",
		res.TaskID, res.Target, string(detailRaw), res.TaskID, res.TaskID,
	)
}

func reportStudioBaseURL() string {
	if u := strings.TrimSpace(os.Getenv("REPORT_STUDIO_URL")); u != "" {
		return strings.TrimRight(u, "/")
	}
	return "http://host.docker.internal:8010/api/model-studio/reports"
}

func (s *Server) toolListReportTemplates() actool.CoreTool {
	return roTool(
		"list_report_templates",
		"List all available Report Studio templates (.docx and .md, including built-in NCSA TLP:AMBER, Full Pentest, Script Forensics, and custom user-uploaded templates) along with their extracted required sections and tables.",
		objSchema(map[string]any{}),
		func(ctx context.Context, _ json.RawMessage) (actool.Result, error) {
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, reportStudioBaseURL()+"/templates", nil)
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			cl := &http.Client{Timeout: 15 * time.Second}
			resp, err := cl.Do(req)
			if err != nil {
				return actool.Errorf("cannot reach Report Studio API: " + err.Error()), nil
			}
			defer resp.Body.Close()
			raw, _ := io.ReadAll(resp.Body)
			if resp.StatusCode >= 400 {
				return actool.Errorf(fmt.Sprintf("Report Studio HTTP %d: %s", resp.StatusCode, string(raw))), nil
			}
			return actool.Text(string(raw)), nil
		},
	)
}

func (s *Server) toolGenerateTaskReport() actool.CoreTool {
	return wrTool(
		"generate_task_report",
		"Launch a deep, template-driven Word (.docx) and Markdown (.md) technical report generation job for an ARTEX Mission Task via Report Studio's multi-pass Section-by-Section Completeness Gate. Runs asynchronously on the backend by default (wait=false) so it returns immediately with job_id and report_tab_url (/function/tasks/detail?id=<tid>&tab=report) without hitting tool/turn timeouts, and automatically deduplicates if a job for this task is already running.",
		objSchema(map[string]any{
			"task_id":        strParam("optional ARTEX task id (defaults to the current conversation's linked task or active shared task)"),
			"template_id":    strParam("optional template id from list_report_templates (defaults to the user's default template)"),
			"model":          strParam("optional model alias to write sections (default: orchestrator)"),
			"workspace_path": strParam("optional shared /workspace/... folder path to include per-file inventory in the report"),
			"extra_notes":    strParam("optional focus notes or key highlights to emphasize in the report"),
			"title":          strParam("optional custom report title"),
			"wait":           map[string]any{"type": "boolean", "description": "optional: wait synchronously until generation completes (default false; keep false to avoid context deadline exceeded)"},
		}),
		func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
			var a struct {
				TaskID        json.RawMessage `json:"task_id"`
				TemplateID    string          `json:"template_id"`
				Model         string          `json:"model"`
				WorkspacePath string          `json:"workspace_path"`
				ExtraNotes    string          `json:"extra_notes"`
				Title         string          `json:"title"`
				Wait          bool            `json:"wait"`
			}
			_ = json.Unmarshal(in, &a)

			tid := parseProfileID(a.TaskID)
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
			active := s.loadSharedContext()
			if tid <= 0 {
				tid = active.TaskID
			}
			wsPath := strings.TrimSpace(a.WorkspacePath)
			if wsPath == "" {
				wsPath = active.WorkspacePath
			}

			payload, _ := json.Marshal(map[string]any{
				"task_id":        tid,
				"template_id":    strings.TrimSpace(a.TemplateID),
				"model":          strings.TrimSpace(a.Model),
				"workspace_path": wsPath,
				"extra_notes":    strings.TrimSpace(a.ExtraNotes),
				"title":          strings.TrimSpace(a.Title),
				"wait":           a.Wait,
			})

			// Async dispatch (default) uses a detached short timeout so even near-end-of-turn
			// wrap-up calls succeed cleanly in <1s without inheriting an expiring turn ctx.
			var reqCtx context.Context
			var cancel context.CancelFunc
			httpTimeout := 25 * time.Second
			if a.Wait {
				reqCtx, cancel = context.WithTimeout(ctx, 10*time.Minute)
				httpTimeout = 10 * time.Minute
			} else {
				reqCtx, cancel = context.WithTimeout(context.Background(), 25*time.Second)
			}
			defer cancel()
			req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, reportStudioBaseURL()+"/generate", bytes.NewReader(payload))
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			req.Header.Set("Content-Type", "application/json")
			cl := &http.Client{Timeout: httpTimeout}
			resp, err := cl.Do(req)
			if err != nil {
				return actool.Errorf("Report Studio generate failed: " + err.Error()), nil
			}
			defer resp.Body.Close()
			raw, _ := io.ReadAll(resp.Body)
			if resp.StatusCode >= 400 {
				return actool.Errorf(fmt.Sprintf("Report Studio HTTP %d: %s", resp.StatusCode, string(raw))), nil
			}
			var parsed struct {
				OK     bool           `json:"ok"`
				Error  string         `json:"error"`
				JobID  string         `json:"job_id"`
				Reused bool           `json:"reused"`
				Job    map[string]any `json:"job"`
				Report map[string]any `json:"report"`
			}
			if json.Unmarshal(raw, &parsed) == nil && parsed.OK {
				if parsed.Report != nil {
					return jsonResult(map[string]any{
						"ok":                true,
						"status":            "completed",
						"task_id":           parsed.Report["task_id"],
						"report_id":         parsed.Report["id"],
						"title":             parsed.Report["title"],
						"template_name":     parsed.Report["template_name"],
						"stats":             parsed.Report["stats"],
						"download_docx_url": parsed.Report["download_docx_url"],
						"download_md_url":   parsed.Report["download_md_url"],
						"report_tab_url":    fmt.Sprintf("/function/tasks/detail?id=%d&tab=report", tid),
						"note":              "Report generated via Completeness Gate. Present both download_docx_url and download_md_url as clickable links to the operator.",
					})
				}
				if parsed.JobID != "" {
					status := "queued"
					stage := ""
					if parsed.Job != nil {
						if st, ok := parsed.Job["status"].(string); ok && st != "" {
							status = st
						}
						if sg, ok := parsed.Job["stage"].(string); ok {
							stage = sg
						}
					}
					return jsonResult(map[string]any{
						"ok":             true,
						"status":         status,
						"reused":         parsed.Reused,
						"task_id":        tid,
						"job_id":         parsed.JobID,
						"stage":          stage,
						"report_tab_url": fmt.Sprintf("/function/tasks/detail?id=%d&tab=report", tid),
						"status_url":     fmt.Sprintf("/model-studio-api/reports/job?job_id=%s", parsed.JobID),
						"note":           "Report Studio background job started on the backend. It continues independently after this turn finishes — tell the operator to track live progress and download .docx/.md in the Report tab (report_tab_url).",
					})
				}
			}
			return actool.Text(string(raw)), nil
		},
	)
}

func (s *Server) toolStartTargetAssessment() actool.CoreTool {
	return wrTool(
		"start_target_assessment",
		"Unified end-to-end target onboarding and assessment launcher. Automatically performs in one flow: "+
			"(1) Company & Scope creation/update (companies + company_scope), "+
			"(2) Initial Assets & HTTP Services registration (assets), "+
			"(3) ScopeSentry ASM project creation & node/template scan launch (create_project + create_scan_task), "+
			"(4) ARTEX Autonomous Task & Exploration Graph creation bound to the company scope (spawn_task), "+
			"(5) Conversation linkage so the Chat Pipeline Bar, Target Assets & Scope, Recon Inventory, Tasks & Graph, and Findings stay continuously connected.",
		objSchema(map[string]any{
			"target":             strParam("single target URL, domain, IP, or CIDR (may be combined with targets)"),
			"targets":            map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "list of target URLs, domains, IPs, or CIDRs"},
			"company":            strParam("optional: organization/project name (auto-derived from root domain/target when omitted)"),
			"company_id":         map[string]any{"type": "integer", "description": "optional: existing company id to attach scope/assets to"},
			"scope":              strParam("optional: extra scope rules (domains/IPs/CIDRs, newline or comma separated)"),
			"description":        strParam("optional: short title for the assessment task"),
			"goal":               strParam("optional: assessment objective for the autonomous exploration engine"),
			"launch_scopesentry": map[string]any{"type": "boolean", "description": "create ScopeSentry project and start ASM scan task (default true)"},
			"launch_artex_task":  map[string]any{"type": "boolean", "description": "create & start ARTEX autonomous task + exploration graph (default true)"},
			"seed_first_intent":  map[string]any{"type": "boolean", "description": "seed an immediate initial exploration intent on the ARTEX task (default true)"},
			"llm_profile_id":     map[string]any{"type": "integer", "description": "optional LLM profile id for the ARTEX task"},
		}),
		func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
			var a struct {
				Target            string          `json:"target"`
				Targets           []string        `json:"targets"`
				Company           string          `json:"company"`
				CompanyID         json.RawMessage `json:"company_id"`
				Scope             string          `json:"scope"`
				Description       string          `json:"description"`
				Goal              string          `json:"goal"`
				LaunchScopeSentry *bool           `json:"launch_scopesentry"`
				LaunchArtexTask   *bool           `json:"launch_artex_task"`
				SeedFirstIntent   *bool           `json:"seed_first_intent"`
				LLMProfileID      json.RawMessage `json:"llm_profile_id"`
			}
			if err := json.Unmarshal(in, &a); err != nil {
				return actool.Errorf("invalid input: " + err.Error()), nil
			}
			res, err := s.runTargetAssessment(ctx, targetAssessmentParams{
				Target:            a.Target,
				Targets:           a.Targets,
				Company:           a.Company,
				CompanyID:         parseProfileID(a.CompanyID),
				Scope:             a.Scope,
				Description:       a.Description,
				Goal:              a.Goal,
				LaunchScopeSentry: a.LaunchScopeSentry == nil || *a.LaunchScopeSentry,
				LaunchArtexTask:   a.LaunchArtexTask == nil || *a.LaunchArtexTask,
				SeedFirstIntent:   a.SeedFirstIntent == nil || *a.SeedFirstIntent,
				LLMProfileID:      parseProfileID(a.LLMProfileID),
			})
			if err != nil {
				return actool.Errorf(err.Error()), nil
			}
			return jsonResult(res)
		},
	)
}

func (s *Server) toolSyncScopeSentryAssets() actool.CoreTool {
	return wrTool(
		"sync_scopesentry_assets",
		"Pull discovered subdomains, HTTP/TCP services, apps, IPs, and vulnerabilities from ScopeSentry ASM back into ARTEX Assets & Findings, recompute company attribution, attach company assets to an ARTEX task, and wake the task engine.",
		objSchema(map[string]any{
			"project_id":          strParam("optional: ScopeSentry project ObjectID (auto-resolved from current chat links when omitted)"),
			"scopesentry_task_id": strParam("optional: ScopeSentry task name to filter by"),
			"task_id":             strParam("optional: ARTEX task id to attach synced assets & findings to (auto-resolved from chat links when omitted)"),
			"company_id":          map[string]any{"type": "integer", "description": "optional: company id (uses ScopeSentry project metadata / attribution when omitted)"},
			"asset_types":         map[string]any{"type": "array", "items": map[string]any{"type": "string"}, "description": "optional: subset of subdomain, service, app, vulnerability (defaults to all four)"},
			"page_size":           map[string]any{"type": "integer", "description": "optional page size (default 100)"},
		}),
		func(ctx context.Context, in json.RawMessage) (actool.Result, error) {
			var a struct {
				ProjectID  string   `json:"project_id"`
				SSTask     string   `json:"scopesentry_task_id"`
				TaskID     string   `json:"task_id"`
				CompanyID  int64    `json:"company_id"`
				AssetTypes []string `json:"asset_types"`
				PageSize   int      `json:"page_size"`
			}
			_ = json.Unmarshal(in, &a)

			taskID, _ := strconv.ParseInt(strings.TrimSpace(a.TaskID), 10, 64)
			projectID := strings.TrimSpace(a.ProjectID)

			if convID := intercept.ConvIDFromContext(ctx); convID > 0 && s.m.pg != nil {
				if links, err := s.m.pg.ListConversationLinks(convID); err == nil {
					for _, l := range links {
						if projectID == "" && l.ScopeSentryProjectID != "" {
							projectID = l.ScopeSentryProjectID
						}
						if taskID == 0 && l.TaskID != nil && *l.TaskID > 0 {
							taskID = *l.TaskID
						}
					}
				}
			}

			opts := ssSyncOpts{
				AssetTypes:    a.AssetTypes,
				CreateCompany: true,
				TaskID:        taskID,
				PageSize:      a.PageSize,
			}
			switch {
			case projectID != "":
				opts.Dimension = "project"
				opts.Targets = []string{projectID}
			case strings.TrimSpace(a.SSTask) != "":
				opts.Dimension = "task"
				opts.Targets = []string{strings.TrimSpace(a.SSTask)}
			default:
				opts.AllProjects = true
			}

			_, _ = s.ensureScopeSentryMCP(ctx)
			res, err := s.syncScopeSentry(ctx, opts)
			if err != nil {
				return actool.Errorf("sync_scopesentry_assets failed: " + err.Error()), nil
			}
			return jsonResult(res)
		},
	)
}

// ---------- Conversation Live Pipeline Links HTTP API ----------

type enrichedConversationLink struct {
	db.ConversationLink
	CompanyName       string `json:"company_name,omitempty"`
	CompanyAssetCount int    `json:"company_asset_count"`
	TaskDescription   string `json:"task_description,omitempty"`
	TaskStatus        string `json:"task_status,omitempty"`
	TaskAssetCount    int    `json:"task_asset_count"`
	TaskFindingCount  int    `json:"task_finding_count"`
	TaskNodeCount     int    `json:"task_node_count"`
	SSProgress        *int   `json:"scopesentry_progress,omitempty"`
	SSStatus          *int   `json:"scopesentry_status,omitempty"`
	SSTaskName        string `json:"scopesentry_task_name,omitempty"`
}

func (s *Server) buildEnrichedConvLinks(ctx context.Context, convID int64, liveSS bool) ([]enrichedConversationLink, error) {
	pg := s.m.pg
	links, err := pg.ListConversationLinks(convID)
	if err != nil {
		return nil, err
	}
	as := s.assetStore()
	cs := s.companyStore()

	var ssClient *mcphttp.Client
	if liveSS {
		hasSS := false
		for _, l := range links {
			if l.ScopeSentryTaskID != "" {
				hasSS = true
				break
			}
		}
		if hasSS {
			lctx, cancel := context.WithTimeout(ctx, 2*time.Second)
			defer cancel()
			if cl, cerr := s.scopeSentryClient(lctx); cerr == nil {
				ssClient = cl
				defer ssClient.Close()
			}
		}
	}

	out := make([]enrichedConversationLink, 0, len(links))
	for _, l := range links {
		item := enrichedConversationLink{ConversationLink: l}
		if l.CompanyID != nil && *l.CompanyID > 0 && cs != nil {
			if c, cerr := cs.GetCompany(*l.CompanyID); cerr == nil && c != nil {
				item.CompanyName = c.Name
			}
			if as != nil {
				if cnt, cerr := as.CountByCompany(*l.CompanyID, ""); cerr == nil {
					item.CompanyAssetCount = cnt
				}
			}
		}
		if l.TaskID != nil && *l.TaskID > 0 {
			tidStr := strconv.FormatInt(*l.TaskID, 10)
			if t, ok := s.m.Task(tidStr); ok && t != nil {
				item.TaskDescription = t.Description
				item.TaskStatus = s.deriveTaskStatus(t)
				if counts, cerr := t.Store.Stats(); cerr == nil {
					for _, c := range counts {
						item.TaskNodeCount += c
					}
					item.TaskFindingCount = counts[db.KindFinding]
				}
			} else {
				var desc, status string
				var expID int64
				if pg.QueryRow(`SELECT description, status, exploration_id FROM tasks WHERE id=$1 AND deleted_at IS NULL`, *l.TaskID).Scan(&desc, &status, &expID) == nil {
					item.TaskDescription = desc
					item.TaskStatus = status
					_ = pg.QueryRow(`SELECT count(*) FROM exploration_nodes WHERE exploration_id=$1`, expID).Scan(&item.TaskNodeCount)
				}
			}
			if item.TaskFindingCount == 0 {
				_ = pg.QueryRow(`SELECT count(*) FROM findings WHERE task_id=$1`, *l.TaskID).Scan(&item.TaskFindingCount)
			}
			if as != nil {
				if byType, cerr := as.CountsByTypeForTask(*l.TaskID); cerr == nil {
					for _, cnt := range byType {
						item.TaskAssetCount += cnt
					}
				}
			}
		}
		if ssClient != nil && l.ScopeSentryTaskID != "" {
			lctx, cancel := context.WithTimeout(ctx, 2*time.Second)
			if text, cerr := ssClient.Call(lctx, "get_task", map[string]any{"id": l.ScopeSentryTaskID}); cerr == nil {
				var tinfo struct {
					Name     string `json:"name"`
					Status   int    `json:"status"`
					Progress int    `json:"progress"`
				}
				if json.Unmarshal([]byte(text), &tinfo) == nil && tinfo.Name != "" {
					item.SSTaskName = tinfo.Name
					st, pr := tinfo.Status, tinfo.Progress
					item.SSStatus = &st
					item.SSProgress = &pr
				}
			}
			cancel()
		}
		out = append(out, item)
	}
	return out, nil
}

func (s *Server) pgConversationLinks(w http.ResponseWriter, r *http.Request) {
	_, c, ok := s.convByID(w, r)
	if !ok {
		return
	}
	liveSS := r.URL.Query().Get("live") == "1"
	links, err := s.buildEnrichedConvLinks(r.Context(), c.ID, liveSS)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"links": links})
}

func (s *Server) pgSyncConversationPipeline(w http.ResponseWriter, r *http.Request) {
	pg, c, ok := s.convByID(w, r)
	if !ok {
		return
	}
	links, err := pg.ListConversationLinks(c.ID)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	var projectIDs []string
	seenProj := map[string]bool{}
	var taskID int64
	for _, l := range links {
		if l.ScopeSentryProjectID != "" && !seenProj[l.ScopeSentryProjectID] {
			seenProj[l.ScopeSentryProjectID] = true
			projectIDs = append(projectIDs, l.ScopeSentryProjectID)
		}
		if taskID == 0 && l.TaskID != nil && *l.TaskID > 0 {
			taskID = *l.TaskID
		}
	}

	ctx, cancel := context.WithTimeout(r.Context(), 90*time.Second)
	defer cancel()

	var syncRes *ssSyncResult
	opts := ssSyncOpts{
		AssetTypes:    []string{"subdomain", "service", "app", "vulnerability"},
		CreateCompany: true,
		TaskID:        taskID,
		PageSize:      syncDefaultPage,
	}
	if len(projectIDs) > 0 {
		opts.Dimension = "project"
		opts.Targets = projectIDs
	} else {
		opts.AllProjects = true
	}
	_, _ = s.ensureScopeSentryMCP(ctx)
	if rres, serr := s.syncScopeSentry(ctx, opts); serr == nil {
		syncRes = rres
	} else {
		syncRes = &ssSyncResult{
			Synced:   map[string]int{"subdomain": 0, "app": 0, "service": 0, "ip": 0, "vulnerability": 0},
			Warnings: []string{"ScopeSentry sync skipped: " + serr.Error()},
		}
	}
	if taskID > 0 {
		if linked, lerr := pg.SyncTaskCompanyAssets(taskID); lerr == nil {
			syncRes.TaskAssetsLinked = linked
		}
	}
	syncRes.FindingsSynced += s.syncReportsDir()

	enriched, _ := s.buildEnrichedConvLinks(ctx, c.ID, true)
	writeJSON(w, 200, map[string]any{
		"ok":    true,
		"sync":  syncRes,
		"links": enriched,
	})
}
