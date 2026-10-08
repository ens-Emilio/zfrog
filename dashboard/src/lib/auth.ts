
/**
 * An API key kept in localStorage, as a fallback to the session cookie.
 *
 * The dashboard normally authenticates with the `zfrog_session` cookie the SSO
 * login sets — see `AuthGate`. This module exists for the case where SSO is not
 * configured and the operator handed out a key instead, which is also what
 * scripts and the CLI use.
 *
 * With no key stored nothing is sent, so local use (auth off, the default) is
 * unchanged.
 */

const STORAGE_KEY = "zfrog.apiKey"

export function getApiKey(): string {
  if (typeof window === "undefined") return ""
  return window.localStorage.getItem(STORAGE_KEY) || ""
}

export function setApiKey(key: string): void {
  if (typeof window === "undefined") return
  const trimmed = key.trim()
  if (trimmed) window.localStorage.setItem(STORAGE_KEY, trimmed)
  else window.localStorage.removeItem(STORAGE_KEY)
}

export function clearApiKey(): void {
  setApiKey("")
}

/** The header every request should carry. Empty when no key is stored. */
export function authHeaders(): Record<string, string> {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}
