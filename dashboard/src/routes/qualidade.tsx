import { createFileRoute } from "@tanstack/react-router"
import { useQuery, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { api, SafetyFinding, SafetyScanResult, IpfsPublishResult, ArweavePublishResult } from "@/lib/api"
import { formatNumber } from "@/lib/utils"
import { Spinner } from "@/components/ui/tui"
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
  const [result, setResult] = useState<SafetyScanResult | null>(null)
  const [dir, setDir] = useState("")
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
    <div className="zf-view">
      <div className="zf-head">
        <h1 className="zf-title">{t("qualidade.title")}</h1>
        <span className="zf-meta">{tab === "seguranca" ? t("qualidade.securityDesc") : t("qualidade.web3Desc")}</span>
      </div>

      <div className="zf-tabs" role="tablist" aria-label={t("qualidade.sectionAria")}>
        <button type="button" className="zf-tab" aria-selected={tab === "seguranca"} onClick={() => setTab("seguranca")}>{t("qualidade.tab.security")}</button>
        <button type="button" className="zf-tab" aria-selected={tab === "web3"} onClick={() => setTab("web3")}>{t("qualidade.tab.web3")}</button>
      </div>

      {tab === "seguranca" ? (
        <div className="zf-stack">
          {error && (
            <div className="zf-panel" style={{ borderColor: "var(--error)" }}><div className="zf-panel-bd"><p style={{ color: "var(--error)", fontSize: "var(--fs-meta)" }}>✗ {t("qualidade.auditError")}: {error}</p></div></div>
          )}

          <form onSubmit={handleScan} className="zf-row">
            <input className="zf-input" value={dir} placeholder={t("qualidade.scanPlaceholder")} onChange={(e) => setDir(e.target.value)} style={{ minWidth: "28ch" }} />
            <button type="submit" className="zf-btn zf-btn--primary" disabled={scanning}>{scanning ? <Spinner /> : t("qualidade.scanBtn")}</button>
          </form>

          {result && (
            <div className="zf-stack">
              <div className="zf-panel">
                <div className="zf-panel-hd"><span className="zf-label">{t("qualidade.diagnosticTitle")}</span><span className="zf-meta" style={{ marginLeft: "auto" }}>{result.summary || t("qualidade.scanComplete")}</span></div>
                <div className="zf-panel-bd">
                  <dl className="zf-kv">
                    <div className="zf-kv-row"><dt>{t("qualidade.riskLevel")}</dt><dd style={{ color: result.risk === "clean" ? "var(--ok)" : "var(--error)", fontWeight: 600 }}>{result.risk === "clean" ? t("qualidade.noRisks").replace("{{sym}}", "✓") : `${result.risk.toUpperCase()} (✗)`}</dd></div>
                    <div className="zf-kv-row"><dt>{t("qualidade.filesScanned")}</dt><dd>{formatNumber(result.files_scanned)} {t("qualidade.filesUnit")}</dd></div>
                    <div className="zf-kv-row"><dt>{t("qualidade.occurrences")}</dt><dd>{result.findings.length} {t("qualidade.findingsUnit")}</dd></div>
                  </dl>
                </div>
              </div>

              <div>
                <span className="zf-label">{t("qualidade.findingsTitle").replace("{{count}}", String(groups.length))}</span>
                {groups.length === 0 ? (
                  <p className="zf-meta" style={{ color: "var(--ok)" }}>{t("qualidade.noFindings").replace("{{sym}}", "✓")}</p>
                ) : (
                  <div className="zf-list" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden", marginTop: "var(--s3)" }}>
                    {groups.map((g) => (
                      <div key={g.kind} style={{ flexDirection: "column", alignItems: "stretch", gap: "var(--s2)" }}>
                        <div className="zf-row" style={{ justifyContent: "space-between", width: "100%" }}>
                          <div className="zf-row">
                            <span className={`zf-flag ${g.severity === "high" ? "zf-flag--err" : "zf-flag--warn"}`}>{g.severity.toUpperCase()}</span>
                            <span style={{ fontWeight: 550 }}>{g.labelKey ? t(g.labelKey) : g.label}</span>
                          </div>
                          <span className="zf-meta">{t("qualidade.occurrencesIn").replace("{{count}}", String(g.count)).replace("{{files}}", String(g.files.length))}</span>
                        </div>
                        <p className="zf-meta">{g.detail}</p>
                        <div className="zf-chips">
                          {g.files.slice(0, 5).map((f) => (<span key={f} className="zf-chip" style={{ cursor: "default" }}>{f}</span>))}
                          {g.files.length > 5 && <span className="zf-chip" style={{ cursor: "default" }}>{t("qualidade.moreFiles").replace("{{count}}", String(g.files.length - 5))}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="zf-stack">
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-label">{t("qualidade.arweaveStatusTitle")}</span></div>
            <div className="zf-panel-bd">
              {arweaveStatusQuery.isLoading ? <p className="zf-meta"><Spinner /> {t("qualidade.loadingArweave")}</p>
              : arweaveStatus ? (
                <div className="zf-split zf-split--2">
                  <div className="zf-stat"><span className="l">{t("qualidade.gateway")}</span><span className="v" style={{ fontSize: 13 }}>{arweaveStatus.gateway || "https://arweave.net"}</span></div>
                  <div className="zf-stat"><span className="l">{t("qualidade.jwkWallet")}</span><span style={{ color: arweaveStatus.wallet ? "var(--ok)" : "var(--warn)", fontWeight: 600 }}>{arweaveStatus.wallet ? `✓ ${t("qualidade.configured")}` : `✗ ${t("qualidade.notConfigured")}`}</span></div>
                  <div className="zf-stat"><span className="l">{t("qualidade.permawebMode")}</span><span className="v" style={{ fontSize: 13 }}>{arweaveStatus.enabled ? t("qualidade.enabled") : t("qualidade.disabled")}</span></div>
                </div>
              ) : <p className="zf-meta">{t("qualidade.arweaveNotReady")}</p>}
            </div>
          </div>

          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-label">{t("qualidade.publishTitle")}</span></div>
            <div className="zf-panel-bd">
              <label className="zf-field"><span className="zf-label">{t("qualidade.cloneDirLabel")}</span><input type="text" className="zf-input" placeholder="output/example.com" value={web3Dir} onChange={(e) => setWeb3Dir(e.target.value)} /></label>
              <div className="zf-row" style={{ paddingTop: "var(--s2)" }}>
                <button type="button" className="zf-btn zf-btn--primary" onClick={() => ipfsMutation.mutate(web3Dir.trim())} disabled={ipfsMutation.isPending || !web3Dir.trim()}>{ipfsMutation.isPending ? <Spinner /> : "✓"} {t("qualidade.publishIpfs")}</button>
                <button type="button" className="zf-btn" onClick={() => arweaveMutation.mutate(web3Dir.trim())} disabled={arweaveMutation.isPending || !web3Dir.trim()}>{arweaveMutation.isPending ? <Spinner /> : "✓"} {t("qualidade.archiveArweave")}</button>
              </div>
              {ipfsResult && (
                <div className="zf-panel" style={{ borderColor: "var(--accent)" }}>
                  <div className="zf-panel-bd">
                    <div style={{ fontWeight: 600, color: "var(--accent)" }}>{t("qualidade.ipfsSuccess")}</div>
                    <div className="zf-code">CID: <b>{ipfsResult.cid}</b></div>
                    <div className="zf-meta">gateway: <a href={ipfsResult.gateway_url} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>{ipfsResult.gateway_url}</a></div>
                  </div>
                </div>
              )}
              {arweaveResult && (
                <div className="zf-panel" style={{ borderColor: "var(--ok)" }}>
                  <div className="zf-panel-bd">
                    <div style={{ fontWeight: 600, color: "var(--ok)" }}>{t("qualidade.arweaveSuccess")}</div>
                    <div className="zf-code">TX ID: <b>{arweaveResult.tx_id}</b></div>
                    <div className="zf-meta">{t("qualidade.permawebLink")} <a href={arweaveResult.gateway_url} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>{arweaveResult.gateway_url}</a></div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export const Route = createFileRoute("/qualidade")({
  component: QualidadePage,
})
