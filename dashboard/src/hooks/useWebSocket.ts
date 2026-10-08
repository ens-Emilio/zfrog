import { useCallback, useEffect, useRef, useState } from "react"
import { getDesktopConfig } from "@/lib/desktop"

import { getApiKey } from "@/lib/auth"
/** Must match `WS_SUBPROTOCOL` in zfrog/ws.py: the server echoes only what the
 * client proposed, so the browser has to offer it explicitly. */
export const WS_SUBPROTOCOL = "zfrog.v1"
/** Must match `WS_KEY_PREFIX` in zfrog/ws.py. */
export const WS_KEY_PREFIX = "zfrog.key."

export interface WsEvent {
  type: "progress" | "status" | "screenshot" | "error" | "connected" | "pong"
  data: Record<string, unknown>
  timestamp?: number
}

interface UseWebSocketResult {
  connected: boolean
  lastEvent: WsEvent | null
  events: WsEvent[]
}

export function useWebSocket(
  jobId: string,
  onEvent?: (event: WsEvent) => void
): UseWebSocketResult {
  const [connected, setConnected] = useState(false)
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null)
  const [events, setEvents] = useState<WsEvent[]>([])
  const reconnectTimer = useRef<number | undefined>(undefined)
  const abortedRef = useRef(false)
  const onEventRef = useRef(onEvent)
  const connectRef = useRef<() => void>(() => {})
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempt = useRef(0)

  onEventRef.current = onEvent

  const scheduleReconnect = useCallback(() => {
    if (abortedRef.current) return
    clearTimeout(reconnectTimer.current)

    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt.current), 30000)
    reconnectAttempt.current++

    reconnectTimer.current = window.setTimeout(() => {
      connectRef.current()
    }, delay)
  }, [])
  const connect = useCallback(() => {
    if (!jobId) return

    const desktopToken = getDesktopConfig()?.token
    const baseUrl =
      import.meta.env.VITE_WS_URL ||
      (getDesktopConfig()?.url ? getDesktopConfig()!.url.replace("http", "ws") : null) ||
      import.meta.env.VITE_API_URL?.replace("http", "ws") ||
      "ws://localhost:8000"

    const url = `${baseUrl}/ws/jobs/${jobId}`

    // Credentials: desktop token (Tauri sidecar) takes precedence — it is the
    // only credential that exists in that mode. Otherwise use the stored API key.
    const desktopKey = desktopToken ? `${WS_KEY_PREFIX}${desktopToken}` : null
    const userKey = !desktopKey ? getApiKey() : ""
    const keyProtocol = desktopKey || (userKey ? `${WS_KEY_PREFIX}${userKey}` : null)
    const protocols = keyProtocol ? [WS_SUBPROTOCOL, keyProtocol] : undefined
    try {
      const ws = new WebSocket(url, protocols)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        reconnectAttempt.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const parsed: WsEvent = JSON.parse(event.data)
          setLastEvent(parsed)
          setEvents((prev) => [...prev.slice(-99), parsed])
          onEventRef.current?.(parsed)
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        if (!abortedRef.current) scheduleReconnect()
      }

      ws.onerror = () => {
        setConnected(false)
      }
    } catch {
      if (!abortedRef.current) scheduleReconnect()
    }
  }, [jobId, scheduleReconnect])
  useEffect(() => {
    abortedRef.current = false
    connectRef.current = connect
    connect()
    return () => {
      abortedRef.current = true
      clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return { connected, lastEvent, events }
}
