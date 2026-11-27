package server

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/artex/mcphttp"
)

const (
	defaultScopeSentryMCPURL = "http://scope-sentry:8082/mcp"
	defaultScopeSentryMCPKey = "ssk_project_malaria_scopesentry_mcp_key_2026"
)

// Asset sync (ScopeSentry data source).
//
// ScopeSentry is an ASM asset-mapping platform; through its MCP interface we pull
// subdomains, web applications, services and other assets along two dimensions — project
// and task — and map them onto ARTEX's company + asset model. The data source itself is an http-transport MCP row named "ScopeSentry" (url + X-API-Key header stored in mcp_servers).
//
// Unlike the agent tool layer, this uses mcphttp.Client.Call to call MCP tools directly
// and take the raw JSON, without triggering the AskUser permission popup (background batch sync).

const (
	scopeSentryMCPName = "ScopeSentry"
	syncMaxPerType     = 5000 // per-target per-type ingestion guard cap
	syncDefaultPage    = 100
)

// findMCPByName returns the MCP server row with the given name, or nil.
func (s *Server) findMCPByName(name string) (*db.MCPServer, error) {
	all, err := s.m.pg.ListMCP()
	if err != nil {
		return nil, err
	}
	for _, m := range all {
		if m.Name == name {
			return m, nil
		}
	}
	return nil, nil
}

// scopeSentryClient dials the configured ScopeSentry MCP (http transport). The env
// map doubles as HTTP headers (X-API-Key). Callers must Close the client.
func (s *Server) scopeSentryClient(ctx context.Context) (*mcphttp.Client, error) {
	m, err := s.findMCPByName(scopeSentryMCPName)
	if err != nil {
		return nil, err
	}
	if m == nil {
		return nil, fmt.Errorf("data source %s does not exist; create it first", scopeSentryMCPName)
	}
	if m.URL == "" {
		return nil, fmt.Errorf("data source %s has no URL configured; configure it first", scopeSentryMCPName)
	}
	return mcphttp.New(ctx, m.Name, m.URL, jsonStrMap(m.Env), m.Insecure, m.TimeoutSeconds)
}

// envHasValue reports whether the env/header map has any non-empty value
// (i.e. an API key / Authorization header was filled in).
func envHasValue(raw json.RawMessage) bool {
	for _, v := range jsonStrMap(raw) {
		if strings.TrimSpace(v) != "" {
			return true
		}
	}
	return false
}

// ---------- GET /api/sync/scopesentry/status ----------

func (s *Server) ensureScopeSentryMCP(ctx context.Context) (*db.MCPServer, error) {
	m, err := s.findMCPByName(scopeSentryMCPName)
	if err != nil {
		return nil, err
	}
	needsSave := false
	if m == nil {
		env, _ := json.Marshal(map[string]string{"X-API-Key": defaultScopeSentryMCPKey})
		m = &db.MCPServer{
			Name:           scopeSentryMCPName,
			Transport:      "http",
			URL:            defaultScopeSentryMCPURL,
			Env:            env,
			Enabled:        true,
			TimeoutSeconds: 120,
		}
		needsSave = true
	} else {
		if strings.TrimSpace(m.URL) == "" {
			m.URL = defaultScopeSentryMCPURL
			needsSave = true
		}
		if !envHasValue(m.Env) {
			env, _ := json.Marshal(map[string]string{"X-API-Key": defaultScopeSentryMCPKey})
			m.Env = env
			needsSave = true
		}
		if !m.Enabled && m.URL != "" && envHasValue(m.Env) {
			m.Enabled = true
			needsSave = true
		}
	}
	if needsSave {
		id, serr := s.m.pg.SaveMCP(m)
		if serr != nil {
			return nil, serr
		}
		m.ID = id
		if m.Enabled {
			dctx, cancel := context.WithTimeout(ctx, 15*time.Second)
			_ = s.discoverAndCacheMCP(dctx, m)
			cancel()
		}
	}
	return m, nil
}

func (s *Server) syncSSStatus(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	m, err := s.ensureScopeSentryMCP(r.Context())
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	resp := map[string]any{
		"exists":     m != nil,
		"configured": false,
		"enabled":    false,
		"reachable":  false,
		"tools":      []string{},
	}
	if m == nil {
		writeJSON(w, 200, resp)
		return
	}
	configured := m.URL != "" && envHasValue(m.Env)
	resp["configured"] = configured
	resp["enabled"] = m.Enabled
	resp["url"] = m.URL
	if m.Tools != nil {
		resp["tools"] = m.Tools
	}
	// Light reachability probe only when it can actually connect.
	if configured && m.Enabled {
		ctx, cancel := context.WithTimeout(r.Context(), 12*time.Second)
		defer cancel()
		if cl, cerr := mcphttp.New(ctx, m.Name, m.URL, jsonStrMap(m.Env), m.Insecure, m.TimeoutSeconds); cerr == nil {
			if _, terr := cl.Tools(ctx); terr == nil {
				resp["reachable"] = true
			}
			_ = cl.Close()
		}
	}
	writeJSON(w, 200, resp)
}

// ---------- POST /api/sync/scopesentry/datasource ----------
// Creates the placeholder row if missing, and/or sets URL + API key and enables it.

func (s *Server) syncSSDatasource(w http.ResponseWriter, r *http.Request) {
	pg := s.pg(w)
	if pg == nil {
		return
	}
	var body struct {
		URL    string `json:"url"`
		APIKey string `json:"api_key"`
	}
	_ = decode(r, &body) // empty body = auto-configure with Project-Malaria defaults
	body.URL = strings.TrimSpace(body.URL)
	body.APIKey = strings.TrimSpace(body.APIKey)

	m, err := s.findMCPByName(scopeSentryMCPName)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if m == nil {
		env, _ := json.Marshal(map[string]string{"X-API-Key": defaultScopeSentryMCPKey})
		m = &db.MCPServer{
			Name:           scopeSentryMCPName,
			Transport:      "http",
			URL:            defaultScopeSentryMCPURL,
			Env:            env,
			TimeoutSeconds: 120,
		}
	}
	if body.URL != "" {
		m.URL = body.URL
	} else if strings.TrimSpace(m.URL) == "" {
		m.URL = defaultScopeSentryMCPURL
	}
	if body.APIKey != "" {
		env, _ := json.Marshal(map[string]string{"X-API-Key": body.APIKey})
		m.Env = env
	} else if !envHasValue(m.Env) {
		env, _ := json.Marshal(map[string]string{"X-API-Key": defaultScopeSentryMCPKey})
		m.Env = env
	}
	// Enable only once it can actually be used.
	m.Enabled = m.URL != "" && envHasValue(m.Env)

	id, err := pg.SaveMCP(m)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	m.ID = id
	// Best-effort tool discovery so the status card shows tools right away.
	if m.Enabled {
		ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
		_ = s.discoverAndCacheMCP(ctx, m)
		cancel()
	}
	writeJSON(w, 200, map[string]any{"id": id, "enabled": m.Enabled})
}

// ---------- GET /api/sync/scopesentry/projects ----------

func (s *Server) syncSSProjects(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	cl, err := s.scopeSentryClient(ctx)
	if err != nil {
		writeErr(w, 502, err.Error())
		return
	}
	defer cl.Close()

	args := map[string]any{
		"pageIndex": queryInt(r, "page", 1),
		"pageSize":  queryInt(r, "size", 50),
	}
	if q := r.URL.Query().Get("search"); q != "" {
		args["search"] = q
	}
	text, err := cl.Call(ctx, "list_projects_data", args)
	if err != nil {
		writeErr(w, 502, "list_projects_data failed: "+err.Error())
		return
	}
	// {result:{All:[{id,name,logo,AssetCount,tag}], <tag>:[...]}, tag:{...}}
	var env struct {
		Result map[string]json.RawMessage `json:"result"`
		Tag    map[string]int             `json:"tag"`
	}
	if err := json.Unmarshal([]byte(text), &env); err != nil {
		writeErr(w, 502, "failed to parse the project list: "+err.Error())
		return
	}
	projects := json.RawMessage("[]")
	if raw, ok := env.Result["All"]; ok && len(raw) > 0 {
		projects = raw
	}
	writeJSON(w, 200, map[string]any{"projects": projects, "tag": env.Tag})
}

// ---------- GET /api/sync/scopesentry/tasks ----------

func (s *Server) syncSSTasks(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	cl, err := s.scopeSentryClient(ctx)
	if err != nil {
		writeErr(w, 502, err.Error())
		return
	}
	defer cl.Close()

	args := map[string]any{
		"pageIndex": queryInt(r, "page", 1),
		"pageSize":  queryInt(r, "size", 50),
	}
	if q := r.URL.Query().Get("search"); q != "" {
		args["search"] = q
	}
	text, err := cl.Call(ctx, "list_tasks", args)
	if err != nil {
		writeErr(w, 502, "list_tasks failed: "+err.Error())
		return
	}
	var env struct {
		List json.RawMessage `json:"list"`
	}
	if err := json.Unmarshal([]byte(text), &env); err != nil {
		writeErr(w, 502, "failed to parse the task list: "+err.Error())
		return
	}
	tasks := env.List
	if len(tasks) == 0 {
		tasks = json.RawMessage("[]")
	}
	writeJSON(w, 200, map[string]any{"tasks": tasks})
}

type ssSyncOpts struct {
	Dimension      string
	Targets        []string
	AllProjects    bool
	AssetTypes     []string
	CreateCompany  bool
	TaskID         int64
	PageSize       int
	SkipAutoNotify bool
}

type ssSyncResult struct {
	Synced           map[string]int `json:"synced"`
	Companies        []string       `json:"companies,omitempty"`
	Warnings         []string       `json:"warnings,omitempty"`
	Errors           []string       `json:"errors,omitempty"`
	FindingsSynced   int            `json:"findings_synced"`
	TaskAssetsLinked int64          `json:"task_assets_linked,omitempty"`
}

// ---------- POST /api/sync/scopesentry/sync ----------

type ssSyncReq struct {
	Dimension     string   `json:"dimension"`   // "project" | "task"
	Targets       []string `json:"targets"`     // project ObjectIDs, or task names
	AssetTypes    []string `json:"asset_types"` // subdomain | app | service | vulnerability
	CreateCompany bool     `json:"create_company"`
	TaskID        int64    `json:"task_id,omitempty"`
	PageSize      int      `json:"page_size"`
}

func (s *Server) syncSSRun(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	if s.assetStore() == nil || s.companyStore() == nil {
		writeErr(w, 503, "database unavailable")
		return
	}
	var req ssSyncReq
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, "invalid JSON: "+err.Error())
		return
	}
	if req.Dimension != "project" && req.Dimension != "task" {
		writeErr(w, 400, "dimension must be project or task")
		return
	}
	if len(req.Targets) == 0 {
		writeErr(w, 400, "targets cannot be empty")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Minute)
	defer cancel()
	res, err := s.syncScopeSentry(ctx, ssSyncOpts{
		Dimension:     req.Dimension,
		Targets:       req.Targets,
		AssetTypes:    req.AssetTypes,
		CreateCompany: req.CreateCompany,
		TaskID:        req.TaskID,
		PageSize:      req.PageSize,
	})
	if err != nil {
		writeErr(w, 502, err.Error())
		return
	}
	writeJSON(w, 200, res)
}

func (s *Server) existingFindingTitles() map[string]bool {
	titles := map[string]bool{}
	if s.m == nil || s.m.pg == nil {
		return titles
	}
	if existing, err := s.m.pg.ListFindings(2000); err == nil {
		for _, f := range existing {
			if k := strings.ToLower(strings.TrimSpace(f.Name)); k != "" {
				titles[k] = true
			}
		}
	}
	return titles
}

// syncScopeSentry is the shared ScopeSentry ASM ingestion pipeline used by
// HTTP handlers (/sync/scopesentry/sync, /sync/unified, /conversations/{id}/sync)
// and agent pipeline tools (sync_scopesentry_assets).
func (s *Server) syncScopeSentry(ctx context.Context, opts ssSyncOpts) (*ssSyncResult, error) {
	as := s.assetStore()
	cs := s.companyStore()
	if as == nil || cs == nil {
		return nil, fmt.Errorf("database unavailable")
	}
	cl, err := s.scopeSentryClient(ctx)
	if err != nil {
		return nil, err
	}
	defer cl.Close()

	assetTypes := opts.AssetTypes
	if len(assetTypes) == 0 {
		assetTypes = []string{"subdomain", "service", "app", "vulnerability"}
	}
	pageSize := opts.PageSize
	if pageSize <= 0 || pageSize > 500 {
		pageSize = syncDefaultPage
	}

	res := &ssSyncResult{
		Synced: map[string]int{"subdomain": 0, "app": 0, "service": 0, "ip": 0, "vulnerability": 0},
	}
	titles := s.existingFindingTitles()
	madeCompany := false

	type syncBatch struct {
		label  string
		filter map[string]any
		projID string
	}
	var batches []syncBatch

	if opts.AllProjects && len(opts.Targets) == 0 {
		var projectIDs []string
		if text, cerr := cl.Call(ctx, "list_projects_data", map[string]any{"pageIndex": 1, "pageSize": 100}); cerr == nil {
			var env struct {
				Result map[string][]struct {
					ID   string `json:"id"`
					Name string `json:"name"`
				} `json:"result"`
			}
			if json.Unmarshal([]byte(text), &env) == nil {
				for _, p := range env.Result["All"] {
					if p.ID != "" {
						projectIDs = append(projectIDs, p.ID)
					}
				}
			}
		}
		if len(projectIDs) > 0 {
			for _, pid := range projectIDs {
				batches = append(batches, syncBatch{label: pid, filter: map[string]any{"project": []string{pid}}, projID: pid})
			}
		} else {
			batches = append(batches, syncBatch{label: "all", filter: map[string]any{}})
		}
	} else {
		for _, target := range opts.Targets {
			t := strings.TrimSpace(target)
			if t == "" {
				continue
			}
			filter := map[string]any{}
			var projID string
			switch opts.Dimension {
			case "task":
				filter["task"] = []string{t}
			default:
				filter["project"] = []string{t}
				projID = t
			}
			batches = append(batches, syncBatch{label: t, filter: filter, projID: projID})
		}
	}

	ssTypeMap := map[string]string{
		"subdomain":     "subdomain",
		"service":       "asset",
		"app":           "app",
		"vulnerability": "vulnerability",
	}

	for _, b := range batches {
		if opts.CreateCompany && b.projID != "" {
			name, roots, perr := s.ssProjectMeta(ctx, cl, b.projID)
			if perr != nil {
				res.Warnings = append(res.Warnings, fmt.Sprintf("failed to fetch details of project %s: %v", b.projID, perr))
			} else if name != "" {
				cid, cerr := cs.UpsertByName(name)
				if cerr != nil {
					res.Warnings = append(res.Warnings, fmt.Sprintf("failed to create company %s: %v", name, cerr))
				} else {
					res.Companies = append(res.Companies, name)
					madeCompany = true
					if len(roots) > 0 {
						cs.AddScope(cid, roots, "scopesentry:"+name)
					}
				}
			}
		}
		for _, at := range assetTypes {
			key := strings.TrimSpace(at)
			ssType, ok := ssTypeMap[key]
			if !ok {
				res.Warnings = append(res.Warnings, "unknown asset type, skipped: "+at)
				continue
			}
			items, truncated, ferr := s.ssPageAll(ctx, cl, ssType, b.filter, pageSize)
			if ferr != nil {
				res.Errors = append(res.Errors, fmt.Sprintf("%s(%s) fetch failed: %v", key, b.label, ferr))
				continue
			}
			if truncated {
				res.Warnings = append(res.Warnings, fmt.Sprintf("%s(%s) hit the %d-entry cap, truncated", key, b.label, syncMaxPerType))
			}
			for _, raw := range items {
				if e := s.ssIngestForTask(as, opts.TaskID, key, raw, res.Synced, titles); e != "" {
					res.Errors = append(res.Errors, e)
				}
			}
		}
	}

	if madeCompany {
		_ = cs.RecomputeAttribution()
	}
	res.FindingsSynced = res.Synced["vulnerability"]
	if opts.TaskID > 0 && s.m.pg != nil {
		if linked, lerr := s.m.pg.SyncTaskCompanyAssets(opts.TaskID); lerr == nil {
			res.TaskAssetsLinked = linked
		}
		totalAdded := res.Synced["subdomain"] + res.Synced["service"] + res.Synced["app"] + res.Synced["ip"] + res.Synced["vulnerability"]
		if !opts.SkipAutoNotify && (totalAdded > 0 || res.TaskAssetsLinked > 0) && s.m != nil {
			if t, ok := s.m.Task(strconv.FormatInt(opts.TaskID, 10)); ok {
				t.Notify()
			}
		}
	}
	return res, nil
}

// ssProjectMeta fetches a project's display name and its target root domains
// (get_project.target is a newline-separated list) for company + scope creation.
func (s *Server) ssProjectMeta(ctx context.Context, cl *mcphttp.Client, projectID string) (name string, roots []string, err error) {
	text, err := cl.Call(ctx, "get_project", map[string]any{"id": projectID})
	if err != nil {
		return "", nil, err
	}
	var p struct {
		Name   string `json:"name"`
		Target string `json:"target"`
	}
	if err := json.Unmarshal([]byte(text), &p); err != nil {
		return "", nil, err
	}
	for _, line := range strings.Split(p.Target, "\n") {
		if t := strings.TrimSpace(line); t != "" {
			roots = append(roots, t)
		}
	}
	return p.Name, roots, nil
}

// ssPageAll pages through list_assets for one asset_type + filter until a short/empty
// page or the protection cap. The {list:[...]} envelope has no total, so we stop when
// a page returns fewer than pageSize items.
func (s *Server) ssPageAll(ctx context.Context, cl *mcphttp.Client, ssType string, filter map[string]any, pageSize int) (items []json.RawMessage, truncated bool, err error) {
	for page := 1; ; page++ {
		args := map[string]any{"asset_type": ssType, "pageIndex": page, "pageSize": pageSize}
		if len(filter) > 0 {
			args["filter"] = filter
		}
		text, cerr := cl.Call(ctx, "list_assets", args)
		if cerr != nil {
			return items, truncated, cerr
		}
		var env struct {
			List []json.RawMessage `json:"list"`
		}
		if uerr := json.Unmarshal([]byte(text), &env); uerr != nil {
			return items, truncated, uerr
		}
		if len(env.List) == 0 {
			break
		}
		items = append(items, env.List...)
		if len(items) >= syncMaxPerType {
			items = items[:syncMaxPerType]
			truncated = true
			break
		}
		if len(env.List) < pageSize {
			break
		}
	}
	return items, truncated, nil
}

// ssIngest maps one ScopeSentry asset JSON to the ARTEX asset store and upserts it.
// Returns a non-empty error string on failure. synced is incremented per kind.
func (s *Server) ssIngest(as *db.AssetStore, assetType string, raw json.RawMessage, synced map[string]int) string {
	return s.ssIngestForTask(as, 0, assetType, raw, synced, nil)
}

func (s *Server) ssIngestForTask(as *db.AssetStore, taskID int64, assetType string, raw json.RawMessage, synced map[string]int, existingTitles map[string]bool) string {
	switch assetType {
	case "subdomain":
		var it struct {
			Host  string   `json:"host"`
			Type  string   `json:"type"`
			Value []string `json:"value"`
			IP    []string `json:"ip"`
		}
		if err := json.Unmarshal(raw, &it); err != nil {
			return "subdomain parse failed: " + err.Error()
		}
		if it.Host == "" {
			return ""
		}
		if _, err := as.UpsertSubdomain(db.UpsertSubdomainReq{Domain: it.Host, RecordType: it.Type, RecordValue: it.Value, TaskID: taskID}); err != nil {
			return "subdomain " + it.Host + ": " + err.Error()
		}
		synced["subdomain"]++
		for _, ip := range it.IP {
			if ip != "" {
				if _, err := as.UpsertIP(db.UpsertIPReq{IP: ip, BoundDomains: []string{it.Host}, TaskID: taskID}); err == nil {
					synced["ip"]++
				}
			}
		}
	case "app":
		var it struct {
			Name        string `json:"name"`
			Category    string `json:"category"`
			Description string `json:"description"`
			ICP         string `json:"icp"`
		}
		if err := json.Unmarshal(raw, &it); err != nil {
			return "app parse failed: " + err.Error()
		}
		if it.Name == "" {
			return ""
		}
		if _, err := as.UpsertApp(db.UpsertAppReq{Name: it.Name, Category: it.Category, Description: it.Description, ICP: it.ICP, TaskID: taskID}); err != nil {
			return "app " + it.Name + ": " + err.Error()
		}
		synced["app"]++
	case "service":
		var it struct {
			Domain   string   `json:"domain"`
			IP       string   `json:"ip"`
			Port     string   `json:"port"`
			Service  string   `json:"service"`
			URL      string   `json:"url"`
			Title    string   `json:"title"`
			Status   *int     `json:"status"`
			Products []string `json:"products"`
			Icon     string   `json:"icon"`
		}
		if err := json.Unmarshal(raw, &it); err != nil {
			return "service parse failed: " + err.Error()
		}
		if it.Service == "http" || it.URL != "" {
			if it.URL == "" {
				return ""
			}
			if _, err := as.UpsertHTTPService(db.UpsertHTTPServiceReq{
				URL: it.URL, Technologies: it.Products, StatusCode: it.Status,
				PageTitle: it.Title, FaviconMMH3: it.Icon, IP: it.IP, TaskID: taskID,
			}); err != nil {
				return "service " + it.URL + ": " + err.Error()
			}
		} else {
			port, _ := strconv.Atoi(it.Port)
			if _, err := as.UpsertOtherService(db.UpsertOtherServiceReq{
				Domain: it.Domain, IP: it.IP, Port: port, ServiceName: it.Service, TaskID: taskID,
			}); err != nil {
				return "service " + it.IP + ":" + it.Port + ": " + err.Error()
			}
		}
		synced["service"]++
	case "vulnerability":
		var it struct {
			VulnID        string `json:"vulnid"`
			URL           string `json:"url"`
			Vulnerability string `json:"vulnerability"`
			VulName       string `json:"vulname"`
			Matched       string `json:"matched"`
			Level         string `json:"level"`
			Request       string `json:"request"`
			Response      string `json:"response"`
			TaskName      string `json:"taskName"`
			RootDomain    string `json:"rootDomain"`
		}
		if err := json.Unmarshal(raw, &it); err != nil {
			return "vulnerability parse failed: " + err.Error()
		}
		name := strings.TrimSpace(it.Vulnerability)
		if name == "" {
			name = strings.TrimSpace(it.VulName)
		}
		if name == "" {
			name = strings.TrimSpace(it.VulnID)
		}
		if name == "" {
			return ""
		}
		target := strings.TrimSpace(it.URL)
		if target == "" {
			target = strings.TrimSpace(it.Matched)
		}
		if target == "" {
			target = strings.TrimSpace(it.RootDomain)
		}
		title := "[ScopeSentry] " + name
		if target != "" {
			title = fmt.Sprintf("[ScopeSentry] %s — %s", name, target)
		}
		if existingTitles == nil {
			existingTitles = s.existingFindingTitles()
		}
		var evParts []string
		if it.Matched != "" {
			evParts = append(evParts, "Matched: "+it.Matched)
		}
		if it.Request != "" {
			reqStr := it.Request
			if len(reqStr) > 3500 {
				reqStr = reqStr[:3500] + "\n...(truncated)"
			}
			evParts = append(evParts, "Request:\n"+reqStr)
		}
		if it.Response != "" {
			respStr := it.Response
			if len(respStr) > 3500 {
				respStr = respStr[:3500] + "\n...(truncated)"
			}
			evParts = append(evParts, "Response:\n"+respStr)
		}
		worker := "scopesentry"
		if strings.TrimSpace(it.TaskName) != "" {
			worker = "scopesentry:" + strings.TrimSpace(it.TaskName)
		}
		_, created, err := s.upsertFindingReq(createFindingReq{
			Title:       title,
			Severity:    it.Level,
			VulnClass:   name,
			TaskID:      taskID,
			TaskDesc:    worker,
			Target:      target,
			Description: fmt.Sprintf("Detected by ScopeSentry scanner on %s (severity: %s)", target, it.Level),
			Evidence:    strings.Join(evParts, "\n\n"),
		}, existingTitles)
		if err != nil {
			return "vulnerability " + name + ": " + err.Error()
		}
		if created {
			synced["vulnerability"]++
		}
	}
	return ""
}

// queryInt reads an int query param with a default fallback.
func queryInt(r *http.Request, key string, def int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return def
}

type createFindingReq struct {
	Title       string         `json:"title"`
	Severity    string         `json:"severity"`
	VulnClass   string         `json:"vuln_class"`
	Status      string         `json:"status"`
	TaskID      int64          `json:"task_id"`
	TaskDesc    string         `json:"task_desc"`
	Target      string         `json:"target"`
	Description string         `json:"description"`
	Evidence    string         `json:"evidence"`
	Remediation string         `json:"remediation"`
	Details     map[string]any `json:"details"`
}

func normalizeFindingSeverity(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "critical", "crit":
		return "critical"
	case "high":
		return "high"
	case "medium", "med", "moderate":
		return "medium"
	case "low", "info", "informational":
		return "low"
	default:
		return "medium"
	}
}

func normalizeFindingStatus(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "open", "confirmed", "fixed", "false_positive", "ignored":
		return strings.ToLower(strings.TrimSpace(raw))
	default:
		return "open"
	}
}

func (s *Server) upsertFindingReq(req createFindingReq, existingTitles map[string]bool) (*db.DBFinding, bool, error) {
	title := strings.TrimSpace(req.Title)
	if title == "" {
		return nil, false, fmt.Errorf("title is required")
	}
	key := strings.ToLower(title)
	if existingTitles != nil && existingTitles[key] {
		return nil, false, nil
	}

	worker := strings.TrimSpace(req.TaskDesc)
	if worker == "" {
		worker = "deep-agent-ide"
	}

	var assetIDs []int64
	if target := strings.TrimSpace(req.Target); target != "" {
		if as := s.assetStore(); as != nil {
			if scheme, host, port, ok := parseTarget(target); ok && host != "" {
				if net.ParseIP(host) != nil {
					if id, err := as.UpsertIP(db.UpsertIPReq{IP: host, TaskID: req.TaskID}); err == nil && id > 0 {
						assetIDs = append(assetIDs, id)
					}
				} else if scheme == "http" || scheme == "https" {
					u := scheme + "://" + host
					if !(scheme == "https" && port == 443) && !(scheme == "http" && port == 80) {
						u += ":" + strconv.Itoa(port)
					}
					if id, err := as.UpsertHTTPService(db.UpsertHTTPServiceReq{URL: u, TaskID: req.TaskID}); err == nil && id > 0 {
						assetIDs = append(assetIDs, id)
					}
				} else {
					if id, err := as.UpsertSubdomain(db.UpsertSubdomainReq{Domain: host, TaskID: req.TaskID}); err == nil && id > 0 {
						assetIDs = append(assetIDs, id)
					}
				}
			}
		}
	}

	vulnClass := strings.TrimSpace(req.VulnClass)
	if vulnClass == "" {
		if vc, ok := req.Details["vuln_class"].(string); ok {
			vulnClass = strings.TrimSpace(vc)
		}
	}
	if vulnClass == "" {
		vulnClass = "Vulnerability"
	}

	summary := strings.TrimSpace(req.Description)
	if summary == "" {
		if desc, ok := req.Details["description"].(string); ok {
			summary = strings.TrimSpace(desc)
		}
	}
	if summary == "" {
		summary = title
	}

	evidence := strings.TrimSpace(req.Evidence)
	if evidence == "" {
		if ev, ok := req.Details["evidence"].(string); ok {
			evidence = strings.TrimSpace(ev)
		}
	}

	sev := normalizeFindingSeverity(req.Severity)
	var id int64
	var err error
	if req.TaskID > 0 && s.m != nil && s.m.dir != "" {
		var expID int64
		if qerr := s.m.pg.QueryRow(`SELECT exploration_id FROM tasks WHERE id=$1 AND deleted_at IS NULL`, req.TaskID).Scan(&expID); qerr == nil && expID > 0 {
			if rec, rerr := s.evidenceStore().Record(context.Background(), db.RecordFindingInput{
				TaskID:        req.TaskID,
				ExplorationID: expID,
				VulnClass:     vulnClass,
				Name:          title,
				Severity:      sev,
				Summary:       summary,
				Evidence:      evidence,
				Worker:        worker,
				AssetIDs:      assetIDs,
			}, nil); rerr == nil && rec != nil {
				id = rec.FindingID
			}
		}
	}
	if id == 0 {
		id, err = s.m.pg.AddFinding(req.TaskID, 0, vulnClass, title, sev, summary, evidence, worker, assetIDs)
		if err != nil {
			return nil, false, err
		}
	}
	if existingTitles != nil {
		existingTitles[key] = true
	}
	dbf, _ := s.m.pg.GetFinding(id)
	if dbf == nil {
		dbf = &db.DBFinding{
			ID:        id,
			VulnClass: vulnClass,
			Name:      title,
			Severity:  sev,
			Summary:   summary,
			Evidence:  evidence,
			Worker:    worker,
			AssetIDs:  assetIDs,
			Status:    db.FindingPending,
			CreatedAt: time.Now(),
		}
	}
	return dbf, true, nil
}

// POST /api/exploration/findings — allows AI Pentest Studio (Deep Agent IDE) or external
// workflows to push findings directly into Malaria's unified Findings & Dashboard store.
func (s *Server) createFinding(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	var req createFindingReq
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, "invalid JSON: "+err.Error())
		return
	}
	existing, _ := s.m.pg.ListFindings(1000)
	existingTitles := map[string]bool{}
	for _, f := range existing {
		existingTitles[strings.ToLower(strings.TrimSpace(f.Name))] = true
	}
	dbf, created, err := s.upsertFindingReq(req, existingTitles)
	if err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	if !created {
		for _, f := range existing {
			if strings.EqualFold(strings.TrimSpace(f.Name), strings.TrimSpace(req.Title)) {
				assets := s.resolveAssetIDs(f.AssetIDs)
				writeJSON(w, 200, findingFromDB(f, assets))
				return
			}
		}
	}
	assets := s.resolveAssetIDs(dbf.AssetIDs)
	writeJSON(w, 201, findingFromDB(dbf, assets))
}

// syncReportsDir scans /reports for JSON finding files written by Deep Agent IDE (/ai)
// and imports any new findings into the unified PostgreSQL findings table.
func (s *Server) syncReportsDir() int {
	entries, err := os.ReadDir("/reports")
	if err != nil {
		return 0
	}
	existing, _ := s.m.pg.ListFindings(1000)
	existingTitles := map[string]bool{}
	for _, f := range existing {
		existingTitles[strings.ToLower(strings.TrimSpace(f.Name))] = true
	}
	imported := 0
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(strings.ToLower(entry.Name()), ".json") {
			continue
		}
		raw, err := os.ReadFile(filepath.Join("/reports", entry.Name()))
		if err != nil || len(raw) == 0 {
			continue
		}
		var single createFindingReq
		if err := json.Unmarshal(raw, &single); err == nil && strings.TrimSpace(single.Title) != "" {
			if _, ok, _ := s.upsertFindingReq(single, existingTitles); ok {
				imported++
			}
			continue
		}
		var batch struct {
			Findings []createFindingReq `json:"findings"`
		}
		if err := json.Unmarshal(raw, &batch); err == nil && len(batch.Findings) > 0 {
			for _, item := range batch.Findings {
				if _, ok, _ := s.upsertFindingReq(item, existingTitles); ok {
					imported++
				}
			}
			continue
		}
		var list []createFindingReq
		if err := json.Unmarshal(raw, &list); err == nil && len(list) > 0 {
			for _, item := range list {
				if _, ok, _ := s.upsertFindingReq(item, existingTitles); ok {
					imported++
				}
			}
		}
	}
	return imported
}

// POST /api/sync/unified — 1-click & background auto-sync across ScopeSentry, Deep Agent IDE, and Malaria Core.
func (s *Server) syncUnified(w http.ResponseWriter, r *http.Request) {
	if s.pg(w) == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Minute)
	defer cancel()

	synced := map[string]int{"subdomain": 0, "app": 0, "service": 0, "ip": 0, "vulnerability": 0}
	var companies []string
	var warnings []string

	_, _ = s.ensureScopeSentryMCP(ctx)
	var ssFindings int
	if res, err := s.syncScopeSentry(ctx, ssSyncOpts{
		AllProjects:   true,
		AssetTypes:    []string{"subdomain", "service", "app", "vulnerability"},
		CreateCompany: true,
		PageSize:      syncDefaultPage,
	}); err == nil {
		synced = res.Synced
		companies = res.Companies
		warnings = append(warnings, res.Warnings...)
		warnings = append(warnings, res.Errors...)
		ssFindings = res.FindingsSynced
	} else {
		warnings = append(warnings, "ScopeSentry MCP: "+err.Error())
	}

	// Sync company assets into any active ARTEX tasks that are company-scoped.
	if rows, err := s.m.pg.Query(`SELECT DISTINCT task_id FROM task_companies`); err == nil {
		var tids []int64
		for rows.Next() {
			var tid int64
			if rows.Scan(&tid) == nil && tid > 0 {
				tids = append(tids, tid)
			}
		}
		rows.Close()
		for _, tid := range tids {
			_, _ = s.m.pg.SyncTaskCompanyAssets(tid)
		}
	}

	findingsImported := s.syncReportsDir() + ssFindings
	go s.discoverEmptyMCPsOnStartup()

	writeJSON(w, 200, map[string]any{
		"ok":              true,
		"synced":          synced,
		"companies":       companies,
		"findings_synced": findingsImported,
		"warnings":        warnings,
	})
}

const ssTaskAutoSyncInterval = 60 * time.Second

// runScopeSentryTaskAutoSync periodically pulls new ScopeSentry ASM discoveries
// into active ARTEX tasks linked via conversation_links so the planner receives
// newly discovered subdomains/services/vulnerabilities without manual /sync calls.
func (s *Server) runScopeSentryTaskAutoSync(ctx context.Context) {
	var completed sync.Map
	ticker := time.NewTicker(ssTaskAutoSyncInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.syncActiveTasksScopeSentry(ctx, &completed)
		}
	}
}

func sumTaskAssetCounts(byType map[string]int) int {
	total := 0
	for _, n := range byType {
		total += n
	}
	return total
}

func (s *Server) syncActiveTasksScopeSentry(ctx context.Context, completed *sync.Map) {
	if s.m == nil || s.m.pg == nil {
		return
	}
	as := s.assetStore()
	if as == nil {
		return
	}
	links, err := s.m.pg.ListTaskScopeSentryLinks()
	if err != nil || len(links) == 0 {
		return
	}

	type syncTarget struct {
		taskID  int64
		task    *Task
		projID  string
		ssTask  string
		doneKey string
	}
	var active []syncTarget
	for _, l := range links {
		if l.TaskID == nil || *l.TaskID <= 0 {
			continue
		}
		tid := *l.TaskID
		tidStr := strconv.FormatInt(tid, 10)
		t, ok := s.m.Task(tidStr)
		if !ok || t == nil {
			continue
		}
		if t.lifecycleSnapshot().Queued || isTerminalStatus(s.deriveTaskStatus(t)) {
			continue
		}
		if s.engine != nil && (s.engine.IsPaused(tidStr) || s.engine.IsDeleting(tidStr)) {
			continue
		}
		doneKey := fmt.Sprintf("%d:%s:%s", tid, l.ScopeSentryProjectID, l.ScopeSentryTaskID)
		if completed != nil {
			if _, done := completed.Load(doneKey); done {
				continue
			}
		}
		active = append(active, syncTarget{
			taskID:  tid,
			task:    t,
			projID:  l.ScopeSentryProjectID,
			ssTask:  l.ScopeSentryTaskID,
			doneKey: doneKey,
		})
	}
	if len(active) == 0 {
		return
	}

	for _, tg := range active {
		if ctx.Err() != nil {
			return
		}
		ssDone := false
		if tg.ssTask != "" {
			pctx, pcancel := context.WithTimeout(ctx, 5*time.Second)
			if cl, cerr := s.scopeSentryClient(pctx); cerr == nil {
				if text, callErr := cl.Call(pctx, "get_task", map[string]any{"id": tg.ssTask}); callErr == nil {
					var tinfo struct {
						Progress int `json:"progress"`
					}
					if json.Unmarshal([]byte(text), &tinfo) == nil && tinfo.Progress >= 100 {
						ssDone = true
					}
				}
				_ = cl.Close()
			}
			pcancel()
		}

		beforeAssets := 0
		if byType, cerr := as.CountsByTypeForTask(tg.taskID); cerr == nil {
			beforeAssets = sumTaskAssetCounts(byType)
		}

		dim := "project"
		targetID := tg.projID
		if targetID == "" {
			dim = "task"
			targetID = tg.ssTask
		}
		sctx, scancel := context.WithTimeout(ctx, 90*time.Second)
		res, serr := s.syncScopeSentry(sctx, ssSyncOpts{
			Dimension:      dim,
			Targets:        []string{targetID},
			AssetTypes:     []string{"subdomain", "service", "app", "vulnerability"},
			TaskID:         tg.taskID,
			PageSize:       syncDefaultPage,
			SkipAutoNotify: true,
		})
		scancel()
		if serr != nil {
			log.Printf("[scopesentry auto-sync] task #%d skipped/failed: %v", tg.taskID, serr)
			continue
		}
		if ssDone && completed != nil {
			completed.Store(tg.doneKey, true)
		}

		afterAssets := beforeAssets
		if byType, cerr := as.CountsByTypeForTask(tg.taskID); cerr == nil {
			afterAssets = sumTaskAssetCounts(byType)
		}
		deltaAssets := afterAssets - beforeAssets
		if deltaAssets < 0 {
			deltaAssets = 0
		}
		if deltaAssets > 0 || res.FindingsSynced > 0 {
			log.Printf("[scopesentry auto-sync] task #%d ingested +%d asset(s), +%d finding(s)", tg.taskID, deltaAssets, res.FindingsSynced)
			if s.engine != nil {
				s.engine.emitActivity(tg.task, db.Activity{
					Worker:  "system",
					Kind:    "text",
					Summary: fmt.Sprintf("ScopeSentry auto-sync added +%d asset(s) and +%d finding(s) to task #%d", deltaAssets, res.FindingsSynced, tg.taskID),
				})
			}
			tg.task.Notify()
		}
	}
}
