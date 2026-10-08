/**
 * Desktop bridge — Tauri sidecar wiring for the dashboard.
 *
 * In a normal browser (`npm run dev` / production web) this module is inert
 * and `API_URL` from `api.ts` (`VITE_API_URL`) is used.
 *
 * Inside the Tauri WebView the Rust sidecar is spawned on a random port with
 * an ephemeral token. This module detects the runtime, fetches `{ url, token }`
 * via `invoke("get_sidecar_config")` or the `sidecar-ready` event, and
 * persists it so `api.ts` can build the right base URL + headers.
 *
 * Static imports are used intentionally: `@tauri-apps/*` is installed in
 * `dashboard/package.json` and the APIs guard internally with `__TAURI__`.
 * The `isTauri()` guard below prevents any native call outside the WebView.
 */

import { invoke } from "@tauri-apps/api/core"
import { listen } from "@tauri-apps/api/event"
import { open as dialogOpen } from "@tauri-apps/plugin-dialog"
import { revealItemInDir } from "@tauri-apps/plugin-opener"
import { sendNotification } from "@tauri-apps/plugin-notification"

export interface SidecarConfig {
  url: string
  token: string
}

const STORAGE_KEY = "zfrog.desktopSidecar"

// Used at 5+ call sites — lockstep Tauri detection is the contract.
function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI__" in window
}

export function isDesktop(): boolean {
  if (isTauri()) return true
  if (typeof window === "undefined") return false
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) !== null || window.localStorage.getItem(STORAGE_KEY) !== null
  } catch {
    return false
  }
}

export function getDesktopConfig(): SidecarConfig | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY) || window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as SidecarConfig
    if (parsed?.url && parsed?.token) return parsed
    return null
  } catch {
    return null
  }
}

function persist(cfg: SidecarConfig): void {
  try {
    const raw = JSON.stringify(cfg)
    // sessionStorage only — token+url are ephemeral per boot (C2: stale localStorage caused offline dashboard after restart)
    window.sessionStorage.setItem(STORAGE_KEY, raw)
    // Clear stale localStorage from older builds so it never shadows sessionStorage.
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
  } catch {
    // ignore quota / private mode
  }
}

export function clearDesktopConfig(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY)
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
  } catch {
    // ignore
  }
}
/**
 * Resolve the sidecar config. Tries `invoke` immediately; if the sidecar
 * hasn't finished booting yet it waits for the `sidecar-ready` event.
 * Resolves to null when not running inside Tauri.
 */
export async function resolveDesktopConfig(timeoutMs = 10_000): Promise<SidecarConfig | null> {
  const cached = getDesktopConfig()
  if (cached) return cached
  if (!isTauri()) return null

  try {
    const cfg = (await invoke<SidecarConfig | null>("get_sidecar_config")) as SidecarConfig | null
    if (cfg?.url && cfg?.token) {
      persist(cfg)
      return cfg
    }
  } catch {
    // invoke not ready yet — fall through to event wait
  }

  return new Promise<SidecarConfig | null>((resolve) => {
    let done = false
    const finish = (cfg: SidecarConfig | null) => {
      if (done) return
      done = true
      if (cfg) persist(cfg)
      resolve(cfg)
    }

    let unlisten: (() => void) | null = null
    const timer = window.setTimeout(() => {
      if (unlisten) unlisten()
      finish(null)
    }, timeoutMs)

    listen<SidecarConfig>("sidecar-ready", (event) => {
      window.clearTimeout(timer)
      if (unlisten) unlisten()
      finish(event.payload)
    })
      .then((u) => {
        unlisten = u
        if (done) unlisten()
      })
      .catch(() => {
        window.clearTimeout(timer)
        finish(null)
      })

    listen<{ reason: string }>("sidecar-failed", (event) => {
      console.error("[desktop] sidecar failed:", event.payload.reason)
      window.clearTimeout(timer)
      if (unlisten) unlisten()
      finish(null)
    })
      .then((u) => {
        void u
      })
      .catch(() => {})
  })
}

/** Headers to attach to every API request when in desktop mode. */
export function desktopHeaders(): Record<string, string> {
  const cfg = getDesktopConfig()
  if (!cfg?.token) return {}
  return { Authorization: `Bearer ${cfg.token}` }
}

/** Effective API base URL — sidecar URL when in desktop, otherwise VITE_API_URL. */
export function effectiveApiUrl(fallback: string): string {
  const cfg = getDesktopConfig()
  return cfg?.url || fallback
}

// ---------------------------------------------------------------------------
// Native helpers (dialogs, opener, notifications) — thin wrappers so routes
// don't import Tauri directly.
// ---------------------------------------------------------------------------

export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) return null
  const selected = await dialogOpen({ directory: true, multiple: false })
  return typeof selected === "string" ? selected : null
}

export async function pickFile(filters?: { name: string; extensions: string[] }[]): Promise<string | null> {
  if (!isTauri()) return null
  const selected = await dialogOpen({ multiple: false, filters })
  return typeof selected === "string" ? selected : null
}

export async function revealInFolder(path: string): Promise<void> {
  if (!isTauri()) return
  await revealItemInDir(path)
}

export async function notifyDesktop(title: string, body: string): Promise<void> {
  if (!isTauri()) return
  await sendNotification({ title, body })
}
