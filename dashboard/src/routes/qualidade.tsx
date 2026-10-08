import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, SafetyFinding, SafetyScanResult, IpfsPublishResult, ArweavePublishResult } from "@/lib/api"
import { formatNumber } from "@/lib/utils"
import { Spinner, SYM, TuiPanel } from "@/components/ui/tui"
import { useToast } from "@/components/ToastRegion"
import { useT, type I18nKey } from "@/lib/i18n"

const FINDING_LABELS: Record<string, I18nKey> = {
  obfuscated_js: "qualidade.findings.obfuscated_js",
  crypto_miner: "qualidade.findings.crypto_miner",
  iframe_hidden: "qualidade.findings.iframe_hidden",
  form_exfil: "qualidade.findings.form_exfil",
  meta_refresh_external: "qualidade.findings.meta_refresh_external",
  known_bad_tld: "qualidade.findings.known_bad_tld",
  data_uri_script: "qualidade.findings.data_uri_script",
  suspicious_download: "qualidade.findings.suspicious_download",
  atob_eval: "qualidade.findings.atob_eval",
}

interface FindingGroup {
  kind: string
  label: string
  labelKey?: I18nKey
  detail: string
  severity: string
  files: string[]
  count: number
}

function groupFindings(findings: SafetyFinding[]): FindingGroup[] {
  const groups = new Map<string, FindingGroup>()
  for (const f of findings) {
    const group = groups.get(f.kind) ?? {
      kind: f.kind,
      label: f.kind,
      labelKey: FINDING_LABELS[f.kind],
      detail: f.detail,
      severity: f.severity,
      files: [],
      count: 0,
    }
    group.count += 1
    if (!group.files.includes(f.file)) group.files.push(f.file)
    groups.set(f.kind, group)
  }
  return [...groups.values()]
}

type TabType = "seguranca" | "web3"

function QualidadePage() {
  const t = useT()
  const toast = useToast()
  const [tab, setTab] = useState<TabType>("seguranca")

  // ── Security state ──
  const [result, setResult] = useState<SafetyScanResult | null>(null)
  const [dir, setDir] = useState("")
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Web3 state ──
  const [web3Dir, setWeb3Dir] = useState("")
  const [ipfsResult, setIpfsResult] = useState<IpfsPublishResult | null>(null)
  const [arweaveResult, setArweaveResult] = useState<ArweavePublishResult | null>(null)

  const arweaveStatusQuery = useQuery({
    queryKey: ["arweave-status"],
    queryFn: () => api.getArweaveStatus(),
    enabled: tab === "web3",
  })

  const ipfsMutation = useMutation({
    mutationFn: (d: string) => api.publishIpfs(d),
    onSuccess: (data) => {
      setIpfsResult(data)
      toast(t("qualidade.ipfsOk").replace("{{cid}}", data.cid), "ok")
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("qualidade.ipfsError").replace("{{msg}}", msg), "err")
    },
  })

  const arweaveMutation = useMutation({
    mutationFn: (d: string) => api.publishArweave(d),
    onSuccess: (data) => {
      setArweaveResult(data)
      toast(t("qualidade.arweaveOk").replace("{{tx}}", data.tx_id), "ok")
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast(t("qualidade.arweaveError").replace("{{msg}}", msg), "err")
    },
  })

  const handleScan = async (e: React.FormEvent) => {
    e.preventDefault()
    setScanning(true)
    setError(null)
    try {
      const res = await api.scanSafety(dir.trim() || ".")
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setScanning(false)
    }
  }

  const groups = result ? groupFindings(result.findings) : []
  const arweaveStatus = arweaveStatusQuery.data

  return (
    <TuiPanel
      title={t("qualidade.title")}
      action={
        <div className="toggles text-xs" role="group" aria-label={t("qualidade.sectionAria")}>
          <button
            type="button"
            className="tgl"
            aria-pressed={tab === "seguranca"}
            onClick={() => setTab("seguranca")}
          >
            {t("qualidade.tab.security")}
          </button>
          <button
            type="button"
            className="tgl"
            aria-pressed={tab === "web3"}
            onClick={() => setTab("web3")}
          >
            {t("qualidade.tab.web3")}
          </button>
        </div>
      }
    >
      <div className="text-xs text-[var(--fg-dim)] border-b border-[var(--border)] pb-2 mb-3">
        {tab === "seguranca"
          ? t("qualidade.securityDesc")
          : t("qualidade.web3Desc")}
      </div>

      {tab === "seguranca" ? (
        <>
          {error && (
            <div className="tui-panel" style={{ borderColor: "var(--error)", marginTop: "0.5lh" }}>
              <p style={{ color: "var(--error)" }}>{SYM.fail} {t("qualidade.auditError")}: {error}</p>
            </div>
          )}

          {/* New scan trigger */}
          <form onSubmit={handleScan} className="filters flex-wrap" style={{ gap: "1ch 1.5ch", marginTop: "0.5lh" }}>
            <input
              className="tui-input"
              value={dir}
              placeholder={t("qualidade.scanPlaceholder")}
              onChange={(e) => setDir(e.target.value)}
              style={{ width: "28ch" }}
            />
            <button type="submit" className="tui-btn accent" disabled={scanning}>
              {scanning ? <Spinner /> : t("qualidade.scanBtn")}
            </button>
          </form>

          {/* Latest audit summary */}
          {result && (
            <div style={{ display: "flex", flexDirection: "column", gap: "1lh", marginTop: "0.5lh" }}>
              <div className="tui-panel">
                <div className="tui-panel-head">
                  <span className="tui-label">{t("qualidade.diagnosticTitle")}</span>
                  <span style={{ fontSize: 12, color: "var(--fg-dim)" }}>
                    {result.summary || t("qualidade.scanComplete")}
                  </span>
                </div>
                <dl className="tui-kv">
                  <dt>{t("qualidade.riskLevel")}</dt>
                  <dd style={{ color: result.risk === "clean" ? "var(--ok)" : "var(--error)", fontWeight: 500 }}>
                    {result.risk === "clean" ? t("qualidade.noRisks").replace("{{sym}}", SYM.ok) : `${result.risk.toUpperCase()} (${SYM.fail})`}
                  </dd>
                  <dt>{t("qualidade.filesScanned")}</dt>
                  <dd>{formatNumber(result.files_scanned)} {t("qualidade.filesUnit")}</dd>
                  <dt>{t("qualidade.occurrences")}</dt>
                  <dd>{result.findings.length} {t("qualidade.findingsUnit")}</dd>
                </dl>
              </div>

              {/* Findings */}
              <div>
                <span className="tui-label">{t("qualidade.findingsTitle").replace("{{count}}", String(groups.length))}</span>
                {groups.length === 0 ? (
                  <p className="empty" style={{ color: "var(--ok)" }}>
                    {t("qualidade.noFindings").replace("{{sym}}", SYM.ok)}
                  </p>
                ) : (
                  <div className="rows" style={{ marginTop: "0.25lh" }}>
                    {groups.map((g) => (
                      <div
                        key={g.kind}
                        style={{
                          borderBottom: "1px solid var(--line)",
                          padding: "0.5lh 0",
                          display: "flex",
                          flexDirection: "column",
                          gap: "0.25lh",
                        }}
                      >
                        <div className="flex items-baseline justify-between">
                          <div className="flex items-baseline gap-2">
                            <span style={{ color: g.severity === "high" ? "var(--error)" : "var(--warn)", fontWeight: 500 }}>
                              [{g.severity.toUpperCase()}]
                            </span>
                            <span style={{ fontWeight: 500 }}>{g.labelKey ? t(g.labelKey) : g.label}</span>
                          </div>
                          <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>
                            {t("qualidade.occurrencesIn").replace("{{count}}", String(g.count)).replace("{{files}}", String(g.files.length))}
                          </span>
                        </div>

                        <p style={{ color: "var(--fg-muted)", fontSize: 12 }}>{g.detail}</p>

                        <div className="tui-tags" style={{ marginTop: "0.125lh" }}>
                          {g.files.slice(0, 5).map((f) => (
                            <span key={f} className="tui-tag" style={{ cursor: "default" }}>
                              {f}
                            </span>
                          ))}
                          {g.files.length > 5 && (
                            <span className="tui-tag" style={{ cursor: "default", color: "var(--fg-dim)" }}>
                              {t("qualidade.moreFiles").replace("{{count}}", String(g.files.length - 5))}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      ) : (
        /* Web3 tab: IPFS and Arweave */
        <div className="flex flex-col gap-4" style={{ marginTop: "0.5lh" }}>
          {/* Arweave status */}
          <div className="tui-panel p-4 text-xs">
            <div className="font-bold border-b border-[var(--border)] pb-1 mb-2">
              {t("qualidade.arweaveStatusTitle")}
            </div>
            {arweaveStatusQuery.isLoading ? (
              <p className="text-[var(--fg-dim)]"><Spinner /> {t("qualidade.loadingArweave")}</p>
            ) : arweaveStatus ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <div>
                  <span className="text-[var(--fg-dim)] block">{t("qualidade.gateway")}</span>
                  <b>{arweaveStatus.gateway || "https://arweave.net"}</b>
                </div>
                <div>
                  <span className="text-[var(--fg-dim)] block">{t("qualidade.jwkWallet")}</span>
                  <span style={{ color: arweaveStatus.wallet ? "var(--ok)" : "var(--warn)" }}>
                    {arweaveStatus.wallet ? `${SYM.ok} ${t("qualidade.configured")}` : `${SYM.fail} ${t("qualidade.notConfigured")}`}
                  </span>
                </div>
                <div>
                  <span className="text-[var(--fg-dim)] block">{t("qualidade.permawebMode")}</span>
                  <span>{arweaveStatus.enabled ? t("qualidade.enabled") : t("qualidade.disabled")}</span>
                </div>
              </div>
            ) : (
              <p className="text-[var(--fg-dim)]">{t("qualidade.arweaveNotReady")}</p>
            )}
          </div>

          {/* Publish panel */}
          <div className="tui-panel p-4 text-xs">
            <div className="font-bold border-b border-[var(--border)] pb-1 mb-3">
              {t("qualidade.publishTitle")}
            </div>
            <div className="flex flex-col gap-3 max-w-xl">
              <div>
                <label className="text-[var(--fg-dim)] block mb-1">{t("qualidade.cloneDirLabel")}</label>
                <input
                  type="text"
                  className="tui-input w-full font-mono text-[11px]"
                  placeholder="output/example.com"
                  value={web3Dir}
                  onChange={(e) => setWeb3Dir(e.target.value)}
                />
              </div>

              <div className="flex items-center gap-3 pt-2">
                <button
                  type="button"
                  className="tui-btn accent"
                  onClick={() => ipfsMutation.mutate(web3Dir.trim())}
                  disabled={ipfsMutation.isPending || !web3Dir.trim()}
                >
                  {ipfsMutation.isPending ? <Spinner /> : SYM.ok} {t("qualidade.publishIpfs")}
                </button>
                <button
                  type="button"
                  className="tui-btn"
                  onClick={() => arweaveMutation.mutate(web3Dir.trim())}
                  disabled={arweaveMutation.isPending || !web3Dir.trim()}
                >
                  {arweaveMutation.isPending ? <Spinner /> : SYM.ok} {t("qualidade.archiveArweave")}
                </button>
              </div>
            </div>

            {/* IPFS results */}
            {ipfsResult && (
              <div className="mt-4 p-3 border border-[var(--accent)] bg-[var(--bg-panel)]">
                <div className="font-bold text-[var(--accent)] mb-1">{t("qualidade.ipfsSuccess")}</div>
                <div className="font-mono text-[11px]">CID: <b>{ipfsResult.cid}</b></div>
                <div className="text-[10px] text-[var(--fg-dim)] mt-1">
                  gateway: <a href={ipfsResult.gateway_url} target="_blank" rel="noreferrer" className="underline">{ipfsResult.gateway_url}</a>
                </div>
              </div>
            )}

            {/* Arweave results */}
            {arweaveResult && (
              <div className="mt-4 p-3 border border-[var(--ok)] bg-[var(--bg-panel)]">
                <div className="font-bold text-[var(--ok)] mb-1">{t("qualidade.arweaveSuccess")}</div>
                <div className="font-mono text-[11px]">TX ID: <b>{arweaveResult.tx_id}</b></div>
                <div className="text-[10px] text-[var(--fg-dim)] mt-1">
                  {t("qualidade.permawebLink")} <a href={arweaveResult.gateway_url} target="_blank" rel="noreferrer" className="underline">{arweaveResult.gateway_url}</a>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </TuiPanel>
  )
}

export const Route = createFileRoute("/qualidade")({
  component: QualidadePage,
})
