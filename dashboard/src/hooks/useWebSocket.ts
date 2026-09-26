"use client"
import { useCallback, useEffect, useRef, useState } from "react"

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
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempt = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    if (!jobId) return

    const baseUrl =
      process.env.NEXT_PUBLIC_WS_URL ||
      process.env.NEXT_PUBLIC_API_URL?.replace("http", "ws") ||
      "ws://localhost:8000"

    const url = `${baseUrl}/ws/jobs/${jobId}`

    // The session cookie rides along on the handshake (same-origin, or a
    // configured cross-origin with CORS credentials), and the server checks
    // Origin — so the dashboard puts no credential in the URL. A stored API key
    // is offered as a subprotocol, which is a header: reverse proxies do not log
    // it, unlike a query string.
    const key = getApiKey()
    const protocols = key ? [WS_SUBPROTOCOL, `${WS_KEY_PREFIX}${key}`] : undefined

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
          onEvent?.(parsed)
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        setConnected(false)
        wsRef.current = null
        scheduleReconnect()
      }

      ws.onerror = () => {
        setConnected(false)
      }
    } catch {
      scheduleReconnect()
    }
  }, [jobId, onEvent])

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)

    const delay = Math.min(1000 * Math.pow(2, reconnectAttempt.current), 30000)
    reconnectAttempt.current++

    reconnectTimer.current = setTimeout(() => {
      connect()
    }, delay)
  }, [connect])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return { connected, lastEvent, events }
}
