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
      <div className="flex items-baseline justify-between">
        <h1>{t("equipe.title")}</h1>
        <button type="button" className="tui-btn" onClick={() => void load()}>
          {t("equipe.refresh")}
        </button>
      </div>

      {error && (
        <div className="tui-panel" style={{ borderColor: "var(--error)" }}>
          <p style={{ color: "var(--error)" }}>{SYM.fail} {t("equipe.error")}{error}</p>
        </div>
      )}

      {loading ? (
        <p className="empty"><Spinner /> {t("equipe.loading")}</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1.5lh", marginTop: "0.5lh" }}>
          {/* Users section */}
          <div>
            <div className="flex items-baseline justify-between">
              <span className="tui-label">{t("equipe.usersLabel")} ({users.length})</span>
            </div>

            {users.length === 0 ? (
              <p className="empty">{t("equipe.emptyUsers")}</p>
            ) : (
              <table className="tui-table">
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
                      <td>
                        <span style={{ color: u.role === "admin" ? "var(--accent)" : "var(--fg-dim)" }}>
                          [{u.role}]
                        </span>
                      </td>
                      <td style={{ color: "var(--fg-dim)" }}>
                        {u.orgs?.join(", ") || t("equipe.allOrgs")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* New user form */}
            <form onSubmit={handleCreateUser} className="tui-panel" style={{ marginTop: "0.75lh" }}>
              <span className="tui-label">{t("equipe.addUser")}</span>
              <div className="flex gap-2 flex-wrap items-baseline" style={{ marginTop: "0.25lh" }}>
                <input
                  className="tui-input"
                  type="email"
                  value={email}
                  placeholder="email@company.com"
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  style={{ minWidth: "24ch" }}
                />
                <input
                  className="tui-input"
                  value={name}
                  placeholder={t("equipe.namePlaceholder")}
                  onChange={(e) => setName(e.target.value)}
                  style={{ minWidth: "20ch" }}
                />
                <select
                  className="tui-select"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  style={{ width: "auto" }}
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {t(r.key)}
                    </option>
                  ))}
                </select>
                <input
                  className="tui-input"
                  type="password"
                  value={password}
                  placeholder={t("equipe.passwordPlaceholder")}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{ width: "18ch" }}
                />
                <button type="submit" className="tui-btn accent" disabled={savingUser || !email.trim()}>
                  {savingUser ? <Spinner /> : t("equipe.addBtn")}
                </button>
              </div>
            </form>
          </div>

          {/* Organizations section */}
          <div>
            <span className="tui-label">{t("equipe.orgsLabel")} ({orgs.length})</span>
            {orgs.length === 0 ? (
              <p className="empty">{t("equipe.emptyOrgs")}</p>
            ) : (
              <div className="rows" style={{ marginTop: "0.25lh" }}>
                {orgs.map((o) => (
                  <div key={o.id} className="runrow" style={{ gridTemplateColumns: "2ch 20ch 1fr auto" }}>
                    <span style={{ color: "var(--accent)" }}>{SYM.sub}</span>
                    <span style={{ fontWeight: 500 }}>{o.name}</span>
                    <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>id: {o.id}</span>
                    <span style={{ color: "var(--fg-dim)", fontSize: 12 }}>
                      {Object.keys(o.members || {}).length} {t("equipe.members")}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* New organization */}
            <form onSubmit={handleCreateOrg} className="tui-panel" style={{ marginTop: "0.75lh" }}>
              <span className="tui-label">{t("equipe.createOrg")}</span>
              <div className="flex gap-2 items-baseline" style={{ marginTop: "0.25lh" }}>
                <input
                  className="tui-input"
                  value={orgName}
                  placeholder={t("equipe.orgNamePlaceholder")}
                  onChange={(e) => setOrgName(e.target.value)}
                  style={{ maxWidth: "32ch" }}
                />
                <button type="submit" className="tui-btn accent" disabled={savingOrg || !orgName.trim()}>
                  {savingOrg ? <Spinner /> : t("equipe.createBtn")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}

export const Route = createFileRoute("/equipe")({
  component: EquipePage,
})
