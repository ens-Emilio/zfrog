import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { api, AppUser, Organization } from "@/lib/api"
import { useToast } from "@/components/ToastRegion"
import { Spinner, SYM } from "@/components/ui/tui"
import { useT } from "@/lib/i18n"

const ROLES = [
  { value: "viewer", key: "equipe.roleViewer" },
  { value: "operator", key: "equipe.roleOperator" },
  { value: "admin", key: "equipe.roleAdmin" },
] as const

function EquipePage() {
  const t = useT()
  const toast = useToast()

  const [users, setUsers] = useState<AppUser[]>([])
  const [orgs, setOrgs] = useState<Organization[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState("viewer")
  const [password, setPassword] = useState("")
  const [savingUser, setSavingUser] = useState(false)

  const [orgName, setOrgName] = useState("")
  const [savingOrg, setSavingOrg] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [u, o] = await Promise.all([api.getUsers(), api.getOrgs()])
      setUsers(u)
      setOrgs(o)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) return
    setSavingUser(true)
    try {
      await api.createUser({
        email: email.trim(),
        name: name.trim() || undefined,
        role,
        password: password.trim() || undefined,
      })
      toast(t("equipe.userCreatedOk"))
      setEmail("")
      setName("")
      setPassword("")
      void load()
    } catch (err) {
      toast(err instanceof Error ? err.message : t("equipe.createUserFailed"), "err")
    } finally {
      setSavingUser(false)
    }
  }

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!orgName.trim()) return
    setSavingOrg(true)
    try {
      await api.createOrg({ name: orgName.trim(), owner: users[0]?.id || "admin" })
      toast(t("equipe.orgCreatedOk"))
      setOrgName("")
      void load()
    } catch (err) {
      toast(err instanceof Error ? err.message : t("equipe.createOrgFailed"), "err")
    } finally {
      setSavingOrg(false)
    }
  }

  return (
    <>
      <div className="zf-head">
        <h1 className="zf-title">{t("equipe.title")}</h1>
        <span className="spacer" style={{ flex: 1 }} />
        <button type="button" className="zf-btn" onClick={() => void load()}>
          {t("equipe.refresh")}
        </button>
      </div>

      {error && (
        <div className="zf-panel" style={{ borderColor: "var(--error)", padding: "var(--s4)", marginBottom: "var(--s4)" }}>
          <p style={{ color: "var(--error)", margin: 0 }}>{SYM.fail} {t("equipe.error")}{error}</p>
        </div>
      )}

      {loading ? (
        <div className="zf-empty"><Spinner /> {t("equipe.loading")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s5)" }}>
          {/* Users */}
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("equipe.usersLabel")} · {users.length}</span></div>
            {users.length === 0 ? (
              <div className="zf-panel-bd"><p className="zf-meta" style={{ margin: 0 }}>{t("equipe.emptyUsers")}</p></div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="zf-table">
                  <thead>
                    <tr>
                      <th>{t("equipe.thName")}</th>
                      <th>{t("equipe.thEmail")}</th>
                      <th>{t("equipe.thRole")}</th>
                      <th>{t("equipe.thOrgs")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td style={{ fontWeight: 500 }}>{u.name || "—"}</td>
                        <td>{u.email}</td>
                        <td><span className="zf-chip" style={{ cursor: "default" }}>[{u.role}]</span></td>
                        <td style={{ color: "var(--muted)" }}>{u.orgs?.join(", ") || t("equipe.allOrgs")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="zf-panel-bd" style={{ borderTop: "1px solid var(--border)" }}>
              <form onSubmit={handleCreateUser} style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap", alignItems: "flex-end" }}>
                <div className="zf-field" style={{ minWidth: "22ch" }}>
                  <label className="zf-label">email</label>
                  <input className="zf-input" type="email" value={email} placeholder="email@company.com" onChange={(e) => setEmail(e.target.value)} required />
                </div>
                <div className="zf-field" style={{ minWidth: "18ch" }}>
                  <label className="zf-label">{t("equipe.namePlaceholder")}</label>
                  <input className="zf-input" value={name} placeholder={t("equipe.namePlaceholder")} onChange={(e) => setName(e.target.value)} />
                </div>
                <div className="zf-field">
                  <label className="zf-label">{t("equipe.thRole")}</label>
                  <select className="zf-select" value={role} onChange={(e) => setRole(e.target.value)}>
                    {ROLES.map((r) => (
                      <option key={r.value} value={r.value}>{t(r.key)}</option>
                    ))}
                  </select>
                </div>
                <div className="zf-field" style={{ width: "18ch" }}>
                  <label className="zf-label">{t("equipe.passwordPlaceholder")}</label>
                  <input className="zf-input" type="password" value={password} placeholder={t("equipe.passwordPlaceholder")} onChange={(e) => setPassword(e.target.value)} />
                </div>
                <button type="submit" className="zf-btn zf-btn--primary" disabled={savingUser || !email.trim()}>
                  {savingUser ? <Spinner /> : t("equipe.addBtn")}
                </button>
              </form>
            </div>
          </div>

          {/* Organizations */}
          <div className="zf-panel">
            <div className="zf-panel-hd"><span className="zf-micro">{t("equipe.orgsLabel")} · {orgs.length}</span></div>
            {orgs.length === 0 ? (
              <div className="zf-panel-bd"><p className="zf-meta" style={{ margin: 0 }}>{t("equipe.emptyOrgs")}</p></div>
            ) : (
              <div className="zf-list">
                {orgs.map((o) => (
                  <div key={o.id} style={{ display: "flex", alignItems: "baseline", gap: "var(--s3)", flexWrap: "wrap" }}>
                    <span style={{ color: "var(--accent)", fontFamily: "var(--font-mono)" }}>{SYM.sub}</span>
                    <span style={{ fontWeight: 500 }}>{o.name}</span>
                    <span className="zf-meta">id: {o.id}</span>
                    <span className="zf-meta" style={{ marginLeft: "auto" }}>{Object.keys(o.members || {}).length} {t("equipe.members")}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="zf-panel-bd" style={{ borderTop: "1px solid var(--border)" }}>
              <form onSubmit={handleCreateOrg} style={{ display: "flex", gap: "var(--s2)", alignItems: "flex-end", flexWrap: "wrap" }}>
                <div className="zf-field" style={{ maxWidth: "32ch", flex: 1 }}>
                  <label className="zf-label">{t("equipe.orgNamePlaceholder")}</label>
                  <input className="zf-input" value={orgName} placeholder={t("equipe.orgNamePlaceholder")} onChange={(e) => setOrgName(e.target.value)} />
                </div>
                <button type="submit" className="zf-btn zf-btn--primary" disabled={savingOrg || !orgName.trim()}>
                  {savingOrg ? <Spinner /> : t("equipe.createBtn")}
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/equipe")({
  component: EquipePage,
})
