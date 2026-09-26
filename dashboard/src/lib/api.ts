import { authHeaders } from "@/lib/auth"

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export type JobStatus =
  | "pending"
  | "probing"
  | "processing"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"

export type JobMode = "auto" | "mirror" | "singlepage" | "scrape" | "extract" | "analyze" | "compare" | "ask" | "pdf" | "summarize" | "delta" | "entities" | "translate" | "sentiment" | "tags" | "video" | "api_discovery"

export interface ProbeResult {
  url: string
  is_spa: boolean
  has_js_rendering: boolean
  robots_restricted: boolean
  framework: string | null
  content_type: string
  suggested_engine: "playwright" | "wget" | "static_file"
  status_code: number | null
  final_url: string | null
}

export interface Job {
  id: string
  url: string
  mode: JobMode
  max_depth: number
  status: JobStatus
  probe: ProbeResult | null
  output_path: string | null
  created_at: string
  updated_at: string
  error: string | null
}

export interface JobResult {
  job_id: string
  output_path: string
  files_count: number
  total_size_bytes: number
  engine_used: string
  duration_seconds: number
}

export interface SystemStats {
  total_jobs: number
  completed: number
  running: number
  failed: number
  concurrent_slots_available: number
  rate_limit_rps: number
}

export interface AppConfig {
  redis_url: string
  output_dir: string
  max_concurrent_jobs: number
  worker_concurrency: number
  proxy_url: string | null
  rate_limit_rps: number
  http_timeout_connect: number
  http_timeout_read: number
}

async function fetcher<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    // The session cookie is the primary credential, and the browser only sends it
    // cross-origin when this is set.
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    let detail = text
    try {
      const parsed = JSON.parse(text)
      if (parsed?.detail) detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail)
    } catch {
      // not JSON, keep raw text
    }
    throw new Error(detail || `HTTP ${res.status}`)
  }
  const ct = res.headers.get("content-type")
  if (ct?.includes("application/json")) {
    return res.json()
  }
  return res as unknown as T
}

export interface SnapshotEntry {
  /** Directory name under output/snapshots (site identity). */
  slug: string
  /** Timestamped file name, e.g. 20260924T031027Z.json */
  file: string
  url: string
  captured_at: string
  pages: number
}

export interface DiffPageDetail {
  path: string
  title_a: string
  title_b: string
  text_diff_lines: number
}

export interface DiffReport {
  url: string
  a: string
  b: string
  added: string[]
  removed: string[]
  changed: string[]
  unchanged: string[]
  change_ratio: number
  details: DiffPageDetail[]
}

export interface Version {
  id: string
  url: string
  snapshot: string
  captured_at: string
  message: string
  parent: string | null
  branch: string
  pages: number
}

export interface VersionLog {
  url: string
  branch: string
  branches: string[]
  versions: Version[]
}

export interface Schedule {
  id: string
  cron: string
  url: string
  mode: JobMode
  max_depth: number
  enabled: boolean
  last_run: string | null
  next_run: string | null
}

export interface SearchHit {
  path: string
  url: string
  title: string
  snippet: string
  score: number
}

export interface SearchResponse {
  query: string
  mode: "fulltext" | "semantic"
  hits: SearchHit[]
  error?: string
}

export interface SessionEntry {
  domain: string
  saved_at: string
  cookies: number
}

export interface WorkflowStep {
  type: string
  params: Record<string, string | number | boolean>
  /** Stable label, e.g. "step-0"; steps are matched by this in `needs`. */
  id?: string
  /** Ids of the steps this one waits for. Omit for the linear default; `[]` runs in parallel. */
  needs?: string[]
}

export interface Workflow {
  id: string
  name: string
  steps: WorkflowStep[]
}

export interface WorkflowRunResult {
  workflow_id: string
  status: string
  steps: { type: string; status: string; detail: string; output: string | null }[]
  error: string | null
}

export interface ExtractedElement {
  index: number
  tag: string
  text: string
  html: string
}

export interface ExtractPreview {
  url: string
  selector: string
  count: number
  elements: ExtractedElement[]
}

export interface ExtractPage {
  url: string
  title: string
  html: string
}

export interface EngineStats {
  engine: string
  runs: number
  succeeded: number
  failed: number
  success_rate: number
  avg_duration_s: number
  avg_bytes: number
  total_bytes: number
  avg_files: number
}

export interface AnalyticsTotals {
  runs: number
  succeeded: number
  failed: number
  success_rate: number
  bytes: number
  avg_duration_s: number
}

export interface SafetyFinding {
  kind: string
  severity: string
  file: string
  detail: string
  evidence: string
}

export interface SafetyScanResult {
  files_scanned: number
  findings: SafetyFinding[]
  risk: string
  summary: string
}

export interface AuditEntry {
  timestamp: string
  action: string
  actor: string
  target: string
  outcome: string
  detail: string
  metadata: Record<string, unknown>
}

export interface IpfsPublishResult {
  cid: string
  name: string
  size: number
  files: number
  gateway_url: string
}

export interface WebhookEntry {
  id: string
  url: string
  events: string[]
  has_secret: boolean
}

export interface MarketplaceAsset {
  id: string
  kind: string
  name: string
  description: string
  author: string
  version: string
  tags: string[]
  installs: number
  rating: number
  rating_count: number
}

export interface MarketplaceInstall {
  kind: string
  name: string
  target: string
  installed: boolean
  detail: string
}

export interface WorkflowPreviewStep {
  index: number
  type: string
  summary: string
  warnings: string[]
}

export interface WorkflowPreview {
  steps: WorkflowPreviewStep[]
  warnings: string[]
  total: number
}

export interface CostByEngine {
  engine: string
  runs: number
  bytes: number
  duration_s: number
  cost: number
  cost_per_run: number
}

export interface CostBreakdown {
  transfer: number
  compute: number
  storage: number
  total: number
  currency: string
}

export interface WebhookEntry {
  id: string
  url: string
  events: string[]
  has_secret: boolean
}

export interface MarketplaceAsset {
  id: string
  kind: string
  name: string
  description: string
  author: string
  version: string
  tags: string[]
  installs: number
  rating: number
  rating_count: number
}

export interface MarketplaceInstall {
  kind: string
  name: string
  target: string
  installed: boolean
  detail: string
}

export interface WorkflowPreviewStep {
  index: number
  type: string
  summary: string
  warnings: string[]
}

export interface WorkflowPreview {
  steps: WorkflowPreviewStep[]
  warnings: string[]
  total: number
}

export interface AppUser {
  id: string
  email: string
  name: string
  role: string
  orgs: string[]
  created_at: string
  enabled: boolean
  sso_subject: string
}

export interface Organization {
  id: string
  name: string
  created_at: string
  owner: string
  members: Record<string, string>
  enabled: boolean
  has_data: boolean
}

export interface Annotation {
  id: string
  job_id: string
  path: string
  selector: string
  text: string
  author: string
  created_at: string
  updated_at: string
  resolved: boolean
  tags: string[]
  replies: { id: string; author: string; text: string; created_at: string }[]
}

export interface AnnotationCounts {
  total: number
  open: number
  resolved: number
  by_author: Record<string, number>
  by_tag: Record<string, number>
}

export interface DomainProfile {
  id: string
  name: string
  description: string
  terminology: Record<string, string>
  examples: { input: string; output: string }[]
  instructions: string
  entity_types: string[]
  tags: string[]
  created_at: string
  updated_at: string
}

export interface WorkerInfo {
  id: string
  region: string
  capacity: number
  running: number
  last_seen: string
  started_at: string
  version: string
  tags: string[]
  enabled: boolean
  alive: boolean
}

export interface WorkerStats {
  workers: number
  alive: number
  capacity: number
  running: number
  free: number
  by_region: Record<string, number>
}

export interface MarketplaceIndexEntry {
  id: string
  kind: string
  name: string
  description: string
  author: string
  version: string
  tags: string[]
  installs: number
  rating: number
  rating_count: number
  checksum: string
  published_at: string
}

export interface MarketplaceIndex {
  version: number
  generated_at: string
  source: string
  count: number
  assets: MarketplaceIndexEntry[]
}

export interface TimelineEntry {
  ref: string
  captured_at: string
  message: string
  branch: string
  pages: number
  size_bytes: number
}

export interface ArchivedPage {
  path: string
  url: string
  title: string
  text: string
  sha256: string
  size_bytes: number
}

export interface RoiInputs {
  hourly_rate: number
  minutes_per_page: number
  currency: string
}

export interface RoiResult {
  runs: number
  pages: number
  bytes: number
  duration_s: number
  value: number
  cost: number
  net: number
  ratio: number | null
  currency: string
  inputs: RoiInputs
  per_engine: Record<string, unknown>[]
  note: string
}

export interface PriceChange {
  label: string
  before: number
  after: number
  currency: string
  change_pct: number
  direction: string
  first_seen: string
  last_seen: string
  points: number
  significant: boolean
}

export const api = {
  getJobs: () => fetcher<Job[]>("/jobs"),
  getJob: (id: string) => fetcher<Job>(`/jobs/${id}`),
  getJobResult: (id: string) => fetcher<JobResult>(`/jobs/${id}/result`),
  createJob: (data: {
    url: string
    mode: JobMode
    max_depth: number
    pdf_filename?: string
  }) => fetcher<Job>("/jobs", { method: "POST", body: JSON.stringify(data) }),
  cancelJob: (id: string) => fetcher<{ message: string }>(`/jobs/${id}/cancel`, { method: "POST" }),
  downloadUrl: (id: string) => `${API_URL}/jobs/${id}/download`,
  pdfUrl: (id: string) => `${API_URL}/jobs/${id}/pdf`,
  getSnapshots: (url?: string) =>
    fetcher<SnapshotEntry[]>(`/snapshots${url ? `?url=${encodeURIComponent(url)}` : ""}`),
  snapshotUrl: (slug: string, file: string) =>
    `${API_URL}/snapshots/${encodeURIComponent(slug)}/${encodeURIComponent(file)}`,
  diffSnapshots: (a: string, b: string) =>
    fetcher<DiffReport>("/diff", { method: "POST", body: JSON.stringify({ a, b }) }),
  getVersions: (url: string, branch?: string) =>
    fetcher<VersionLog>(
      `/versions?url=${encodeURIComponent(url)}${branch ? `&branch=${encodeURIComponent(branch)}` : ""}`
    ),
  rollbackVersion: (url: string, ref: string) =>
    fetcher<{ restored: string; files: number }>("/versions/rollback", {
      method: "POST",
      body: JSON.stringify({ url, ref }),
    }),
  createBranch: (url: string, name: string) =>
    fetcher<{ branches: string[] }>("/versions/branches", {
      method: "POST",
      body: JSON.stringify({ url, name }),
    }),
  getSchedules: () => fetcher<Schedule[]>("/schedules"),
  addSchedule: (data: { cron: string; url: string; mode: JobMode; max_depth: number }) =>
    fetcher<Schedule>("/schedules", { method: "POST", body: JSON.stringify(data) }),
  removeSchedule: (id: string) =>
    fetcher<{ removed: string }>(`/schedules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runSchedule: (id: string) =>
    fetcher<{ job_id: string }>(`/schedules/${encodeURIComponent(id)}/run`, { method: "POST" }),
  search: (query: string, mode: "fulltext" | "semantic", dir?: string) =>
    fetcher<SearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify({ query, mode, dir: dir || null }),
    }),
  getSessions: () => fetcher<SessionEntry[]>("/sessions"),
  deleteSession: (domain: string) =>
    fetcher<{ removed: string }>(`/sessions/${encodeURIComponent(domain)}`, { method: "DELETE" }),
  getWorkflows: () => fetcher<Workflow[]>("/workflows"),
  saveWorkflow: (workflow: { name: string; steps: WorkflowStep[] }) =>
    fetcher<Workflow>("/workflows", { method: "POST", body: JSON.stringify(workflow) }),
  deleteWorkflow: (id: string) =>
    fetcher<{ removed: string }>(`/workflows/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runWorkflow: (id: string) =>
    fetcher<WorkflowRunResult>(`/workflows/${encodeURIComponent(id)}/run`, { method: "POST" }),
  extractPage: (url: string) =>
    fetcher<ExtractPage>(`/extract/page?url=${encodeURIComponent(url)}`),
  previewSelector: (url: string, selector: string) =>
    fetcher<ExtractPreview>("/extract/preview", {
      method: "POST",
      body: JSON.stringify({ url, selector }),
    }),
  getEngineStats: (engine?: string) =>
    fetcher<EngineStats[]>(`/analytics/engines${engine ? `?engine=${encodeURIComponent(engine)}` : ""}`),
  getAnalyticsTotals: () => fetcher<AnalyticsTotals>("/analytics/totals"),
  getAuditLog: (limit = 50) => fetcher<AuditEntry[]>(`/audit?limit=${limit}`),
  scanSafety: (dir: string) =>
    fetcher<SafetyScanResult>("/safety/scan", { method: "POST", body: JSON.stringify({ dir }) }),
  publishIpfs: (dir: string) =>
    fetcher<IpfsPublishResult>("/ipfs/publish", { method: "POST", body: JSON.stringify({ dir }) }),
  getWebhooks: () => fetcher<WebhookEntry[]>("/webhooks"),
  registerWebhook: (data: { url: string; events: string[]; secret?: string }) =>
    fetcher<WebhookEntry>("/webhooks", { method: "POST", body: JSON.stringify(data) }),
  deleteWebhook: (id: string) =>
    fetcher<{ removed: string }>(`/webhooks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getMarketplace: (kind?: string, query?: string) => {
    const params = new URLSearchParams()
    if (kind) params.set("kind", kind)
    if (query) params.set("query", query)
    const qs = params.toString()
    return fetcher<MarketplaceAsset[]>(`/marketplace${qs ? `?${qs}` : ""}`)
  },
  installAsset: (id: string) =>
    fetcher<MarketplaceInstall>(`/marketplace/${encodeURIComponent(id)}/install`, { method: "POST" }),
  uninstallAsset: (id: string) =>
    fetcher<{ removed: boolean }>(`/marketplace/${encodeURIComponent(id)}/install`, { method: "DELETE" }),
  rateAsset: (id: string, score: number) =>
    fetcher<MarketplaceAsset>(`/marketplace/${encodeURIComponent(id)}/rate`, {
      method: "POST",
      body: JSON.stringify({ score }),
    }),
  previewWorkflow: (steps: WorkflowStep[]) =>
    fetcher<WorkflowPreview>("/workflows/preview", {
      method: "POST",
      body: JSON.stringify({ steps }),
    }),
  getCostByEngine: () => fetcher<CostByEngine[]>("/analytics/cost"),
  getUsers: () => fetcher<AppUser[]>("/users"),
  createUser: (data: { email: string; name?: string; role?: string; password?: string; orgs?: string[] }) =>
    fetcher<{ user: AppUser; password: string }>("/users", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getOrgs: () => fetcher<Organization[]>("/orgs"),
  createOrg: (data: { name: string; owner: string }) =>
    fetcher<Organization>("/orgs", { method: "POST", body: JSON.stringify(data) }),
  addOrgMember: (orgId: string, data: { user_id: string; role?: string }) =>
    fetcher<Organization>(`/orgs/${encodeURIComponent(orgId)}/members`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getAnnotations: (jobId?: string, resolved?: boolean) => {
    const params = new URLSearchParams()
    if (jobId) params.set("job_id", jobId)
    if (resolved !== undefined) params.set("resolved", String(resolved))
    const qs = params.toString()
    return fetcher<Annotation[]>(`/annotations${qs ? `?${qs}` : ""}`)
  },
  createAnnotation: (data: {
    job_id: string
    path: string
    text: string
    author?: string
    selector?: string
    tags?: string[]
  }) => fetcher<Annotation>("/annotations", { method: "POST", body: JSON.stringify(data) }),
  updateAnnotation: (id: string, data: { text?: string; selector?: string; tags?: string[] }) =>
    fetcher<Annotation>(`/annotations/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  resolveAnnotation: (id: string, resolved: boolean) =>
    fetcher<Annotation>(
      `/annotations/${encodeURIComponent(id)}/resolve?resolved=${resolved}`,
      { method: "POST" }
    ),
  replyAnnotation: (id: string, data: { text: string; author?: string }) =>
    fetcher<Annotation>(`/annotations/${encodeURIComponent(id)}/replies`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteAnnotation: (id: string) =>
    fetcher<{ removed: string }>(`/annotations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  exportAnnotations: (jobId: string) =>
    fetcher<{ job_id: string; markdown: string }>(
      `/annotations/export?job_id=${encodeURIComponent(jobId)}`
    ),
  getDomains: () => fetcher<{ saved: DomainProfile[]; builtin: DomainProfile[] }>("/domains"),
  saveDomain: (data: Partial<DomainProfile> & { name: string }) =>
    fetcher<DomainProfile>("/domains", { method: "POST", body: JSON.stringify(data) }),
  deleteDomain: (id: string) =>
    fetcher<{ removed: string }>(`/domains/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getWorkers: (region?: string) =>
    fetcher<{ stats: WorkerStats; workers: WorkerInfo[] }>(
      `/workers${region ? `?region=${encodeURIComponent(region)}` : ""}`
    ),
  assignWorker: (url: string, region?: string) =>
    fetcher<{ worker: string | null; region: string; reason: string }>(
      `/workers/assign?url=${encodeURIComponent(url)}${region ? `&region=${encodeURIComponent(region)}` : ""}`
    ),
  getMarketplaceIndex: (source?: string) =>
    fetcher<MarketplaceIndex>(
      `/marketplace/index${source ? `?source=${encodeURIComponent(source)}` : ""}`
    ),
  syncMarketplace: (indexUrl: string) =>
    fetcher<{ added: number; updated: number; unchanged: number; skipped: number; errors: string[] }>(
      "/marketplace/sync",
      { method: "POST", body: JSON.stringify({ index_url: indexUrl }) }
    ),
  getAuthConfig: () =>
    fetcher<{ auth_enabled: boolean; sso: boolean; issuer?: string; client_id?: string }>(
      "/auth/config"
    ),
  // Reading the configuration needs `read:jobs`, so a 200 here proves the stored
  // credential is accepted — which is what the login gate checks.
  verifyCredential: () => fetcher<AppConfig>("/config"),
  // Clears the server-side session cookie. Safe without a credential: it only
  // expires the caller's own cookie.
  logout: () => fetcher<{ signed_out: boolean }>("/auth/logout", { method: "POST" }),
  getTimeline: (url: string, branch?: string) =>
    fetcher<{ url: string; branch: string; entries: TimelineEntry[]; summary: string }>(
      `/timeline?url=${encodeURIComponent(url)}${branch ? `&branch=${encodeURIComponent(branch)}` : ""}`
    ),
  resolveTimelineDate: (url: string, when: string) =>
    fetcher<{ ref: string; captured_at: string; message: string }>(
      `/timeline/resolve?url=${encodeURIComponent(url)}&when=${encodeURIComponent(when)}`
    ),
  getTimelinePages: (url: string, ref: string) =>
    fetcher<ArchivedPage[]>(
      `/timeline/pages?url=${encodeURIComponent(url)}&ref=${encodeURIComponent(ref)}`
    ),
  getTimelinePage: (url: string, ref: string, path: string) =>
    fetcher<ArchivedPage>(
      `/timeline/page?url=${encodeURIComponent(url)}&ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`
    ),
  timelinePageUrl: (url: string, ref: string, path: string) =>
    `${API_URL}/timeline/content?url=${encodeURIComponent(url)}&ref=${encodeURIComponent(ref)}&path=${encodeURIComponent(path)}`,
  getRoi: () => fetcher<RoiResult>("/roi"),
  getPriceChanges: (url: string) =>
    fetcher<PriceChange[]>(`/prices/changes?url=${encodeURIComponent(url)}`),
  probe: (url: string) => fetcher<ProbeResult>(`/probe/${encodeURIComponent(url)}`),
  getStats: () => fetcher<SystemStats>("/stats"),
  getConfig: () => fetcher<AppConfig>("/config"),
  updateRateLimit: (rps: number) =>
    fetcher<{ rate_limit_rps: number }>("/config/rate-limit", {
      method: "POST",
      body: JSON.stringify({ requests_per_second: rps }),
    }),
}
