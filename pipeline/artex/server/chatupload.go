package server

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/Autumn-27/artex/db"
)

// maxChatUpload caps a single chat-attachment upload request (memory + spill).
const maxChatUpload = 256 << 20 // 256 MiB (supports full folder uploads)

const sharedWorkspaceRoot = "/workspace"

// safeChatID guards the {id} path segment against traversal — task ids are numeric,
// session ids are alnum/_/- ; anything with "/" or ".." is rejected.
var safeChatID = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)

var unsafeFolderChars = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func sanitizeFolderSegment(seg string) string {
	seg = strings.TrimSpace(seg)
	if seg == "" || seg == "." || seg == ".." {
		return ""
	}
	cleaned := unsafeFolderChars.ReplaceAllString(seg, "-")
	cleaned = strings.Trim(cleaned, "-")
	if cleaned == "" || cleaned == "." || cleaned == ".." {
		return "item"
	}
	return cleaned
}

func sanitizeRelativeUploadPath(rel string) string {
	rel = strings.ReplaceAll(strings.TrimSpace(rel), "\\", "/")
	parts := strings.Split(rel, "/")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" || p == "." {
			continue
		}
		if p == ".." {
			return ""
		}
		// Keep original unicode/Thai filenames safe while blocking slashes/traversal
		if strings.ContainsAny(p, `/\`) || strings.Contains(p, "\x00") {
			continue
		}
		out = append(out, p)
	}
	return strings.Join(out, "/")
}

// chatAttachment is one uploaded file or shared folder as the frontend + agent see it.
type chatAttachment struct {
	Name string `json:"name"`
	Path string `json:"path"`
	Size int64  `json:"size"`
	Abs  string `json:"abs,omitempty"`
}

// chatUpload saves uploaded files OR an entire directory tree (when folder_name or relpath
// is supplied) into either the conversation uploads/ dir or /workspace/shared/<folder> so
// Graph Chat (/chat), Pentest Missions, and Deep Agent IDE (/ai) share the exact same folder!
func (s *Server) chatUpload(w http.ResponseWriter, r *http.Request) {
	var sub string
	taskScoped := false
	switch r.URL.Query().Get("scope") {
	case "task":
		sub = "tasks"
		taskScoped = true
	case "session":
		sub = "sessions"
	case "staging":
		sub = "drafts"
	default:
		writeErr(w, 400, "scope must be task / session / staging")
		return
	}
	id := r.URL.Query().Get("id")
	if !safeChatID.MatchString(id) {
		writeErr(w, 400, "invalid id")
		return
	}
	if taskScoped {
		if s.m.ResolveTask(id) == nil {
			writeErr(w, 404, "task not found")
			return
		}
		if !s.engine.beginTaskOperation(id) {
			writeErr(w, http.StatusConflict, "Task is being deleted; cannot upload attachments")
			return
		}
		defer s.engine.decInflight(id)
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxChatUpload)
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		writeErr(w, 400, "failed to parse the upload or size limit exceeded: "+err.Error())
		return
	}
	files := r.MultipartForm.File["file"]
	if len(files) == 0 {
		writeErr(w, 400, "missing upload file (form field file)")
		return
	}

	folderNameRaw := strings.TrimSpace(r.FormValue("folder_name"))
	relPaths := r.MultipartForm.Value["relpath"]
	isFolderUpload := folderNameRaw != ""
	if !isFolderUpload {
		for _, rp := range relPaths {
			if strings.Contains(rp, "/") || strings.Contains(rp, "\\") {
				isFolderUpload = true
				break
			}
		}
	}

	// Folder mode -> store into /workspace/shared/<folder> so /chat and Deep Agent IDE (/ai) share it live!
	if isFolderUpload {
		if folderNameRaw == "" && len(relPaths) > 0 {
			firstSeg := strings.Split(strings.ReplaceAll(relPaths[0], "\\", "/"), "/")[0]
			folderNameRaw = firstSeg
		}
		folderSlug := sanitizeFolderSegment(folderNameRaw)
		if folderSlug == "" {
			folderSlug = "uploaded-folder"
		}
		baseShared := filepath.Join(sharedWorkspaceRoot, "shared")
		if err := os.MkdirAll(baseShared, 0o755); err != nil {
			baseShared = filepath.Join(s.m.dir, sub, id, "uploads")
			_ = os.MkdirAll(baseShared, 0o755)
		}
		targetFolder := filepath.Join(baseShared, folderSlug)
		if err := os.MkdirAll(targetFolder, 0o755); err != nil {
			writeErr(w, 500, "failed to create shared folder: "+err.Error())
			return
		}

		var totalBytes int64
		savedCount := 0
		for i, hdr := range files {
			rel := ""
			if i < len(relPaths) {
				rel = sanitizeRelativeUploadPath(relPaths[i])
			}
			if rel == "" {
				rel = sanitizeRelativeUploadPath(hdr.Filename)
			}
			// Strip leading duplicate folderName prefix if webkitRelativePath included it
			prefix := folderNameRaw + "/"
			if folderNameRaw != "" && strings.HasPrefix(rel, prefix) {
				rel = strings.TrimPrefix(rel, prefix)
			}
			if rel == "" {
				continue
			}
			dest := filepath.Join(targetFolder, filepath.FromSlash(rel))
			cleanDest := filepath.Clean(dest)
			if !strings.HasPrefix(cleanDest, filepath.Clean(targetFolder)+string(os.PathSeparator)) {
				continue
			}
			if err := os.MkdirAll(filepath.Dir(cleanDest), 0o755); err != nil {
				continue
			}
			if err := saveUpload(hdr, cleanDest); err != nil {
				writeErr(w, 500, "Save failed: "+err.Error())
				return
			}
			totalBytes += hdr.Size
			savedCount++
		}

		curCtx := s.loadSharedContext()
		curCtx.WorkspacePath = targetFolder
		if curCtx.Source == "" {
			curCtx.Source = "folder_upload"
		}
		_ = s.saveSharedContext(curCtx)

		displayLabel := folderNameRaw
		if displayLabel == "" {
			displayLabel = folderSlug
		}
		out := []chatAttachment{{
			Name: fmt.Sprintf("📁 %s (%d files)", displayLabel, savedCount),
			Path: targetFolder,
			Size: totalBytes,
			Abs:  targetFolder,
		}}
		writeJSON(w, 200, map[string]any{"attachments": out, "workspace_path": targetFolder})
		return
	}

	dir := filepath.Join(s.m.dir, sub, id, "uploads")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		writeErr(w, 500, "failed to create directory: "+err.Error())
		return
	}
	sharedUploadsDir := filepath.Join(sharedWorkspaceRoot, "shared", "uploads")
	canMirrorShared := os.MkdirAll(sharedUploadsDir, 0o755) == nil

	out := make([]chatAttachment, 0, len(files))
	for _, hdr := range files {
		name := filepath.Base(hdr.Filename)
		if name == "" || name == "." || name == ".." || strings.ContainsAny(name, `/\`) {
			continue
		}
		dest := uniqueUploadPath(dir, name)
		if err := saveUpload(hdr, dest); err != nil {
			writeErr(w, 500, "Save failed: "+err.Error())
			return
		}
		base := filepath.Base(dest)
		attPath := "uploads/" + base
		absPath := dest
		if canMirrorShared {
			mirrorDest := filepath.Join(sharedUploadsDir, base)
			if data, rerr := os.ReadFile(dest); rerr == nil {
				if os.WriteFile(mirrorDest, data, 0o644) == nil {
					attPath = mirrorDest
					absPath = mirrorDest
				}
			}
		}
		out = append(out, chatAttachment{Name: base, Path: attPath, Size: hdr.Size, Abs: absPath})
	}
	writeJSON(w, 200, map[string]any{"attachments": out})
}

type sharedWorkspaceFolderInfo struct {
	Name       string `json:"name"`
	Path       string `json:"path"`
	Group      string `json:"group"`
	FileCount  int    `json:"file_count"`
	TotalBytes int64  `json:"total_bytes"`
}

func summarizeFolderQuick(dirPath string) (int, int64) {
	count := 0
	var total int64
	_ = filepath.WalkDir(dirPath, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			name := d.Name()
			if p != dirPath && (strings.HasPrefix(name, ".") || name == "node_modules" || name == "__pycache__" || name == "venv") {
				return filepath.SkipDir
			}
			return nil
		}
		count++
		if info, ierr := d.Info(); ierr == nil {
			total += info.Size()
		}
		if count >= 500 {
			return fs.SkipAll
		}
		return nil
	})
	return count, total
}

// listChatWorkspaces lists folders under /workspace and /workspace/shared so Graph Chat (/chat)
// can attach any folder shared with Deep Agent IDE (/ai) in one click.
func (s *Server) listChatWorkspaces(w http.ResponseWriter, _ *http.Request) {
	var folders []sharedWorkspaceFolderInfo
	skipNames := map[string]bool{
		".qwen": true, ".git": true, "node_modules": true, "__pycache__": true, "shared": true,
	}

	if entries, err := os.ReadDir(sharedWorkspaceRoot); err == nil {
		// Include /workspace root itself as an option
		rootCnt, rootBytes := summarizeFolderQuick(sharedWorkspaceRoot)
		folders = append(folders, sharedWorkspaceFolderInfo{
			Name:       "/workspace (Deep Agent Root)",
			Path:       sharedWorkspaceRoot,
			Group:      "workspace",
			FileCount:  rootCnt,
			TotalBytes: rootBytes,
		})
		for _, e := range entries {
			if !e.IsDir() || strings.HasPrefix(e.Name(), ".") || skipNames[e.Name()] {
				continue
			}
			full := filepath.Join(sharedWorkspaceRoot, e.Name())
			fc, tb := summarizeFolderQuick(full)
			folders = append(folders, sharedWorkspaceFolderInfo{
				Name:       e.Name(),
				Path:       full,
				Group:      "workspace",
				FileCount:  fc,
				TotalBytes: tb,
			})
		}
	}

	sharedDir := filepath.Join(sharedWorkspaceRoot, "shared")
	if entries, err := os.ReadDir(sharedDir); err == nil {
		for _, e := range entries {
			if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
				continue
			}
			full := filepath.Join(sharedDir, e.Name())
			fc, tb := summarizeFolderQuick(full)
			folders = append(folders, sharedWorkspaceFolderInfo{
				Name:       "shared/" + e.Name(),
				Path:       full,
				Group:      "shared",
				FileCount:  fc,
				TotalBytes: tb,
			})
		}
	}

	sort.SliceStable(folders, func(i, j int) bool {
		if folders[i].Group != folders[j].Group {
			return folders[i].Group == "shared"
		}
		return folders[i].Name < folders[j].Name
	})

	active := s.loadSharedContext()
	writeJSON(w, 200, map[string]any{
		"ok":                    true,
		"active_workspace_path": active.WorkspacePath,
		"folders":               folders,
	})
}

// attachChatWorkspace attaches an existing /workspace directory into a chat composer
// and syncs it into sharedWorkspaceContext so /chat and /ai stay aligned.
func (s *Server) attachChatWorkspace(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Path           string `json:"path"`
		ConversationID int64  `json:"conversation_id"`
	}
	if err := decode(r, &req); err != nil {
		writeErr(w, 400, "invalid JSON: "+err.Error())
		return
	}
	clean := filepath.Clean(strings.TrimSpace(req.Path))
	rootClean := filepath.Clean(sharedWorkspaceRoot)
	if clean != rootClean && !strings.HasPrefix(clean, rootClean+string(os.PathSeparator)) {
		writeErr(w, 400, "workspace path must be inside /workspace")
		return
	}
	info, err := os.Stat(clean)
	if err != nil || !info.IsDir() {
		writeErr(w, 404, "workspace folder not found: "+clean)
		return
	}
	fc, tb := summarizeFolderQuick(clean)
	label := filepath.Base(clean)
	if clean == rootClean {
		label = "workspace"
	}

	cur := s.loadSharedContext()
	cur.WorkspacePath = clean
	if req.ConversationID > 0 && cur.ConversationID == 0 {
		cur.ConversationID = req.ConversationID
	}
	cur.Source = "workspace_attach"
	_ = s.saveSharedContext(cur)

	att := chatAttachment{
		Name: fmt.Sprintf("📁 %s (%d files · shared /workspace)", label, fc),
		Path: clean,
		Size: tb,
		Abs:  clean,
	}
	writeJSON(w, 200, map[string]any{"ok": true, "attachment": att, "workspace_path": clean})
}

// uniqueUploadPath returns dir/name, or dir/name-1, dir/name-2… when it already exists.
func uniqueUploadPath(dir, name string) string {
	dest := filepath.Join(dir, name)
	if _, err := os.Stat(dest); os.IsNotExist(err) {
		return dest
	}
	ext := filepath.Ext(name)
	stem := strings.TrimSuffix(name, ext)
	for i := 1; ; i++ {
		cand := filepath.Join(dir, fmt.Sprintf("%s-%d%s", stem, i, ext))
		if _, err := os.Stat(cand); os.IsNotExist(err) {
			return cand
		}
	}
}

func previewDirectoryFiles(dirPath string, maxFiles int) []string {
	var out []string
	_ = filepath.WalkDir(dirPath, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			name := d.Name()
			if p != dirPath && (strings.HasPrefix(name, ".") || name == "node_modules" || name == "__pycache__" || name == "venv") {
				return filepath.SkipDir
			}
			return nil
		}
		if rel, rerr := filepath.Rel(dirPath, p); rerr == nil {
			out = append(out, filepath.ToSlash(rel))
		}
		if len(out) >= maxFiles {
			return fs.SkipAll
		}
		return nil
	})
	return out
}

// composeAgentMessage appends an attachment manifest (including directory trees for shared
// /workspace folders) so both Graph Chat and Deep Agent IDE know exact file locations.
func composeAgentMessage(msg string, atts []chatAttachment, baseDir string) string {
	if len(atts) == 0 {
		return msg
	}
	var b strings.Builder
	b.WriteString(msg)
	b.WriteString("\n\n[User-uploaded / Shared Workspace Attachments] (absolute paths; directly accessible via Read/Bash in both Graph Chat and Deep Agent IDE):")
	for _, a := range atts {
		resolved := a.Path
		if !filepath.IsAbs(resolved) {
			resolved = filepath.Join(baseDir, a.Path)
		}
		if info, err := os.Stat(resolved); err == nil && info.IsDir() {
			fmt.Fprintf(&b, "\n- Shared Folder: %s (%s)", resolved, humanBytes(a.Size))
			files := previewDirectoryFiles(resolved, 35)
			if len(files) > 0 {
				fmt.Fprintf(&b, "\n  Files inside %s:\n    • %s", resolved, strings.Join(files, "\n    • "))
			}
		} else {
			fmt.Fprintf(&b, "\n- %s (%s)", resolved, humanBytes(a.Size))
		}
	}
	return b.String()
}

func userActivityWithAttachments(worker, text string, atts []chatAttachment) db.Activity {
	a := db.Activity{Worker: worker, Kind: "user", Summary: text}
	if len(atts) > 0 {
		blob, _ := json.Marshal(map[string]any{"text": text, "attachments": atts})
		a.Detail = string(blob)
	}
	return a
}

func humanBytes(n int64) string {
	switch {
	case n >= 1<<20:
		return fmt.Sprintf("%.1f MB", float64(n)/(1<<20))
	case n >= 1<<10:
		return fmt.Sprintf("%.1f KB", float64(n)/(1<<10))
	default:
		return fmt.Sprintf("%d B", n)
	}
}
