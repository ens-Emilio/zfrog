/**
 * Official JavaScript/TypeScript client for the Zfrog REST API.
 *
 * ```ts
 * const client = new ZfrogClient({ baseUrl: "http://localhost:8000", apiKey: "..." });
 * const job = await client.createJob({ url: "https://example.com", mode: "mirror" });
 * const zip = await client.downloadZip(job.id);
 * ```
 */

import type {
  AuditEntry,
  CreateJobInput,
  DiffReport,
  EngineStats,
  HealthResponse,
  IpfsPublishResult,
  Job,
  JobResult,
  MessageResponse,
  ProbeResult,
  RollbackResult,
  RunResult,
  SafetyReport,
  Schedule,
  ScheduleInput,
  ScheduleRun,
  SearchResponse,
  SnapshotEntry,
  Stats,
  Totals,
  VersionLog,
  Workflow,
  WorkflowStepInput,
} from "./types";

export * from "./types";

/** Base URL used when the caller does not pass one. */
const DEFAULT_BASE_URL = "http://localhost:8000";

/** Per-request timeout used when the caller does not pass one. */
const DEFAULT_TIMEOUT_MS = 30_000;

/** Options accepted by {@link ZfrogClient}. */
export interface ZfrogClientOptions {
  baseUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
}

/**
 * Error raised for any failed call.
 *
 * `status` is the HTTP status of the response, or `0` when the request never
 * reached the API (connection refused, timeout, DNS failure).
 * `detail` is the API's `{"detail": ...}` value when the body carries one.
 * `body` is the raw response text, kept for diagnostics.
 */
export class ZfrogError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly body: string;

  constructor(message: string, status: number, detail: unknown = undefined, body = "") {
    super(message);
    this.name = "ZfrogError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

/**
 * Pull the API's `detail` out of an error body.
 *
 * Returns the parsed `detail` when the body is a JSON object carrying one,
 * otherwise the parsed body itself, otherwise the untouched text.
 */
function parseDetail(body: string): unknown {
  if (body === "") {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed !== null && typeof parsed === "object" && "detail" in parsed) {
      return (parsed as { detail: unknown }).detail;
    }
    return parsed;
  } catch {
    return body;
  }
}

/** Build `?a=1&b=2`, dropping parameters that were not supplied. */
function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

/**
 * Client for the Zfrog REST API.
 *
 * Every method performs a real HTTP call with the global `fetch`; nothing is
 * cached or retried. Failed calls throw {@link ZfrogError}.
 */
export class ZfrogClient {
  readonly baseUrl: string;
  readonly apiKey: string | undefined;
  readonly timeoutMs: number;

  constructor({ baseUrl = DEFAULT_BASE_URL, apiKey, timeoutMs = DEFAULT_TIMEOUT_MS }: ZfrogClientOptions = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  /** Send a request and return the raw response, throwing on any failure. */
  private async send(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("accept", "application/json");
    if (init.body !== undefined) {
      headers.set("content-type", "application/json");
    }
    if (this.apiKey !== undefined) {
      headers.set("authorization", `Bearer ${this.apiKey}`);
    }

    const url = `${this.baseUrl}${path}`;
    let response: Response;
    try {
      response = await fetch(url, { ...init, headers, signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new ZfrogError(`Zfrog unreachable at ${url}: ${reason}`, 0, undefined, "");
    }

    if (!response.ok) {
      const body = await response.text();
      throw new ZfrogError(
        `Zfrog returned ${response.status} for ${init.method ?? "GET"} ${path}`,
        response.status,
        parseDetail(body),
        body,
      );
    }
    return response;
  }

  /** Send a request and decode the JSON response. */
  private async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.send(path, init);
    const body = await response.text();
    if (body.trim() === "") {
      throw new ZfrogError(`Zfrog returned an empty body for ${path}`, response.status, undefined, body);
    }
    try {
      return JSON.parse(body) as T;
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      throw new ZfrogError(`Zfrog returned invalid JSON for ${path}: ${reason}`, response.status, undefined, body);
    }
  }

  /** Send a request and return the response body untouched. */
  private async bytes(path: string, init: RequestInit = {}): Promise<Uint8Array> {
    const response = await this.send(path, init);
    return new Uint8Array(await response.arrayBuffer());
  }

  /** `GET /health`. */
  async health(): Promise<HealthResponse> {
    return this.json<HealthResponse>("/health");
  }

  /** `POST /jobs`. */
  async createJob(input: CreateJobInput): Promise<Job> {
    return this.json<Job>("/jobs", { method: "POST", body: JSON.stringify(input) });
  }

  /** `GET /jobs`. */
  async listJobs(): Promise<Job[]> {
    return this.json<Job[]>("/jobs");
  }

  /** `GET /jobs/{id}`. */
  async getJob(id: string): Promise<Job> {
    return this.json<Job>(`/jobs/${encodeURIComponent(id)}`);
  }

  /** `POST /jobs/{id}/cancel`. */
  async cancelJob(id: string): Promise<MessageResponse> {
    return this.json<MessageResponse>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  }

  /** `GET /jobs/{id}/result`. */
  async getJobResult(id: string): Promise<JobResult> {
    return this.json<JobResult>(`/jobs/${encodeURIComponent(id)}/result`);
  }

  /** `GET /jobs/{id}/download` — the clone as ZIP bytes. */
  async downloadZip(id: string): Promise<Uint8Array> {
    return this.bytes(`/jobs/${encodeURIComponent(id)}/download`);
  }

  /** `GET /jobs/{id}/pdf` — the generated PDF bytes. */
  async getJobPdf(id: string): Promise<Uint8Array> {
    return this.bytes(`/jobs/${encodeURIComponent(id)}/pdf`);
  }

  /** `GET /probe/{url}`. */
  async probe(url: string): Promise<ProbeResult> {
    return this.json<ProbeResult>(`/probe/${encodeURIComponent(url)}`);
  }

  /** `GET /snapshots`, optionally filtered by site URL. */
  async listSnapshots(url?: string): Promise<SnapshotEntry[]> {
    return this.json<SnapshotEntry[]>(`/snapshots${queryString({ url })}`);
  }

  /** `POST /diff`. */
  async diff(a: string, b: string): Promise<DiffReport> {
    return this.json<DiffReport>("/diff", { method: "POST", body: JSON.stringify({ a, b }) });
  }

  /** `GET /versions`, `branch` defaults to the server's `main`. */
  async getVersions(url: string, branch?: string): Promise<VersionLog> {
    return this.json<VersionLog>(`/versions${queryString({ url, branch })}`);
  }

  /** `POST /versions/rollback`. */
  async rollback(url: string, ref: string): Promise<RollbackResult> {
    return this.json<RollbackResult>("/versions/rollback", {
      method: "POST",
      body: JSON.stringify({ url, ref }),
    });
  }

  /** `POST /search`. */
  async search(query: string, mode = "fulltext", dir?: string): Promise<SearchResponse> {
    return this.json<SearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify({ query, mode, dir }),
    });
  }

  /** `GET /schedules`. */
  async listSchedules(): Promise<Schedule[]> {
    return this.json<Schedule[]>("/schedules");
  }

  /** `POST /schedules`. */
  async createSchedule(input: ScheduleInput): Promise<Schedule> {
    return this.json<Schedule>("/schedules", { method: "POST", body: JSON.stringify(input) });
  }

  /** `DELETE /schedules/{id}`. */
  async deleteSchedule(id: string): Promise<{ removed: string }> {
    return this.json<{ removed: string }>(`/schedules/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  /** `POST /schedules/{id}/run`. */
  async runSchedule(id: string): Promise<ScheduleRun> {
    return this.json<ScheduleRun>(`/schedules/${encodeURIComponent(id)}/run`, { method: "POST" });
  }

  /** `GET /workflows`. */
  async listWorkflows(): Promise<Workflow[]> {
    return this.json<Workflow[]>("/workflows");
  }

  /** `POST /workflows`. */
  async saveWorkflow(name: string, steps: WorkflowStepInput[]): Promise<Workflow> {
    return this.json<Workflow>("/workflows", { method: "POST", body: JSON.stringify({ name, steps }) });
  }

  /** `POST /workflows/{id}/run`. */
  async runWorkflow(id: string): Promise<RunResult> {
    return this.json<RunResult>(`/workflows/${encodeURIComponent(id)}/run`, { method: "POST" });
  }

  /** `GET /analytics/engines`, optionally for a single engine. */
  async getEngineStats(engine?: string): Promise<EngineStats[]> {
    return this.json<EngineStats[]>(`/analytics/engines${queryString({ engine })}`);
  }

  /** `GET /analytics/totals`. */
  async getTotals(): Promise<Totals> {
    return this.json<Totals>("/analytics/totals");
  }

  /** `GET /audit`, newest first. */
  async getAudit(limit?: number): Promise<AuditEntry[]> {
    return this.json<AuditEntry[]>(`/audit${queryString({ limit })}`);
  }

  /** `GET /stats` — queue depth and rate-limit configuration. */
  async getStats(): Promise<Stats> {
    return this.json<Stats>("/stats");
  }

  /** `POST /safety/scan` — malware and phishing markers under `dir`. */
  async scanSafety(dir: string): Promise<SafetyReport> {
    return this.json<SafetyReport>("/safety/scan", { method: "POST", body: JSON.stringify({ dir }) });
  }

  /** `POST /ipfs/publish` — publish a clone to IPFS. */
  async publishIpfs(dir: string): Promise<IpfsPublishResult> {
    return this.json<IpfsPublishResult>("/ipfs/publish", { method: "POST", body: JSON.stringify({ dir }) });
  }
}
