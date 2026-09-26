// Package zfrog is the official Go client for the Zfrog REST API.
//
//	client := zfrog.NewClient("http://localhost:8000", zfrog.WithAPIKey("..."))
//	job, err := client.CreateJob(ctx, zfrog.CreateJobInput{URL: "https://example.com", Mode: "mirror"})
//	if err != nil {
//		return err
//	}
//	zip, err := client.DownloadZip(ctx, job.ID)
//
// Every method performs one real HTTP call and returns the decoded payload. A
// non-2xx response becomes an [*APIError]; a transport failure is returned as
// the underlying error wrapped, so [errors.Is] still finds context errors.
package zfrog

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// Health is the payload of GET /health.
type Health struct {
	Status string `json:"status"`
}

// Job is a crawl/extraction job, as returned by every /jobs endpoint.
type Job struct {
	ID         string       `json:"id"`
	URL        string       `json:"url"`
	Mode       string       `json:"mode"`
	MaxDepth   int          `json:"max_depth"`
	Status     string       `json:"status"`
	Probe      *ProbeResult `json:"probe"`
	OutputPath *string      `json:"output_path"`
	CreatedAt  string       `json:"created_at"`
	UpdatedAt  string       `json:"updated_at"`
	Error      *string      `json:"error"`
}

// CreateJobInput is the body of POST /jobs. The optional fields are pointers so
// that a zero value stays distinguishable from "not sent".
type CreateJobInput struct {
	URL         string  `json:"url"`
	Mode        string  `json:"mode"`
	MaxDepth    *int    `json:"max_depth,omitempty"`
	PDFFilename *string `json:"pdf_filename,omitempty"`
	Versioned   *bool   `json:"versioned,omitempty"`
}

// JobResult is the payload of GET /jobs/{id}/result.
type JobResult struct {
	JobID           string  `json:"job_id"`
	OutputPath      string  `json:"output_path"`
	FilesCount      int     `json:"files_count"`
	TotalSizeBytes  int64   `json:"total_size_bytes"`
	EngineUsed      string  `json:"engine_used"`
	DurationSeconds float64 `json:"duration_seconds"`
}

// ProbeResult is the payload of GET /probe/{url}.
type ProbeResult struct {
	URL              string  `json:"url"`
	IsSPA            bool    `json:"is_spa"`
	HasJSRendering   bool    `json:"has_js_rendering"`
	RobotsRestricted bool    `json:"robots_restricted"`
	Framework        *string `json:"framework"`
	ContentType      string  `json:"content_type"`
	SuggestedEngine  string  `json:"suggested_engine"`
	StatusCode       *int    `json:"status_code"`
	FinalURL         *string `json:"final_url"`
}

// SnapshotEntry is one entry of GET /snapshots.
type SnapshotEntry struct {
	Slug       string `json:"slug"`
	File       string `json:"file"`
	URL        string `json:"url"`
	CapturedAt string `json:"captured_at"`
	Pages      int    `json:"pages"`
}

// DiffReport is the payload of POST /diff.
type DiffReport struct {
	URL         string           `json:"url"`
	A           string           `json:"a"`
	B           string           `json:"b"`
	Added       []string         `json:"added"`
	Removed     []string         `json:"removed"`
	Changed     []string         `json:"changed"`
	Unchanged   []string         `json:"unchanged"`
	ChangeRatio float64          `json:"change_ratio"`
	Details     []map[string]any `json:"details"`
}

// Version is a single saved version of a site.
type Version struct {
	ID         string            `json:"id"`
	URL        string            `json:"url"`
	Snapshot   string            `json:"snapshot"`
	CapturedAt string            `json:"captured_at"`
	Message    string            `json:"message"`
	Parent     *string           `json:"parent"`
	Branch     string            `json:"branch"`
	Pages      int               `json:"pages"`
	Files      map[string]string `json:"files"`
}

// VersionLog is the payload of GET /versions.
type VersionLog struct {
	URL      string    `json:"url"`
	Branch   string    `json:"branch"`
	Branches []string  `json:"branches"`
	Versions []Version `json:"versions"`
}

// RollbackResult is the payload of POST /versions/rollback.
type RollbackResult struct {
	Restored string `json:"restored"`
	Files    int    `json:"files"`
}

// SearchInput is the body of POST /search.
type SearchInput struct {
	Query string `json:"query"`
	Mode  string `json:"mode"`
	Dir   string `json:"dir,omitempty"`
}

// SearchHit is one search result.
type SearchHit struct {
	Path    string  `json:"path"`
	URL     string  `json:"url"`
	Title   string  `json:"title"`
	Snippet string  `json:"snippet"`
	Score   float64 `json:"score"`
}

// SearchResponse is the payload of POST /search.
type SearchResponse struct {
	Query string      `json:"query"`
	Mode  string      `json:"mode"`
	Hits  []SearchHit `json:"hits"`
}

// Schedule is a recurring job definition.
type Schedule struct {
	ID       string  `json:"id"`
	Cron     string  `json:"cron"`
	URL      string  `json:"url"`
	Mode     string  `json:"mode"`
	MaxDepth int     `json:"max_depth"`
	Enabled  bool    `json:"enabled"`
	LastRun  *string `json:"last_run"`
	NextRun  *string `json:"next_run"`
}

// ScheduleInput is the body of POST /schedules.
type ScheduleInput struct {
	Cron     string `json:"cron"`
	URL      string `json:"url"`
	Mode     string `json:"mode"`
	MaxDepth *int   `json:"max_depth,omitempty"`
}

// ScheduleRun is the payload of POST /schedules/{id}/run.
type ScheduleRun struct {
	JobID string `json:"job_id"`
}

// WorkflowStep is one step of a pipeline; ID and Needs are filled by the API
// when the caller leaves them out.
type WorkflowStep struct {
	Type   string         `json:"type"`
	Params map[string]any `json:"params,omitempty"`
	Needs  []string       `json:"needs,omitempty"`
	ID     string         `json:"id,omitempty"`
}

// Workflow is a named pipeline of steps.
type Workflow struct {
	ID    string         `json:"id"`
	Name  string         `json:"name"`
	Steps []WorkflowStep `json:"steps"`
}

// StepResult is the outcome of a single step inside a run.
type StepResult struct {
	Type   string  `json:"type"`
	Status string  `json:"status"`
	Detail string  `json:"detail"`
	Output *string `json:"output"`
}

// RunResult is the payload of POST /workflows/{id}/run.
type RunResult struct {
	WorkflowID string       `json:"workflow_id"`
	Status     string       `json:"status"`
	Steps      []StepResult `json:"steps"`
	Error      *string      `json:"error"`
}

// EngineStats is the aggregated performance of a single engine.
type EngineStats struct {
	Engine      string  `json:"engine"`
	Runs        int     `json:"runs"`
	Succeeded   int     `json:"succeeded"`
	Failed      int     `json:"failed"`
	SuccessRate float64 `json:"success_rate"`
	AvgDuration float64 `json:"avg_duration_s"`
	AvgBytes    float64 `json:"avg_bytes"`
	TotalBytes  int64   `json:"total_bytes"`
	AvgFiles    float64 `json:"avg_files"`
	TotalCost   float64 `json:"total_cost"`
	AvgCost     float64 `json:"avg_cost"`
}

// Totals is the payload of GET /analytics/totals.
type Totals struct {
	Runs        int     `json:"runs"`
	Succeeded   int     `json:"succeeded"`
	Failed      int     `json:"failed"`
	SuccessRate float64 `json:"success_rate"`
	Bytes       int64   `json:"bytes"`
	AvgDuration float64 `json:"avg_duration_s"`
	Cost        float64 `json:"cost"`
	Currency    string  `json:"currency"`
}

// AuditEntry is one recorded action of the audit trail.
type AuditEntry struct {
	Timestamp string         `json:"timestamp"`
	Action    string         `json:"action"`
	Actor     string         `json:"actor"`
	Target    string         `json:"target"`
	Outcome   string         `json:"outcome"`
	Detail    string         `json:"detail"`
	Metadata  map[string]any `json:"metadata"`
}

// Message is the payload of POST /jobs/{id}/cancel.
type Message struct {
	Message string `json:"message"`
}

// Removed is the payload of the DELETE endpoints.
type Removed struct {
	Removed string `json:"removed"`
}

// Stats is the payload of GET /stats.
type Stats struct {
	TotalJobs                int     `json:"total_jobs"`
	Completed                int     `json:"completed"`
	Failed                   int     `json:"failed"`
	Running                  int     `json:"running"`
	ConcurrentSlotsAvailable int     `json:"concurrent_slots_available"`
	RateLimitRPS             float64 `json:"rate_limit_rps"`
}

// DirInput is the body of the directory endpoints (/safety/scan, /ipfs/publish).
type DirInput struct {
	Dir string `json:"dir"`
}

// SafetyFinding is one suspicious marker reported by POST /safety/scan.
type SafetyFinding struct {
	Kind     string `json:"kind"`
	Severity string `json:"severity"`
	File     string `json:"file"`
	Detail   string `json:"detail"`
	Evidence string `json:"evidence"`
}

// SafetyReport is the payload of POST /safety/scan.
type SafetyReport struct {
	FilesScanned int             `json:"files_scanned"`
	Findings     []SafetyFinding `json:"findings"`
	Risk         string          `json:"risk"`
	Summary      string          `json:"summary"`
}

// IPFSPublishResult is the payload of POST /ipfs/publish.
type IPFSPublishResult struct {
	CID        string `json:"cid"`
	Name       string `json:"name"`
	Size       int64  `json:"size"`
	Files      int    `json:"files"`
	GatewayURL string `json:"gateway_url"`
}

// defaultBaseURL is used when NewClient is given an empty base URL.
const defaultBaseURL = "http://localhost:8000"

// Client talks to a Zfrog API instance. It is safe for concurrent use.
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

// Option customises a Client built by NewClient.
type Option func(*Client)

// WithAPIKey sends "Authorization: Bearer key" on every request.
func WithAPIKey(key string) Option {
	return func(c *Client) {
		c.apiKey = key
	}
}

// WithHTTPClient replaces the default HTTP client, e.g. to set a timeout or a
// custom transport. A nil client is ignored.
func WithHTTPClient(client *http.Client) Option {
	return func(c *Client) {
		if client != nil {
			c.httpClient = client
		}
	}
}

// NewClient builds a client for baseURL. An empty baseURL means
// http://localhost:8000.
//
// The default HTTP client has no timeout, so a call is bounded by its context
// deadline (recommended) or by a client passed to WithHTTPClient.
func NewClient(baseURL string, opts ...Option) *Client {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = defaultBaseURL
	}
	client := &Client{
		baseURL:    strings.TrimRight(baseURL, "/"),
		httpClient: &http.Client{},
	}
	for _, opt := range opts {
		opt(client)
	}
	return client
}

// APIError reports a non-2xx response from the API.
type APIError struct {
	StatusCode int
	// Detail is the API's {"detail": ...} value: the string itself when the API
	// sent one, otherwise its JSON encoding (validation errors send a list).
	Detail string
	// Body is the raw response body, kept for diagnostics.
	Body   string
	Method string
	Path   string
}

// Error implements the error interface.
func (e *APIError) Error() string {
	if e.Detail != "" {
		return fmt.Sprintf("zfrog: %s %s: HTTP %d: %s", e.Method, e.Path, e.StatusCode, e.Detail)
	}
	return fmt.Sprintf("zfrog: %s %s: HTTP %d", e.Method, e.Path, e.StatusCode)
}

// newAPIError builds an APIError, extracting the API's detail from the body.
func newAPIError(method, path string, status int, raw []byte) *APIError {
	apiErr := &APIError{StatusCode: status, Body: string(raw), Method: method, Path: path}
	var envelope struct {
		Detail json.RawMessage `json:"detail"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil || len(envelope.Detail) == 0 {
		return apiErr
	}
	var detail string
	if err := json.Unmarshal(envelope.Detail, &detail); err == nil {
		apiErr.Detail = detail
		return apiErr
	}
	apiErr.Detail = string(envelope.Detail)
	return apiErr
}

// withQuery appends the encoded values to path, leaving it untouched when empty.
func withQuery(path string, values url.Values) string {
	if len(values) == 0 {
		return path
	}
	return path + "?" + values.Encode()
}

// setIf adds key to values unless value is empty.
func setIf(values url.Values, key, value string) url.Values {
	if value != "" {
		values.Set(key, value)
	}
	return values
}

// call performs the request and returns the raw body, mapping failures onto
// *APIError or a wrapped transport error.
func (c *Client) call(ctx context.Context, method, path string, body any) ([]byte, error) {
	var payload io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("zfrog: encode body for %s %s: %w", method, path, err)
		}
		payload = bytes.NewReader(encoded)
	}

	request, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, payload)
	if err != nil {
		return nil, fmt.Errorf("zfrog: build request %s %s: %w", method, path, err)
	}
	request.Header.Set("Accept", "application/json")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	if c.apiKey != "" {
		request.Header.Set("Authorization", "Bearer "+c.apiKey)
	}

	response, err := c.httpClient.Do(request)
	if err != nil {
		return nil, fmt.Errorf("zfrog: call %s %s: %w", method, path, err)
	}
	defer response.Body.Close()

	raw, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, fmt.Errorf("zfrog: read response from %s %s: %w", method, path, err)
	}
	if response.StatusCode < 200 || response.StatusCode > 299 {
		return nil, newAPIError(method, path, response.StatusCode, raw)
	}
	return raw, nil
}

// do performs the request and decodes the JSON response into out (which may be
// nil when the body is not needed).
func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	raw, err := c.call(ctx, method, path, body)
	if err != nil {
		return err
	}
	if out == nil || len(bytes.TrimSpace(raw)) == 0 {
		return nil
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("zfrog: decode response from %s %s: %w", method, path, err)
	}
	return nil
}

// Health checks that the API answers. GET /health.
func (c *Client) Health(ctx context.Context) (*Health, error) {
	out := new(Health)
	if err := c.do(ctx, http.MethodGet, "/health", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// CreateJob starts an extraction job. POST /jobs.
func (c *Client) CreateJob(ctx context.Context, input CreateJobInput) (*Job, error) {
	out := new(Job)
	if err := c.do(ctx, http.MethodPost, "/jobs", input, out); err != nil {
		return nil, err
	}
	return out, nil
}

// ListJobs lists every known job. GET /jobs.
func (c *Client) ListJobs(ctx context.Context) ([]Job, error) {
	var out []Job
	if err := c.do(ctx, http.MethodGet, "/jobs", nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// GetJob fetches one job. GET /jobs/{id}.
func (c *Client) GetJob(ctx context.Context, id string) (*Job, error) {
	out := new(Job)
	if err := c.do(ctx, http.MethodGet, "/jobs/"+url.PathEscape(id), nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// CancelJob marks a running job for cancellation. POST /jobs/{id}/cancel.
func (c *Client) CancelJob(ctx context.Context, id string) (*Message, error) {
	out := new(Message)
	if err := c.do(ctx, http.MethodPost, "/jobs/"+url.PathEscape(id)+"/cancel", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// GetJobResult fetches the summary of a finished job. GET /jobs/{id}/result.
func (c *Client) GetJobResult(ctx context.Context, id string) (*JobResult, error) {
	out := new(JobResult)
	if err := c.do(ctx, http.MethodGet, "/jobs/"+url.PathEscape(id)+"/result", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// DownloadZip fetches the cloned content as a ZIP. GET /jobs/{id}/download.
func (c *Client) DownloadZip(ctx context.Context, id string) ([]byte, error) {
	return c.call(ctx, http.MethodGet, "/jobs/"+url.PathEscape(id)+"/download", nil)
}

// GetJobPDF fetches the generated PDF. GET /jobs/{id}/pdf.
func (c *Client) GetJobPDF(ctx context.Context, id string) ([]byte, error) {
	return c.call(ctx, http.MethodGet, "/jobs/"+url.PathEscape(id)+"/pdf", nil)
}

// Probe inspects a URL and suggests an engine. GET /probe/{url}.
func (c *Client) Probe(ctx context.Context, rawURL string) (*ProbeResult, error) {
	out := new(ProbeResult)
	if err := c.do(ctx, http.MethodGet, "/probe/"+url.PathEscape(rawURL), nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// ListSnapshots lists captured snapshots; an empty rawURL lists them all.
// GET /snapshots.
func (c *Client) ListSnapshots(ctx context.Context, rawURL string) ([]SnapshotEntry, error) {
	var out []SnapshotEntry
	path := withQuery("/snapshots", setIf(url.Values{}, "url", rawURL))
	if err := c.do(ctx, http.MethodGet, path, nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Diff compares two snapshots. POST /diff.
func (c *Client) Diff(ctx context.Context, a, b string) (*DiffReport, error) {
	out := new(DiffReport)
	if err := c.do(ctx, http.MethodPost, "/diff", map[string]string{"a": a, "b": b}, out); err != nil {
		return nil, err
	}
	return out, nil
}

// GetVersions lists the saved versions of a site; an empty branch means the
// server default. GET /versions.
func (c *Client) GetVersions(ctx context.Context, rawURL, branch string) (*VersionLog, error) {
	query := setIf(url.Values{}, "url", rawURL)
	query = setIf(query, "branch", branch)
	out := new(VersionLog)
	if err := c.do(ctx, http.MethodGet, withQuery("/versions", query), nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// Rollback restores the files of a saved version. POST /versions/rollback.
func (c *Client) Rollback(ctx context.Context, rawURL, ref string) (*RollbackResult, error) {
	out := new(RollbackResult)
	if err := c.do(ctx, http.MethodPost, "/versions/rollback", map[string]string{"url": rawURL, "ref": ref}, out); err != nil {
		return nil, err
	}
	return out, nil
}

// Search queries cloned content. POST /search.
func (c *Client) Search(ctx context.Context, input SearchInput) (*SearchResponse, error) {
	out := new(SearchResponse)
	if err := c.do(ctx, http.MethodPost, "/search", input, out); err != nil {
		return nil, err
	}
	return out, nil
}

// ListSchedules lists the recurring jobs. GET /schedules.
func (c *Client) ListSchedules(ctx context.Context) ([]Schedule, error) {
	var out []Schedule
	if err := c.do(ctx, http.MethodGet, "/schedules", nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// CreateSchedule schedules a recurring job. POST /schedules.
func (c *Client) CreateSchedule(ctx context.Context, input ScheduleInput) (*Schedule, error) {
	out := new(Schedule)
	if err := c.do(ctx, http.MethodPost, "/schedules", input, out); err != nil {
		return nil, err
	}
	return out, nil
}

// DeleteSchedule removes a scheduled job. DELETE /schedules/{id}.
func (c *Client) DeleteSchedule(ctx context.Context, id string) (*Removed, error) {
	out := new(Removed)
	if err := c.do(ctx, http.MethodDelete, "/schedules/"+url.PathEscape(id), nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// RunSchedule runs a scheduled job now. POST /schedules/{id}/run.
func (c *Client) RunSchedule(ctx context.Context, id string) (*ScheduleRun, error) {
	out := new(ScheduleRun)
	if err := c.do(ctx, http.MethodPost, "/schedules/"+url.PathEscape(id)+"/run", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// ListWorkflows lists the saved pipelines. GET /workflows.
func (c *Client) ListWorkflows(ctx context.Context) ([]Workflow, error) {
	var out []Workflow
	if err := c.do(ctx, http.MethodGet, "/workflows", nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// SaveWorkflow stores a named pipeline. POST /workflows.
func (c *Client) SaveWorkflow(ctx context.Context, name string, steps []WorkflowStep) (*Workflow, error) {
	body := struct {
		Name  string         `json:"name"`
		Steps []WorkflowStep `json:"steps"`
	}{Name: name, Steps: steps}
	out := new(Workflow)
	if err := c.do(ctx, http.MethodPost, "/workflows", body, out); err != nil {
		return nil, err
	}
	return out, nil
}

// RunWorkflow runs a saved pipeline. POST /workflows/{id}/run.
func (c *Client) RunWorkflow(ctx context.Context, id string) (*RunResult, error) {
	out := new(RunResult)
	if err := c.do(ctx, http.MethodPost, "/workflows/"+url.PathEscape(id)+"/run", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// EngineStats lists per-engine performance; an empty engine means all of them.
// GET /analytics/engines.
func (c *Client) EngineStats(ctx context.Context, engine string) ([]EngineStats, error) {
	var out []EngineStats
	path := withQuery("/analytics/engines", setIf(url.Values{}, "engine", engine))
	if err := c.do(ctx, http.MethodGet, path, nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Totals returns the overall run figures. GET /analytics/totals.
func (c *Client) Totals(ctx context.Context) (*Totals, error) {
	out := new(Totals)
	if err := c.do(ctx, http.MethodGet, "/analytics/totals", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// Audit lists recent audit entries, newest first; a limit of zero or less uses
// the server default. GET /audit.
func (c *Client) Audit(ctx context.Context, limit int) ([]AuditEntry, error) {
	query := url.Values{}
	if limit > 0 {
		query.Set("limit", fmt.Sprint(limit))
	}
	var out []AuditEntry
	if err := c.do(ctx, http.MethodGet, withQuery("/audit", query), nil, &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Stats returns the queue depth and rate-limit configuration. GET /stats.
func (c *Client) Stats(ctx context.Context) (*Stats, error) {
	out := new(Stats)
	if err := c.do(ctx, http.MethodGet, "/stats", nil, out); err != nil {
		return nil, err
	}
	return out, nil
}

// ScanSafety looks for malware and phishing markers under dir.
// POST /safety/scan.
func (c *Client) ScanSafety(ctx context.Context, dir string) (*SafetyReport, error) {
	out := new(SafetyReport)
	if err := c.do(ctx, http.MethodPost, "/safety/scan", DirInput{Dir: dir}, out); err != nil {
		return nil, err
	}
	return out, nil
}

// PublishIPFS publishes a clone to IPFS. POST /ipfs/publish.
func (c *Client) PublishIPFS(ctx context.Context, dir string) (*IPFSPublishResult, error) {
	out := new(IPFSPublishResult)
	if err := c.do(ctx, http.MethodPost, "/ipfs/publish", DirInput{Dir: dir}, out); err != nil {
		return nil, err
	}
	return out, nil
}
