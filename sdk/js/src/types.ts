/**
 * Wire types for the Zfrog REST API.
 *
 * Field names are snake_case because they mirror the JSON the API actually
 * sends; these interfaces describe a decoded response as-is.
 */

/** Payload of `GET /health`. */
export interface HealthResponse {
  status: string;
}

/** A crawl/extraction job, as returned by every `/jobs` endpoint. */
export interface Job {
  id: string;
  url: string;
  mode: string;
  max_depth: number;
  status: string;
  probe: ProbeResult | null;
  output_path: string | null;
  created_at: string;
  updated_at: string;
  error: string | null;
}

/** Body of `POST /jobs`. */
export interface CreateJobInput {
  url: string;
  mode: string;
  max_depth?: number;
  pdf_filename?: string;
  versioned?: boolean;
}

/** Payload of `GET /jobs/{id}/result`. */
export interface JobResult {
  job_id: string;
  output_path: string;
  files_count: number;
  total_size_bytes: number;
  engine_used: string;
  duration_seconds: number;
}

/** Payload of `GET /probe/{url}`. */
export interface ProbeResult {
  url: string;
  is_spa: boolean;
  has_js_rendering: boolean;
  robots_restricted: boolean;
  framework: string | null;
  content_type: string;
  suggested_engine: string;
  status_code: number | null;
  final_url: string | null;
}

/** One entry of `GET /snapshots`. */
export interface SnapshotEntry {
  slug: string;
  file: string;
  url: string;
  captured_at: string;
  pages: number;
}

/** Payload of `POST /diff`. */
export interface DiffReport {
  url: string;
  a: string;
  b: string;
  added: string[];
  removed: string[];
  changed: string[];
  unchanged: string[];
  change_ratio: number;
  details: Record<string, unknown>[];
}

/** A single saved version of a site. */
export interface Version {
  id: string;
  url: string;
  snapshot: string;
  captured_at: string;
  message: string;
  parent: string | null;
  branch: string;
  pages: number;
  files: Record<string, string>;
}

/** Payload of `GET /versions`. */
export interface VersionLog {
  url: string;
  branch: string;
  branches: string[];
  versions: Version[];
}

/** One search result. */
export interface SearchHit {
  path: string;
  url: string;
  title: string;
  snippet: string;
  score: number;
}

/** Payload of `POST /search`. */
export interface SearchResponse {
  query: string;
  mode: string;
  hits: SearchHit[];
}

/** A recurring job definition. */
export interface Schedule {
  id: string;
  cron: string;
  url: string;
  mode: string;
  max_depth: number;
  enabled: boolean;
  last_run: string | null;
  next_run: string | null;
}

/** Body of `POST /schedules`. */
export interface ScheduleInput {
  cron: string;
  url: string;
  mode: string;
  max_depth?: number;
}

/** A single workflow step, as stored by the API. */
export interface WorkflowStep {
  id: string;
  type: string;
  params: Record<string, unknown>;
  needs: string[] | null;
}

/** Body of a step when saving a workflow; the API fills the defaults. */
export interface WorkflowStepInput {
  type: string;
  params?: Record<string, unknown>;
  needs?: string[] | null;
  id?: string;
}

/** A named pipeline of steps. */
export interface Workflow {
  id: string;
  name: string;
  steps: WorkflowStep[];
}

/** Outcome of a single step inside a run. */
export interface StepResult {
  type: string;
  status: string;
  detail: string;
  output: string | null;
}

/** Payload of `POST /workflows/{id}/run`. */
export interface RunResult {
  workflow_id: string;
  status: string;
  steps: StepResult[];
  error: string | null;
}

/** Aggregated performance of a single engine. */
export interface EngineStats {
  engine: string;
  runs: number;
  succeeded: number;
  failed: number;
  success_rate: number;
  avg_duration_s: number;
  avg_bytes: number;
  total_bytes: number;
  avg_files: number;
  total_cost: number;
  avg_cost: number;
}

/** Payload of `GET /analytics/totals`. */
export interface Totals {
  runs: number;
  succeeded: number;
  failed: number;
  success_rate: number;
  bytes: number;
  avg_duration_s: number;
  cost: number;
  currency: string;
}

/** One recorded action of the audit trail. */
export interface AuditEntry {
  timestamp: string;
  action: string;
  actor: string;
  target: string;
  outcome: string;
  detail: string;
  metadata: Record<string, unknown>;
}

/** Payload of `POST /versions/rollback`. */
export interface RollbackResult {
  restored: string;
  files: number;
}

/** Payload of `POST /jobs/{id}/cancel`. */
export interface MessageResponse {
  message: string;
}

/** Payload of `POST /schedules/{id}/run`. */
export interface ScheduleRun {
  job_id: string;
}

/** Payload of `GET /stats`. */
export interface Stats {
  total_jobs: number;
  completed: number;
  failed: number;
  running: number;
  concurrent_slots_available: number;
  rate_limit_rps: number;
}

/** One suspicious marker reported by `POST /safety/scan`. */
export interface SafetyFinding {
  kind: string;
  severity: string;
  file: string;
  detail: string;
  evidence: string;
}

/** Payload of `POST /safety/scan`. */
export interface SafetyReport {
  files_scanned: number;
  findings: SafetyFinding[];
  risk: string;
  summary: string;
}

/** Payload of `POST /ipfs/publish`. */
export interface IpfsPublishResult {
  cid: string;
  name: string;
  size: number;
  files: number;
  gateway_url: string;
}
