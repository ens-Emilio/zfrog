/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API URL reachable from the **browser** (not the compose service name). */
  readonly VITE_API_URL?: string
  /** URL WebSocket da API; cai para VITE_API_URL com http→ws se ausente. */
  readonly VITE_WS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
