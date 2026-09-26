package zfrog

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
)

// captured is one request the fake API received.
type captured struct {
	method string
	path   string
	query  url.Values
	header http.Header
	body   []byte
}

// api is a fake Zfrog API backed by a real HTTP server.
type api struct {
	*httptest.Server

	mu       sync.Mutex
	requests []captured
}

// newAPI starts the fake API and stops it when the test ends.
func newAPI(t *testing.T) *api {
	t.Helper()
	server := &api{}
	server.Server = httptest.NewServer(http.HandlerFunc(server.handle))
	t.Cleanup(server.Close)
	return server
}

// last returns the request the fake API handled most recently.
func (a *api) last(t *testing.T) captured {
	t.Helper()
	a.mu.Lock()
	defer a.mu.Unlock()
	if len(a.requests) == 0 {
		t.Fatal("the fake API received no request")
	}
	return a.requests[len(a.requests)-1]
}

// client builds a client pointed at the fake API.
func (a *api) client(t *testing.T, opts ...Option) *Client {
	t.Helper()
	return NewClient(a.URL, opts...)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

// decode reads the recorded body as JSON.
func decode(t *testing.T, raw []byte) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatalf("body %q is not a JSON object: %v", raw, err)
	}
	return decoded
}

var (
	zipBytes = []byte{0x50, 0x4b, 0x03, 0x04, 0xff, 0x00, 0x7f}
	pdfBytes = []byte{0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34}

	jobPayload = map[string]any{
		"id":          "job-1",
		"url":         "https://example.com",
		"mode":        "mirror",
		"max_depth":   3,
		"status":      "completed",
		"probe":       nil,
		"output_path": "/tmp/output/example.com",
		"created_at":  "2026-01-01T00:00:00",
		"updated_at":  "2026-01-01T00:01:00",
		"error":       nil,
	}

	jobResultPayload = map[string]any{
		"job_id": "job-1", "output_path": "/tmp/output/example.com", "files_count": 12,
		"total_size_bytes": 4096, "engine_used": "wget", "duration_seconds": 1.5,
	}

	probePayload = map[string]any{
		"url": "https://example.com", "is_spa": true, "has_js_rendering": true,
		"robots_restricted": false, "framework": "react", "content_type": "text/html",
		"suggested_engine": "playwright", "status_code": 200, "final_url": "https://example.com/",
	}

	snapshotPayload = map[string]any{
		"slug": "example.com", "file": "20260101.json", "url": "https://example.com",
		"captured_at": "2026-01-01T00:00:00", "pages": 3,
	}

	diffPayload = map[string]any{
		"url": "https://example.com", "a": "snap-a", "b": "snap-b",
		"added": []string{"new.html"}, "removed": []string{}, "changed": []string{"index.html"},
		"unchanged": []string{}, "change_ratio": 0.5, "details": []map[string]any{{"path": "index.html"}},
	}

	versionPayload = map[string]any{
		"id": "abcdef12", "url": "https://example.com", "snapshot": "snap-a",
		"captured_at": "2026-01-01T00:00:00", "message": "crawl", "parent": nil,
		"branch": "dev", "pages": 3, "files": map[string]string{"index.html": "deadbeef"},
	}

	schedulePayload = map[string]any{
		"id": "sched-1", "cron": "0 * * * *", "url": "https://example.com", "mode": "mirror",
		"max_depth": 1, "enabled": true, "last_run": nil, "next_run": "2026-01-01T01:00:00",
	}

	workflowPayload = map[string]any{
		"id": "wf-1", "name": "nightly",
		"steps": []map[string]any{{"id": "step-0", "type": "fetch", "params": map[string]any{"url": "https://example.com"}, "needs": []string{}}},
	}

	runResultPayload = map[string]any{
		"workflow_id": "wf-1", "status": "completed",
		"steps": []map[string]any{{"type": "fetch", "status": "ok", "detail": "", "output": "/tmp/output"}},
		"error": nil,
	}

	engineStatsPayload = map[string]any{
		"engine": "wget", "runs": 4, "succeeded": 3, "failed": 1, "success_rate": 0.75,
		"avg_duration_s": 2.5, "avg_bytes": 1024, "total_bytes": 4096, "avg_files": 3,
		"total_cost": 0.0, "avg_cost": 0.0,
	}

	totalsPayload = map[string]any{
		"runs": 4, "succeeded": 3, "failed": 1, "success_rate": 0.75, "bytes": 4096,
		"avg_duration_s": 2.5, "cost": 0.0, "currency": "USD",
	}

	auditPayload = map[string]any{
		"timestamp": "2026-01-01T00:00:00", "action": "job.create", "actor": "127.0.0.1",
		"target": "https://example.com", "outcome": "ok", "detail": "",
		"metadata": map[string]any{"mode": "mirror"},
	}
)

// handle answers the documented endpoints and records every request.
func (a *api) handle(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	a.mu.Lock()
	a.requests = append(a.requests, captured{
		method: r.Method,
		path:   r.URL.Path,
		query:  r.URL.Query(),
		header: r.Header.Clone(),
		body:   body,
	})
	a.mu.Unlock()

	switch {
	case r.URL.Path == "/health":
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	case r.URL.Path == "/jobs" && r.Method == http.MethodPost:
		var input CreateJobInput
		if err := json.Unmarshal(body, &input); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": err.Error()})
			return
		}
		maxDepth := 3
		if input.MaxDepth != nil {
			maxDepth = *input.MaxDepth
		}
		writeJSON(w, http.StatusCreated, map[string]any{
			"id": "job-1", "url": input.URL, "mode": input.Mode, "max_depth": maxDepth,
			"status": "completed", "probe": nil, "output_path": "/tmp/output/example.com",
			"created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:01:00", "error": nil,
		})
	case r.URL.Path == "/jobs" && r.Method == http.MethodGet:
		writeJSON(w, http.StatusOK, []map[string]any{jobPayload})
	case r.URL.Path == "/jobs/job-1":
		writeJSON(w, http.StatusOK, jobPayload)
	case r.URL.Path == "/jobs/job-1/cancel":
		writeJSON(w, http.StatusOK, map[string]string{"message": "Job job-1 marked for cancellation"})
	case r.URL.Path == "/jobs/job-1/result":
		writeJSON(w, http.StatusOK, jobResultPayload)
	case r.URL.Path == "/jobs/job-1/download":
		w.Header().Set("Content-Type", "application/zip")
		_, _ = w.Write(zipBytes)
	case r.URL.Path == "/jobs/job-1/pdf":
		w.Header().Set("Content-Type", "application/pdf")
		_, _ = w.Write(pdfBytes)
	case strings.HasPrefix(r.URL.Path, "/probe/"):
		writeJSON(w, http.StatusOK, map[string]any{
			"url": strings.TrimPrefix(r.URL.Path, "/probe/"), "is_spa": true, "has_js_rendering": true,
			"robots_restricted": false, "framework": "react", "content_type": "text/html",
			"suggested_engine": "playwright", "status_code": 200, "final_url": "https://example.com/",
		})
	case r.URL.Path == "/snapshots":
		writeJSON(w, http.StatusOK, []map[string]any{snapshotPayload})
	case r.URL.Path == "/diff":
		var input map[string]string
		_ = json.Unmarshal(body, &input)
		echo := map[string]any{}
		for key, value := range diffPayload {
			echo[key] = value
		}
		echo["a"], echo["b"] = input["a"], input["b"]
		writeJSON(w, http.StatusOK, echo)
	case r.URL.Path == "/versions":
		echo := map[string]any{}
		for key, value := range versionPayload {
			echo[key] = value
		}
		echo["url"] = r.URL.Query().Get("url")
		echo["branch"] = r.URL.Query().Get("branch")
		writeJSON(w, http.StatusOK, map[string]any{
			"url": r.URL.Query().Get("url"), "branch": r.URL.Query().Get("branch"),
			"branches": []string{"main", "dev"}, "versions": []map[string]any{echo},
		})
	case r.URL.Path == "/versions/rollback":
		writeJSON(w, http.StatusOK, map[string]any{"restored": "/tmp/versions/example.com", "files": 7})
	case r.URL.Path == "/search":
		var input SearchInput
		_ = json.Unmarshal(body, &input)
		writeJSON(w, http.StatusOK, map[string]any{
			"query": input.Query, "mode": input.Mode,
			"hits": []map[string]any{{"path": "index.html", "url": "https://example.com", "title": "Home", "snippet": "hello world", "score": 0.9}},
		})
	case r.URL.Path == "/schedules" && r.Method == http.MethodGet:
		writeJSON(w, http.StatusOK, []map[string]any{schedulePayload})
	case r.URL.Path == "/schedules" && r.Method == http.MethodPost:
		var input ScheduleInput
		_ = json.Unmarshal(body, &input)
		maxDepth := 1
		if input.MaxDepth != nil {
			maxDepth = *input.MaxDepth
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"id": "sched-1", "cron": input.Cron, "url": input.URL, "mode": input.Mode,
			"max_depth": maxDepth, "enabled": true, "last_run": nil, "next_run": nil,
		})
	case r.URL.Path == "/schedules/sched-1" && r.Method == http.MethodDelete:
		writeJSON(w, http.StatusOK, map[string]string{"removed": "sched-1"})
	case r.URL.Path == "/schedules/sched-1/run":
		writeJSON(w, http.StatusOK, map[string]string{"job_id": "job-1"})
	case r.URL.Path == "/workflows" && r.Method == http.MethodGet:
		writeJSON(w, http.StatusOK, []map[string]any{workflowPayload})
	case r.URL.Path == "/workflows" && r.Method == http.MethodPost:
		var input struct {
			Name  string         `json:"name"`
			Steps []WorkflowStep `json:"steps"`
		}
		_ = json.Unmarshal(body, &input)
		writeJSON(w, http.StatusOK, map[string]any{"id": "wf-1", "name": input.Name, "steps": input.Steps})
	case r.URL.Path == "/workflows/wf-1/run":
		writeJSON(w, http.StatusOK, runResultPayload)
	case r.URL.Path == "/analytics/engines":
		writeJSON(w, http.StatusOK, []map[string]any{engineStatsPayload})
	case r.URL.Path == "/analytics/totals":
		writeJSON(w, http.StatusOK, totalsPayload)
	case r.URL.Path == "/audit":
		writeJSON(w, http.StatusOK, []map[string]any{auditPayload})
	case r.URL.Path == "/stats":
		writeJSON(w, http.StatusOK, map[string]any{
			"total_jobs": 7, "completed": 5, "failed": 1, "running": 1,
			"concurrent_slots_available": 3, "rate_limit_rps": 10.0,
		})
	case r.URL.Path == "/safety/scan":
		writeJSON(w, http.StatusOK, map[string]any{
			"files_scanned": 2,
			"findings": []map[string]any{{
				"kind": "hidden_iframe", "severity": "high",
				"file": "/tmp/output/example.com/index.html", "detail": "hidden iframe",
				"evidence": "<iframe hidden",
			}},
			"risk": "high", "summary": "1 finding",
		})
	case r.URL.Path == "/ipfs/publish":
		writeJSON(w, http.StatusOK, map[string]any{
			"cid": "bafybeigdyrzt", "name": "example.com", "size": 4096, "files": 12,
			"gateway_url": "https://ipfs.io/ipfs/bafybeigdyrzt",
		})
	default:
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Job not found"})
	}
}

func TestCreateJobSendsJSONAndDecodes(t *testing.T) {
	server := newAPI(t)
	maxDepth := 2

	job, err := server.client(t).CreateJob(context.Background(), CreateJobInput{
		URL:      "https://example.com",
		Mode:     "singlepage",
		MaxDepth: &maxDepth,
	})
	if err != nil {
		t.Fatalf("CreateJob: %v", err)
	}

	request := server.last(t)
	if request.method != http.MethodPost {
		t.Fatalf("method = %s, want POST", request.method)
	}
	if request.path != "/jobs" {
		t.Fatalf("path = %s, want /jobs", request.path)
	}
	if got := request.header.Get("Content-Type"); got != "application/json" {
		t.Fatalf("Content-Type = %q, want application/json", got)
	}
	if got := decode(t, request.body); got["url"] != "https://example.com" || got["mode"] != "singlepage" || got["max_depth"] != float64(2) {
		t.Fatalf("body = %v, want url/mode/max_depth echoed", got)
	}

	if job.ID != "job-1" {
		t.Fatalf("job.ID = %q, want job-1", job.ID)
	}
	if job.URL != "https://example.com" || job.Mode != "singlepage" || job.MaxDepth != 2 {
		t.Fatalf("job = %+v, want the echoed url/mode/max_depth", job)
	}
	if job.Status != "completed" {
		t.Fatalf("job.Status = %q, want completed", job.Status)
	}
	if job.OutputPath == nil || *job.OutputPath != "/tmp/output/example.com" {
		t.Fatalf("job.OutputPath = %v, want /tmp/output/example.com", job.OutputPath)
	}
	if job.Error != nil {
		t.Fatalf("job.Error = %v, want nil", *job.Error)
	}
}

func TestCreateJobOmitsUnsetOptionalFields(t *testing.T) {
	server := newAPI(t)

	if _, err := server.client(t).CreateJob(context.Background(), CreateJobInput{URL: "https://example.com", Mode: "mirror"}); err != nil {
		t.Fatalf("CreateJob: %v", err)
	}

	body := decode(t, server.last(t).body)
	if len(body) != 2 {
		t.Fatalf("body = %v, want only url and mode", body)
	}
	if _, present := body["max_depth"]; present {
		t.Fatalf("body = %v, want no max_depth key", body)
	}
}

func TestAPIKeyIsSentAsBearerToken(t *testing.T) {
	server := newAPI(t)

	if _, err := server.client(t, WithAPIKey("s3cret-key")).Health(context.Background()); err != nil {
		t.Fatalf("Health: %v", err)
	}
	if got := server.last(t).header.Get("Authorization"); got != "Bearer s3cret-key" {
		t.Fatalf("Authorization = %q, want Bearer s3cret-key", got)
	}

	if _, err := server.client(t).Health(context.Background()); err != nil {
		t.Fatalf("Health: %v", err)
	}
	if got := server.last(t).header.Get("Authorization"); got != "" {
		t.Fatalf("Authorization = %q, want empty without WithAPIKey", got)
	}
}

func TestNotFoundBecomesAPIError(t *testing.T) {
	server := newAPI(t)

	job, err := server.client(t).GetJob(context.Background(), "missing")
	if err == nil {
		t.Fatalf("GetJob = %+v, want an error", job)
	}

	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("error %v (%T) is not an *APIError", err, err)
	}
	if apiErr.StatusCode != http.StatusNotFound {
		t.Fatalf("StatusCode = %d, want 404", apiErr.StatusCode)
	}
	if apiErr.Detail != "Job not found" {
		t.Fatalf("Detail = %q, want Job not found", apiErr.Detail)
	}
	if !strings.Contains(apiErr.Error(), "Job not found") {
		t.Fatalf("Error() = %q, want it to mention the detail", apiErr.Error())
	}
}

func TestTransportErrorIsReturned(t *testing.T) {
	server := newAPI(t)
	closedURL := server.URL
	server.Close()

	health, err := NewClient(closedURL).Health(context.Background())
	if err == nil {
		t.Fatalf("Health = %+v, want an error from the closed server", health)
	}

	var apiErr *APIError
	if errors.As(err, &apiErr) {
		t.Fatalf("error %v is an *APIError, want a wrapped transport error", err)
	}
	if !strings.Contains(err.Error(), closedURL) {
		t.Fatalf("error %q does not name the unreachable server", err)
	}
}

func TestContextCancellationPropagates(t *testing.T) {
	server := newAPI(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	health, err := server.client(t).Health(ctx)
	if err == nil {
		t.Fatalf("Health = %+v, want an error from the cancelled context", health)
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error %v does not wrap context.Canceled", err)
	}
}

func TestDownloadZipReturnsRawBytes(t *testing.T) {
	server := newAPI(t)

	got, err := server.client(t).DownloadZip(context.Background(), "job-1")
	if err != nil {
		t.Fatalf("DownloadZip: %v", err)
	}
	if len(got) != len(zipBytes) || !bytes.Equal(got, zipBytes) {
		t.Fatalf("DownloadZip = %v, want the raw bytes %v", got, zipBytes)
	}
	if path := server.last(t).path; path != "/jobs/job-1/download" {
		t.Fatalf("path = %s, want /jobs/job-1/download", path)
	}

	pdf, err := server.client(t).GetJobPDF(context.Background(), "job-1")
	if err != nil {
		t.Fatalf("GetJobPDF: %v", err)
	}
	if !bytes.Equal(pdf, pdfBytes) {
		t.Fatalf("GetJobPDF = %v, want %v", pdf, pdfBytes)
	}
}

func TestNewClientDefaultsBaseURL(t *testing.T) {
	server := newAPI(t)
	dialed := make(chan string, 1)
	dialer := &net.Dialer{}

	client := NewClient("", WithHTTPClient(&http.Client{
		Transport: &http.Transport{
			DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
				select {
				case dialed <- addr:
				default:
				}
				return dialer.DialContext(ctx, network, server.Listener.Addr().String())
			},
		},
	}))

	if _, err := client.Health(context.Background()); err != nil {
		t.Fatalf("Health: %v", err)
	}

	select {
	case addr := <-dialed:
		if addr != "localhost:8000" {
			t.Fatalf("dialed %q, want localhost:8000", addr)
		}
	default:
		t.Fatal("the client dialed nothing")
	}
	if path := server.last(t).path; path != "/health" {
		t.Fatalf("path = %s, want /health", path)
	}
}

func TestWithHTTPClientIsUsed(t *testing.T) {
	server := newAPI(t)
	transport := &countingTransport{inner: http.DefaultTransport}

	if _, err := server.client(t, WithHTTPClient(&http.Client{Transport: transport})).Health(context.Background()); err != nil {
		t.Fatalf("Health: %v", err)
	}
	if transport.calls != 1 {
		t.Fatalf("transport calls = %d, want 1", transport.calls)
	}
}

// countingTransport counts how many requests went through it.
type countingTransport struct {
	inner http.RoundTripper
	calls int
}

// RoundTrip implements http.RoundTripper.
func (c *countingTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	c.calls++
	return c.inner.RoundTrip(request)
}

func TestEndpointsUseTheDocumentedRequests(t *testing.T) {
	server := newAPI(t)
	client := server.client(t)
	ctx := context.Background()

	tests := []struct {
		name   string
		call   func() error
		method string
		path   string
		query  map[string]string
	}{
		{
			name:   "Health",
			call:   func() error { _, err := client.Health(ctx); return err },
			method: http.MethodGet, path: "/health",
		},
		{
			name:   "ListJobs",
			call:   func() error { _, err := client.ListJobs(ctx); return err },
			method: http.MethodGet, path: "/jobs",
		},
		{
			name:   "GetJob",
			call:   func() error { _, err := client.GetJob(ctx, "job-1"); return err },
			method: http.MethodGet, path: "/jobs/job-1",
		},
		{
			name:   "CancelJob",
			call:   func() error { _, err := client.CancelJob(ctx, "job-1"); return err },
			method: http.MethodPost, path: "/jobs/job-1/cancel",
		},
		{
			name:   "GetJobResult",
			call:   func() error { _, err := client.GetJobResult(ctx, "job-1"); return err },
			method: http.MethodGet, path: "/jobs/job-1/result",
		},
		{
			name:   "Probe",
			call:   func() error { _, err := client.Probe(ctx, "https://example.com/a?b=1"); return err },
			method: http.MethodGet, path: "/probe/https://example.com/a?b=1",
		},
		{
			name:   "ListSnapshots with url",
			call:   func() error { _, err := client.ListSnapshots(ctx, "https://example.com"); return err },
			method: http.MethodGet, path: "/snapshots",
			query: map[string]string{"url": "https://example.com"},
		},
		{
			name:   "ListSnapshots without url",
			call:   func() error { _, err := client.ListSnapshots(ctx, ""); return err },
			method: http.MethodGet, path: "/snapshots",
		},
		{
			name:   "Diff",
			call:   func() error { _, err := client.Diff(ctx, "snap-a", "snap-b"); return err },
			method: http.MethodPost, path: "/diff",
		},
		{
			name:   "GetVersions with branch",
			call:   func() error { _, err := client.GetVersions(ctx, "https://example.com", "dev"); return err },
			method: http.MethodGet, path: "/versions",
			query: map[string]string{"url": "https://example.com", "branch": "dev"},
		},
		{
			name:   "GetVersions without branch",
			call:   func() error { _, err := client.GetVersions(ctx, "https://example.com", ""); return err },
			method: http.MethodGet, path: "/versions",
			query: map[string]string{"url": "https://example.com"},
		},
		{
			name:   "Rollback",
			call:   func() error { _, err := client.Rollback(ctx, "https://example.com", "abcdef12"); return err },
			method: http.MethodPost, path: "/versions/rollback",
		},
		{
			name:   "Search",
			call:   func() error { _, err := client.Search(ctx, SearchInput{Query: "hello", Mode: "semantic"}); return err },
			method: http.MethodPost, path: "/search",
		},
		{
			name:   "ListSchedules",
			call:   func() error { _, err := client.ListSchedules(ctx); return err },
			method: http.MethodGet, path: "/schedules",
		},
		{
			name: "CreateSchedule",
			call: func() error {
				_, err := client.CreateSchedule(ctx, ScheduleInput{Cron: "*/5 * * * *", URL: "https://example.com", Mode: "scrape"})
				return err
			},
			method: http.MethodPost, path: "/schedules",
		},
		{
			name:   "DeleteSchedule",
			call:   func() error { _, err := client.DeleteSchedule(ctx, "sched-1"); return err },
			method: http.MethodDelete, path: "/schedules/sched-1",
		},
		{
			name:   "RunSchedule",
			call:   func() error { _, err := client.RunSchedule(ctx, "sched-1"); return err },
			method: http.MethodPost, path: "/schedules/sched-1/run",
		},
		{
			name:   "ListWorkflows",
			call:   func() error { _, err := client.ListWorkflows(ctx); return err },
			method: http.MethodGet, path: "/workflows",
		},
		{
			name: "SaveWorkflow",
			call: func() error {
				_, err := client.SaveWorkflow(ctx, "nightly", []WorkflowStep{{Type: "fetch", Params: map[string]any{"url": "https://example.com"}}})
				return err
			},
			method: http.MethodPost, path: "/workflows",
		},
		{
			name:   "RunWorkflow",
			call:   func() error { _, err := client.RunWorkflow(ctx, "wf-1"); return err },
			method: http.MethodPost, path: "/workflows/wf-1/run",
		},
		{
			name:   "EngineStats with engine",
			call:   func() error { _, err := client.EngineStats(ctx, "wget"); return err },
			method: http.MethodGet, path: "/analytics/engines",
			query: map[string]string{"engine": "wget"},
		},
		{
			name:   "EngineStats without engine",
			call:   func() error { _, err := client.EngineStats(ctx, ""); return err },
			method: http.MethodGet, path: "/analytics/engines",
		},
		{
			name:   "Totals",
			call:   func() error { _, err := client.Totals(ctx); return err },
			method: http.MethodGet, path: "/analytics/totals",
		},
		{
			name:   "Audit with limit",
			call:   func() error { _, err := client.Audit(ctx, 5); return err },
			method: http.MethodGet, path: "/audit",
			query: map[string]string{"limit": "5"},
		},
		{
			name:   "Audit without limit",
			call:   func() error { _, err := client.Audit(ctx, 0); return err },
			method: http.MethodGet, path: "/audit",
		},
		{
			name:   "Stats",
			call:   func() error { _, err := client.Stats(ctx); return err },
			method: http.MethodGet, path: "/stats",
		},
		{
			name:   "ScanSafety",
			call:   func() error { _, err := client.ScanSafety(ctx, "/tmp/output/example.com"); return err },
			method: http.MethodPost, path: "/safety/scan",
		},
		{
			name:   "PublishIPFS",
			call:   func() error { _, err := client.PublishIPFS(ctx, "/tmp/output/example.com"); return err },
			method: http.MethodPost, path: "/ipfs/publish",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := test.call(); err != nil {
				t.Fatalf("%s: %v", test.name, err)
			}

			request := server.last(t)
			if request.method != test.method {
				t.Fatalf("method = %s, want %s", request.method, test.method)
			}
			if request.path != test.path {
				t.Fatalf("path = %s, want %s", request.path, test.path)
			}
			if len(request.query) != len(test.query) {
				t.Fatalf("query = %v, want %v", request.query, test.query)
			}
			for key, value := range test.query {
				if got := request.query.Get(key); got != value {
					t.Fatalf("query %s = %q, want %q", key, got, value)
				}
			}
		})
	}
}

func TestResponsesAreDecoded(t *testing.T) {
	server := newAPI(t)
	client := server.client(t)
	ctx := context.Background()

	jobs, err := client.ListJobs(ctx)
	if err != nil {
		t.Fatalf("ListJobs: %v", err)
	}
	if len(jobs) != 1 || jobs[0].ID != "job-1" || jobs[0].MaxDepth != 3 || jobs[0].Probe != nil {
		t.Fatalf("ListJobs = %+v, want the canned job", jobs)
	}

	result, err := client.GetJobResult(ctx, "job-1")
	if err != nil {
		t.Fatalf("GetJobResult: %v", err)
	}
	if result.FilesCount != 12 || result.TotalSizeBytes != 4096 || result.EngineUsed != "wget" || result.DurationSeconds != 1.5 {
		t.Fatalf("GetJobResult = %+v, want the canned result", result)
	}

	probe, err := client.Probe(ctx, "https://example.com")
	if err != nil {
		t.Fatalf("Probe: %v", err)
	}
	if !probe.IsSPA || probe.SuggestedEngine != "playwright" || probe.Framework == nil || *probe.Framework != "react" {
		t.Fatalf("Probe = %+v, want the canned probe", probe)
	}

	snapshots, err := client.ListSnapshots(ctx, "")
	if err != nil {
		t.Fatalf("ListSnapshots: %v", err)
	}
	if len(snapshots) != 1 || snapshots[0].Slug != "example.com" || snapshots[0].Pages != 3 {
		t.Fatalf("ListSnapshots = %+v, want the canned snapshot", snapshots)
	}

	report, err := client.Diff(ctx, "snap-a", "snap-b")
	if err != nil {
		t.Fatalf("Diff: %v", err)
	}
	if report.A != "snap-a" || report.B != "snap-b" || len(report.Added) != 1 || report.ChangeRatio != 0.5 {
		t.Fatalf("Diff = %+v, want the canned report", report)
	}

	log, err := client.GetVersions(ctx, "https://example.com", "dev")
	if err != nil {
		t.Fatalf("GetVersions: %v", err)
	}
	if log.Branch != "dev" || len(log.Branches) != 2 || len(log.Versions) != 1 || log.Versions[0].ID != "abcdef12" {
		t.Fatalf("GetVersions = %+v, want the canned log", log)
	}
	if log.Versions[0].Parent != nil {
		t.Fatalf("Parent = %v, want nil", *log.Versions[0].Parent)
	}
	if got := log.Versions[0].Files["index.html"]; got != "deadbeef" {
		t.Fatalf("files[index.html] = %q, want deadbeef", got)
	}

	rollback, err := client.Rollback(ctx, "https://example.com", "abcdef12")
	if err != nil {
		t.Fatalf("Rollback: %v", err)
	}
	if rollback.Files != 7 || rollback.Restored != "/tmp/versions/example.com" {
		t.Fatalf("Rollback = %+v, want the canned result", rollback)
	}
	if body := decode(t, server.last(t).body); body["url"] != "https://example.com" || body["ref"] != "abcdef12" {
		t.Fatalf("rollback body = %v, want url and ref", body)
	}

	search, err := client.Search(ctx, SearchInput{Query: "hello", Mode: "semantic"})
	if err != nil {
		t.Fatalf("Search: %v", err)
	}
	if search.Mode != "semantic" || len(search.Hits) != 1 || search.Hits[0].Path != "index.html" || search.Hits[0].Score != 0.9 {
		t.Fatalf("Search = %+v, want the canned response", search)
	}

	schedules, err := client.ListSchedules(ctx)
	if err != nil {
		t.Fatalf("ListSchedules: %v", err)
	}
	if len(schedules) != 1 || schedules[0].Cron != "0 * * * *" || schedules[0].LastRun != nil {
		t.Fatalf("ListSchedules = %+v, want the canned schedule", schedules)
	}

	maxDepth := 2
	created, err := client.CreateSchedule(ctx, ScheduleInput{Cron: "*/5 * * * *", URL: "https://example.com", Mode: "scrape", MaxDepth: &maxDepth})
	if err != nil {
		t.Fatalf("CreateSchedule: %v", err)
	}
	if created.Cron != "*/5 * * * *" || created.Mode != "scrape" || created.MaxDepth != 2 {
		t.Fatalf("CreateSchedule = %+v, want the echoed schedule", created)
	}

	removed, err := client.DeleteSchedule(ctx, "sched-1")
	if err != nil {
		t.Fatalf("DeleteSchedule: %v", err)
	}
	if removed.Removed != "sched-1" {
		t.Fatalf("DeleteSchedule = %+v, want removed sched-1", removed)
	}

	run, err := client.RunSchedule(ctx, "sched-1")
	if err != nil {
		t.Fatalf("RunSchedule: %v", err)
	}
	if run.JobID != "job-1" {
		t.Fatalf("RunSchedule = %+v, want job-1", run)
	}

	workflows, err := client.ListWorkflows(ctx)
	if err != nil {
		t.Fatalf("ListWorkflows: %v", err)
	}
	if len(workflows) != 1 || workflows[0].Name != "nightly" || workflows[0].Steps[0].Type != "fetch" {
		t.Fatalf("ListWorkflows = %+v, want the canned workflow", workflows)
	}

	saved, err := client.SaveWorkflow(ctx, "nightly", []WorkflowStep{{Type: "fetch", Params: map[string]any{"url": "https://example.com"}}})
	if err != nil {
		t.Fatalf("SaveWorkflow: %v", err)
	}
	if saved.Name != "nightly" || len(saved.Steps) != 1 {
		t.Fatalf("SaveWorkflow = %+v, want the saved workflow", saved)
	}
	if body := decode(t, server.last(t).body); body["name"] != "nightly" {
		t.Fatalf("workflow body = %v, want the name", body)
	}

	workflowRun, err := client.RunWorkflow(ctx, "wf-1")
	if err != nil {
		t.Fatalf("RunWorkflow: %v", err)
	}
	if workflowRun.Status != "completed" || len(workflowRun.Steps) != 1 || workflowRun.Steps[0].Status != "ok" || workflowRun.Error != nil {
		t.Fatalf("RunWorkflow = %+v, want the canned run", workflowRun)
	}

	stats, err := client.EngineStats(ctx, "")
	if err != nil {
		t.Fatalf("EngineStats: %v", err)
	}
	if len(stats) != 1 || stats[0].Engine != "wget" || stats[0].SuccessRate != 0.75 || stats[0].TotalBytes != 4096 {
		t.Fatalf("EngineStats = %+v, want the canned stats", stats)
	}

	totals, err := client.Totals(ctx)
	if err != nil {
		t.Fatalf("Totals: %v", err)
	}
	if totals.Runs != 4 || totals.Succeeded != 3 || totals.Currency != "USD" {
		t.Fatalf("Totals = %+v, want the canned totals", totals)
	}

	audit, err := client.Audit(ctx, 5)
	if err != nil {
		t.Fatalf("Audit: %v", err)
	}
	if len(audit) != 1 || audit[0].Action != "job.create" || audit[0].Metadata["mode"] != "mirror" {
		t.Fatalf("Audit = %+v, want the canned entry", audit)
	}

	cancelled, err := client.CancelJob(ctx, "job-1")
	if err != nil {
		t.Fatalf("CancelJob: %v", err)
	}
	if !strings.Contains(cancelled.Message, "cancellation") {
		t.Fatalf("CancelJob = %+v, want the cancellation message", cancelled)
	}

	systemStats, err := client.Stats(ctx)
	if err != nil {
		t.Fatalf("Stats: %v", err)
	}
	if systemStats.TotalJobs != 7 || systemStats.Running != 1 || systemStats.ConcurrentSlotsAvailable != 3 || systemStats.RateLimitRPS != 10 {
		t.Fatalf("Stats = %+v, want the canned stats", systemStats)
	}

	safety, err := client.ScanSafety(ctx, "/tmp/output/example.com")
	if err != nil {
		t.Fatalf("ScanSafety: %v", err)
	}
	if safety.Risk != "high" || safety.FilesScanned != 2 || len(safety.Findings) != 1 {
		t.Fatalf("ScanSafety = %+v, want the canned report", safety)
	}
	if safety.Findings[0].Severity != "high" || safety.Findings[0].Kind != "hidden_iframe" {
		t.Fatalf("ScanSafety finding = %+v, want the canned finding", safety.Findings[0])
	}
	if body := decode(t, server.last(t).body); body["dir"] != "/tmp/output/example.com" {
		t.Fatalf("safety body = %v, want dir", body)
	}

	published, err := client.PublishIPFS(ctx, "/tmp/output/example.com")
	if err != nil {
		t.Fatalf("PublishIPFS: %v", err)
	}
	if published.CID != "bafybeigdyrzt" || published.Size != 4096 || published.Files != 12 {
		t.Fatalf("PublishIPFS = %+v, want the canned publication", published)
	}
	if !strings.Contains(published.GatewayURL, published.CID) {
		t.Fatalf("GatewayURL = %q, want it to contain the CID", published.GatewayURL)
	}
	if body := decode(t, server.last(t).body); body["dir"] != "/tmp/output/example.com" {
		t.Fatalf("ipfs body = %v, want dir", body)
	}
}

func TestBaseURLKeepsNoTrailingSlash(t *testing.T) {
	server := newAPI(t)

	client := NewClient(server.URL + "/")
	if _, err := client.Health(context.Background()); err != nil {
		t.Fatalf("Health: %v", err)
	}
	if path := server.last(t).path; path != "/health" {
		t.Fatalf("path = %s, want /health", path)
	}
}
