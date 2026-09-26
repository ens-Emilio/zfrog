/**
 * End-to-end tests for the Zfrog JS SDK.
 *
 * A real `Bun.serve` HTTP server stands in for the API: every call goes over a
 * real socket, and the server records what it received so the tests can assert
 * on the wire format (path, query, headers, body) and not just on the client's
 * own parsing.
 */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import type { Server } from "bun";

import { ZfrogClient, ZfrogError } from "../src/index";
import type {
  AuditEntry,
  DiffReport,
  EngineStats,
  IpfsPublishResult,
  Job,
  JobResult,
  ProbeResult,
  RunResult,
  SafetyReport,
  Schedule,
  SearchResponse,
  SnapshotEntry,
  Stats,
  Totals,
  VersionLog,
  Workflow,
} from "../src/index";

interface Recorded {
  method: string;
  path: string;
  query: URLSearchParams;
  headers: Headers;
  body: string;
}

const JOB: Job = {
  id: "job-1",
  url: "https://example.com",
  mode: "mirror",
  max_depth: 3,
  status: "completed",
  probe: null,
  output_path: "/tmp/output/example.com",
  created_at: "2026-01-01T00:00:00",
  updated_at: "2026-01-01T00:01:00",
  error: null,
};

const JOB_RESULT: JobResult = {
  job_id: "job-1",
  output_path: "/tmp/output/example.com",
  files_count: 12,
  total_size_bytes: 4096,
  engine_used: "wget",
  duration_seconds: 1.5,
};

const PROBE: ProbeResult = {
  url: "https://example.com",
  is_spa: true,
  has_js_rendering: true,
  robots_restricted: false,
  framework: "react",
  content_type: "text/html",
  suggested_engine: "playwright",
  status_code: 200,
  final_url: "https://example.com/",
};

const SNAPSHOT: SnapshotEntry = {
  slug: "example.com",
  file: "20260101.json",
  url: "https://example.com",
  captured_at: "2026-01-01T00:00:00",
  pages: 3,
};

const DIFF: DiffReport = {
  url: "https://example.com",
  a: "snap-a",
  b: "snap-b",
  added: ["new.html"],
  removed: [],
  changed: ["index.html"],
  unchanged: [],
  change_ratio: 0.5,
  details: [{ path: "index.html", ratio: 0.5 }],
};

const VERSION_LOG: VersionLog = {
  url: "https://example.com",
  branch: "dev",
  branches: ["main", "dev"],
  versions: [
    {
      id: "abcdef12",
      url: "https://example.com",
      snapshot: "snap-a",
      captured_at: "2026-01-01T00:00:00",
      message: "crawl",
      parent: null,
      branch: "dev",
      pages: 3,
      files: { "index.html": "deadbeef" },
    },
  ],
};

const SEARCH: SearchResponse = {
  query: "hello",
  mode: "semantic",
  hits: [{ path: "index.html", url: "https://example.com", title: "Home", snippet: "hello world", score: 0.9 }],
};

const SCHEDULE: Schedule = {
  id: "sched-1",
  cron: "0 * * * *",
  url: "https://example.com",
  mode: "mirror",
  max_depth: 1,
  enabled: true,
  last_run: null,
  next_run: "2026-01-01T01:00:00",
};

const WORKFLOW: Workflow = {
  id: "wf-1",
  name: "nightly",
  steps: [{ id: "step-0", type: "fetch", params: { url: "https://example.com" }, needs: [] }],
};

const RUN_RESULT: RunResult = {
  workflow_id: "wf-1",
  status: "completed",
  steps: [{ type: "fetch", status: "ok", detail: "", output: "/tmp/output" }],
  error: null,
};

const ENGINE_STATS: EngineStats = {
  engine: "wget",
  runs: 4,
  succeeded: 3,
  failed: 1,
  success_rate: 0.75,
  avg_duration_s: 2.5,
  avg_bytes: 1024,
  total_bytes: 4096,
  avg_files: 3,
  total_cost: 0,
  avg_cost: 0,
};

const TOTALS: Totals = {
  runs: 4,
  succeeded: 3,
  failed: 1,
  success_rate: 0.75,
  bytes: 4096,
  avg_duration_s: 2.5,
  cost: 0,
  currency: "USD",
};

const AUDIT: AuditEntry = {
  timestamp: "2026-01-01T00:00:00",
  action: "job.create",
  actor: "127.0.0.1",
  target: "https://example.com",
  outcome: "ok",
  detail: "",
  metadata: { mode: "mirror" },
};

const STATS: Stats = {
  total_jobs: 7,
  completed: 5,
  failed: 1,
  running: 1,
  concurrent_slots_available: 3,
  rate_limit_rps: 10,
};

const SAFETY: SafetyReport = {
  files_scanned: 2,
  findings: [
    {
      kind: "hidden_iframe",
      severity: "high",
      file: "/tmp/output/example.com/index.html",
      detail: "hidden iframe",
      evidence: "<iframe hidden",
    },
  ],
  risk: "high",
  summary: "1 finding",
};

const IPFS: IpfsPublishResult = {
  cid: "bafybeigdyrzt",
  name: "example.com",
  size: 4096,
  files: 12,
  gateway_url: "https://ipfs.io/ipfs/bafybeigdyrzt",
};

const ZIP_BYTES = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0xff, 0x00, 0x7f]);
const PDF_BYTES = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34]);

const API_KEY = "s3cret-key";

let server: Server;
let baseUrl = "";
const recorded: Recorded[] = [];

/** The request the server handled most recently. */
function lastRequest(): Recorded {
  const request = recorded.at(-1);
  if (!request) {
    throw new Error("the test server received no request");
  }
  return request;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

beforeAll(() => {
  server = Bun.serve({
    port: 0,
    async fetch(request) {
      const url = new URL(request.url);
      const body = request.method === "GET" || request.method === "DELETE" ? "" : await request.text();
      recorded.push({
        method: request.method,
        path: url.pathname,
        query: url.searchParams,
        headers: request.headers,
        body,
      });

      const path = url.pathname;
      const payload = body === "" ? {} : (JSON.parse(body) as Record<string, unknown>);

      if (path === "/health") {
        return json({ status: "ok" });
      }
      if (path === "/jobs" && request.method === "POST") {
        return json({ ...JOB, url: payload.url, mode: payload.mode, max_depth: payload.max_depth }, 201);
      }
      if (path === "/jobs" && request.method === "GET") {
        return json([JOB]);
      }
      if (path === "/jobs/job-1" && request.method === "GET") {
        return json(JOB);
      }
      if (path === "/jobs/missing") {
        return json({ detail: "Job not found" }, 404);
      }
      if (path === "/jobs/job-1/cancel") {
        return json({ message: "Job job-1 marked for cancellation" });
      }
      if (path === "/jobs/job-1/result") {
        return json(JOB_RESULT);
      }
      if (path === "/jobs/job-1/download") {
        return new Response(ZIP_BYTES, { headers: { "content-type": "application/zip" } });
      }
      if (path === "/jobs/job-1/pdf") {
        return new Response(PDF_BYTES, { headers: { "content-type": "application/pdf" } });
      }
      if (path.startsWith("/probe/")) {
        return json({ ...PROBE, url: decodeURIComponent(path.slice("/probe/".length)) });
      }
      if (path === "/snapshots") {
        return json([SNAPSHOT]);
      }
      if (path === "/diff") {
        return json({ ...DIFF, a: payload.a, b: payload.b });
      }
      if (path === "/versions") {
        return json({ ...VERSION_LOG, url: url.searchParams.get("url"), branch: url.searchParams.get("branch") });
      }
      if (path === "/versions/rollback") {
        return json({ restored: `/tmp/versions/${String(payload.url)}`, files: 7 });
      }
      if (path === "/search") {
        return json({ ...SEARCH, query: payload.query, mode: payload.mode });
      }
      if (path === "/schedules" && request.method === "GET") {
        return json([SCHEDULE]);
      }
      if (path === "/schedules" && request.method === "POST") {
        return json({ ...SCHEDULE, cron: payload.cron, url: payload.url, mode: payload.mode, max_depth: payload.max_depth });
      }
      if (path === "/schedules/sched-1" && request.method === "DELETE") {
        return json({ removed: "sched-1" });
      }
      if (path === "/schedules/sched-1/run") {
        return json({ job_id: "job-1" });
      }
      if (path === "/workflows" && request.method === "GET") {
        return json([WORKFLOW]);
      }
      if (path === "/workflows" && request.method === "POST") {
        return json({ id: "wf-1", name: payload.name, steps: payload.steps });
      }
      if (path === "/workflows/wf-1/run") {
        return json(RUN_RESULT);
      }
      if (path === "/analytics/engines") {
        return json([ENGINE_STATS]);
      }
      if (path === "/analytics/totals") {
        return json(TOTALS);
      }
      if (path === "/audit") {
        return json([AUDIT]);
      }
      if (path === "/stats") {
        return json(STATS);
      }
      if (path === "/safety/scan") {
        return json(SAFETY);
      }
      if (path === "/ipfs/publish") {
        return json(IPFS);
      }
      if (path === "/jobs/plain-error") {
        return new Response("boom", { status: 500, headers: { "content-type": "text/plain" } });
      }
      return json({ detail: "not found" }, 404);
    },
  });
  baseUrl = `http://127.0.0.1:${server.port}`;
});

afterAll(() => {
  server.stop(true);
});

/** Client pointed at the test server; a fresh one per call keeps assertions crisp. */
function client(options: { apiKey?: string; timeoutMs?: number } = {}): ZfrogClient {
  return new ZfrogClient({ baseUrl, ...options });
}

describe("ZfrogClient", () => {
  test("health returns the API status", async () => {
    const response = await client().health();

    expect(response).toEqual({ status: "ok" });
    expect(lastRequest().path).toBe("/health");
  });

  test("createJob posts the documented body and parses the Job", async () => {
    const job = await client().createJob({ url: "https://example.com", mode: "singlepage", max_depth: 2 });

    const request = lastRequest();
    expect(request.method).toBe("POST");
    expect(request.path).toBe("/jobs");
    expect(request.headers.get("content-type")).toContain("application/json");
    expect(JSON.parse(request.body)).toEqual({ url: "https://example.com", mode: "singlepage", max_depth: 2 });

    expect(job.id).toBe("job-1");
    expect(job.url).toBe("https://example.com");
    expect(job.mode).toBe("singlepage");
    expect(job.max_depth).toBe(2);
    expect(job.status).toBe("completed");
    expect(job.output_path).toBe("/tmp/output/example.com");
    expect(job.error).toBeNull();
  });

  test("createJob omits the optional fields the caller did not set", async () => {
    await client().createJob({ url: "https://example.com", mode: "mirror" });

    expect(JSON.parse(lastRequest().body)).toEqual({ url: "https://example.com", mode: "mirror" });
  });

  test("apiKey is sent as a bearer token on every request", async () => {
    const authed = client({ apiKey: API_KEY });
    await authed.health();
    expect(lastRequest().headers.get("authorization")).toBe(`Bearer ${API_KEY}`);

    await authed.listJobs();
    expect(lastRequest().headers.get("authorization")).toBe(`Bearer ${API_KEY}`);

    await client().health();
    expect(lastRequest().headers.get("authorization")).toBeNull();
  });

  test("a 404 raises ZfrogError with the status and the parsed detail", async () => {
    const failure = await client()
      .getJob("missing")
      .then(() => null)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ZfrogError);
    expect(failure).toBeInstanceOf(Error);
    const error = failure as ZfrogError;
    expect(error.status).toBe(404);
    expect(error.detail).toBe("Job not found");
    expect(error.body).toBe(JSON.stringify({ detail: "Job not found" }));
    expect(error.message).toContain("404");
  });

  test("a non-JSON error body keeps the raw text as the detail", async () => {
    const failure = (await client()
      .getJob("plain-error")
      .then(() => null)
      .catch((error: unknown) => error)) as ZfrogError;

    expect(failure.status).toBe(500);
    expect(failure.detail).toBe("boom");
    expect(failure.body).toBe("boom");
  });

  test("a connection failure raises ZfrogError with status 0", async () => {
    const ephemeral = Bun.serve({ port: 0, fetch: () => new Response("unused") });
    const closedUrl = `http://127.0.0.1:${ephemeral.port}`;
    ephemeral.stop(true);

    const failure = (await new ZfrogClient({ baseUrl: closedUrl })
      .health()
      .then(() => null)
      .catch((error: unknown) => error)) as ZfrogError;

    expect(failure).toBeInstanceOf(ZfrogError);
    expect(failure.status).toBe(0);
    expect(failure.message).toContain(closedUrl);
  });

  test("timeoutMs aborts a slow request as ZfrogError with status 0", async () => {
    // The real platform clock is the thing under test here: `AbortSignal.timeout`
    // has to cancel a request that is genuinely still in flight, which fake
    // timers cannot produce.
    const slow = Bun.serve({
      port: 0,
      async fetch() {
        await Bun.sleep(500);
        return new Response(JSON.stringify({ status: "ok" }), { headers: { "content-type": "application/json" } });
      },
    });

    try {
      const failure = (await new ZfrogClient({ baseUrl: `http://127.0.0.1:${slow.port}`, timeoutMs: 50 })
        .health()
        .then(() => null)
        .catch((error: unknown) => error)) as ZfrogError;

      expect(failure).toBeInstanceOf(ZfrogError);
      expect(failure.status).toBe(0);
    } finally {
      slow.stop(true);
    }
  });

  test("downloadZip returns raw bytes and never parses them as JSON", async () => {
    const bytes = await client().downloadZip("job-1");

    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(bytes.length).toBe(ZIP_BYTES.length);
    expect(Array.from(bytes)).toEqual(Array.from(ZIP_BYTES));
    expect(lastRequest().path).toBe("/jobs/job-1/download");
  });

  test("getJobPdf returns the PDF bytes", async () => {
    const bytes = await client().getJobPdf("job-1");

    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(Array.from(bytes)).toEqual(Array.from(PDF_BYTES));
  });

  test("search sends the mode and returns the hits", async () => {
    const response = await client().search("hello", "semantic");

    expect(JSON.parse(lastRequest().body)).toEqual({ query: "hello", mode: "semantic" });
    expect(lastRequest().path).toBe("/search");
    expect(response.mode).toBe("semantic");
    expect(response.hits).toHaveLength(1);
    expect(response.hits[0]?.path).toBe("index.html");
    expect(response.hits[0]?.score).toBeCloseTo(0.9);
  });

  test("search defaults to fulltext and forwards dir when given", async () => {
    await client().search("hello");
    expect(JSON.parse(lastRequest().body)).toEqual({ query: "hello", mode: "fulltext" });

    await client().search("hello", "fulltext", "/tmp/output");
    expect(JSON.parse(lastRequest().body)).toEqual({ query: "hello", mode: "fulltext", dir: "/tmp/output" });
  });

  test("getVersions builds the query string with both params", async () => {
    const log = await client().getVersions("https://example.com", "dev");

    const request = lastRequest();
    expect(request.path).toBe("/versions");
    expect(request.query.get("url")).toBe("https://example.com");
    expect(request.query.get("branch")).toBe("dev");
    expect(log.branch).toBe("dev");
    expect(log.branches).toEqual(["main", "dev"]);
    expect(log.versions[0]?.id).toBe("abcdef12");
  });

  test("getVersions omits branch when the caller does not pick one", async () => {
    await client().getVersions("https://example.com");

    expect(lastRequest().query.get("url")).toBe("https://example.com");
    expect(lastRequest().query.has("branch")).toBe(false);
  });

  test("job endpoints hit the documented paths", async () => {
    const api = client();

    expect((await api.listJobs())[0]?.id).toBe("job-1");
    expect(lastRequest().method).toBe("GET");
    expect(lastRequest().path).toBe("/jobs");

    expect((await api.getJob("job-1")).id).toBe("job-1");
    expect(lastRequest().path).toBe("/jobs/job-1");

    expect((await api.cancelJob("job-1")).message).toContain("cancellation");
    expect(lastRequest().method).toBe("POST");
    expect(lastRequest().path).toBe("/jobs/job-1/cancel");

    const result = await api.getJobResult("job-1");
    expect(lastRequest().path).toBe("/jobs/job-1/result");
    expect(result.files_count).toBe(12);
    expect(result.engine_used).toBe("wget");
  });

  test("probe encodes the target URL into the path", async () => {
    const probe = await client().probe("https://example.com/a?b=1");

    expect(decodeURIComponent(lastRequest().path)).toBe("/probe/https://example.com/a?b=1");
    expect(probe.suggested_engine).toBe("playwright");
    expect(probe.framework).toBe("react");
  });

  test("snapshots, diff and rollback round-trip", async () => {
    const api = client();

    expect((await api.listSnapshots("https://example.com"))[0]?.slug).toBe("example.com");
    expect(lastRequest().path).toBe("/snapshots");
    expect(lastRequest().query.get("url")).toBe("https://example.com");

    await api.listSnapshots();
    expect(lastRequest().query.has("url")).toBe(false);

    const report = await api.diff("snap-a", "snap-b");
    expect(JSON.parse(lastRequest().body)).toEqual({ a: "snap-a", b: "snap-b" });
    expect(report.a).toBe("snap-a");
    expect(report.added).toEqual(["new.html"]);

    const rollback = await api.rollback("https://example.com", "abcdef12");
    expect(JSON.parse(lastRequest().body)).toEqual({ url: "https://example.com", ref: "abcdef12" });
    expect(rollback.files).toBe(7);
  });

  test("schedule endpoints hit the documented paths", async () => {
    const api = client();

    expect((await api.listSchedules())[0]?.cron).toBe("0 * * * *");

    const created = await api.createSchedule({ cron: "*/5 * * * *", url: "https://example.com", mode: "scrape", max_depth: 2 });
    expect(lastRequest().method).toBe("POST");
    expect(JSON.parse(lastRequest().body)).toEqual({
      cron: "*/5 * * * *",
      url: "https://example.com",
      mode: "scrape",
      max_depth: 2,
    });
    expect(created.cron).toBe("*/5 * * * *");
    expect(created.mode).toBe("scrape");

    expect((await api.deleteSchedule("sched-1")).removed).toBe("sched-1");
    expect(lastRequest().method).toBe("DELETE");
    expect(lastRequest().path).toBe("/schedules/sched-1");

    expect((await api.runSchedule("sched-1")).job_id).toBe("job-1");
    expect(lastRequest().path).toBe("/schedules/sched-1/run");
  });

  test("workflow endpoints hit the documented paths", async () => {
    const api = client();

    expect((await api.listWorkflows())[0]?.name).toBe("nightly");

    const steps = [{ type: "fetch", params: { url: "https://example.com" } }];
    const saved = await api.saveWorkflow("nightly", steps);
    expect(JSON.parse(lastRequest().body)).toEqual({ name: "nightly", steps });
    expect(saved.name).toBe("nightly");

    const run = await api.runWorkflow("wf-1");
    expect(lastRequest().path).toBe("/workflows/wf-1/run");
    expect(run.status).toBe("completed");
    expect(run.steps[0]?.status).toBe("ok");
  });

  test("analytics and audit endpoints hit the documented paths", async () => {
    const api = client();

    const stats = await api.getEngineStats("wget");
    expect(lastRequest().path).toBe("/analytics/engines");
    expect(lastRequest().query.get("engine")).toBe("wget");
    expect(stats[0]?.success_rate).toBeCloseTo(0.75);

    await api.getEngineStats();
    expect(lastRequest().query.has("engine")).toBe(false);

    expect((await api.getTotals()).currency).toBe("USD");
    expect(lastRequest().path).toBe("/analytics/totals");

    const audit = await api.getAudit(5);
    expect(lastRequest().path).toBe("/audit");
    expect(lastRequest().query.get("limit")).toBe("5");
    expect(audit[0]?.action).toBe("job.create");

    await api.getAudit();
    expect(lastRequest().query.has("limit")).toBe(false);
  });

  test("stats, safety and ipfs endpoints hit the documented paths", async () => {
    const api = client();

    const stats = await api.getStats();
    expect(lastRequest().path).toBe("/stats");
    expect(stats.total_jobs).toBe(7);
    expect(stats.concurrent_slots_available).toBe(3);

    const safety = await api.scanSafety("/tmp/output/example.com");
    expect(lastRequest().path).toBe("/safety/scan");
    expect(JSON.parse(lastRequest().body)).toEqual({ dir: "/tmp/output/example.com" });
    expect(safety.risk).toBe("high");
    expect(safety.findings[0]?.severity).toBe("high");

    const published = await api.publishIpfs("/tmp/output/example.com");
    expect(lastRequest().path).toBe("/ipfs/publish");
    expect(JSON.parse(lastRequest().body)).toEqual({ dir: "/tmp/output/example.com" });
    expect(published.cid).toBe("bafybeigdyrzt");
    expect(published.gateway_url).toContain(published.cid);
  });

  test("a trailing slash on baseUrl does not double up", async () => {
    const api = new ZfrogClient({ baseUrl: `${baseUrl}/` });

    expect(await api.health()).toEqual({ status: "ok" });
    expect(lastRequest().path).toBe("/health");
  });
});
