"use client"
import { useEffect, useState } from "react"
import { api, AppUser, Organization } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty"
import { Modal } from "@/components/ui/modal"
import { useToast } from "@/components/ToastRegion"
import {
  Users,
  Building2,
  UserPlus,
  KeyRound,
  Copy,
  Check,
  RefreshCw,
  ShieldAlert,
  AlertTriangle,
  UsersRound,
  UserCog,
} from "lucide-react"

/**
 * Quem entra no sistema e a que organização cada pessoa pertence. Uma
 * organização separa os dados: o que é de uma não aparece na outra.
 */

/** Papéis disponíveis, na ordem em que aparecem no formulário. */
const ROLE_ORDER = ["viewer", "operator", "admin"]

/** Nome em português de cada papel, incluindo os que a tela ainda não conhece. */
const ROLE_LABELS: Record<string, string> = {
  viewer: "Visualizador",
  operator: "Operador",
  admin: "Administrador",
}

/** O que cada papel pode fazer, em uma frase. */
const ROLE_HELP: Record<string, string> = {
  viewer: "Só olha: vê as cópias e os relatórios.",
  operator: "Olha e roda: também cria e cancela extrações.",
  admin: "Faz tudo, inclusive mexer em usuários, organizações e chaves.",
}

/** A cor do papel no protótipo: admin em destaque, operator em info, resto neutro. */
function roleVariant(role: string): "accent" | "info" | "neutral" {
  if (role === "admin") return "accent"
  if (role === "operator") return "info"
  return "neutral"
}

export default function EquipePage() {
  const toast = useToast()

  const [users, setUsers] = useState<AppUser[]>([])
  const [usersLoading, setUsersLoading] = useState(true)
  const [usersError, setUsersError] = useState<string | null>(null)

  const [orgs, setOrgs] = useState<Organization[]>([])
  const [orgsLoading, setOrgsLoading] = useState(true)
  const [orgsError, setOrgsError] = useState<string | null>(null)

  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState("viewer")
  const [password, setPassword] = useState("")
  const [orgsCsv, setOrgsCsv] = useState("")
  const [creatingUser, setCreatingUser] = useState(false)
  const [userFormError, setUserFormError] = useState<string | null>(null)
  const [credentials, setCredentials] = useState<{ user: AppUser; password: string } | null>(null)
  const [passwordCopied, setPasswordCopied] = useState(false)
  const [inviteOpen, setInviteOpen] = useState(false)

  const [orgName, setOrgName] = useState("")
  const [orgOwner, setOrgOwner] = useState("")
  const [creatingOrg, setCreatingOrg] = useState(false)
  const [orgFormError, setOrgFormError] = useState<string | null>(null)

  const [memberFor, setMemberFor] = useState<string | null>(null)
  const [memberUser, setMemberUser] = useState("")
  const [memberRole, setMemberRole] = useState("viewer")
  const [memberBusy, setMemberBusy] = useState(false)
  const [memberError, setMemberError] = useState<string | null>(null)
  const [confirmingMember, setConfirmingMember] = useState(false)

  const fetchUsers = async () => {
    setUsersLoading(true)
    try {
      const data = await api.getUsers()
      setUsers(data)
      setUsersError(null)
    } catch (e) {
      setUsersError(e instanceof Error ? e.message : String(e))
    } finally {
      setUsersLoading(false)
    }
  }

  const fetchOrgs = async () => {
    setOrgsLoading(true)
    try {
      const data = await api.getOrgs()
      setOrgs(data)
      setOrgsError(null)
    } catch (e) {
      setOrgsError(e instanceof Error ? e.message : String(e))
    } finally {
      setOrgsLoading(false)
    }
  }

  // Os dois painéis carregam sozinhos, para a falha de um não esconder o outro.
  useEffect(() => {
    void (async () => {
      await fetchUsers()
      await fetchOrgs()
    })()
  }, [])

  const handleCreateUser = async () => {
    if (!email.trim()) return
    setCreatingUser(true)
    setUserFormError(null)
    setCredentials(null)
    setPasswordCopied(false)
    try {
      const result = await api.createUser({
        email: email.trim(),
        name: name.trim(),
        role,
        password,
        orgs: orgsCsv
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      })
      setCredentials(result)
      setEmail("")
      setName("")
      setPassword("")
      setOrgsCsv("")
      setInviteOpen(false)
      await fetchUsers()
      toast("Pessoa convidada.")
    } catch (e) {
      setUserFormError(e instanceof Error ? e.message : String(e))
      toast("Não foi possível convidar a pessoa.", "err")
    } finally {
      setCreatingUser(false)
    }
  }

  const handleCopyPassword = async () => {
    if (!credentials?.password) return
    try {
      await navigator.clipboard.writeText(credentials.password)
      setPasswordCopied(true)
      setTimeout(() => setPasswordCopied(false), 2000)
    } catch {
      setPasswordCopied(false)
    }
  }

  const handleCreateOrg = async () => {
    if (!orgName.trim() || !orgOwner.trim()) return
    setCreatingOrg(true)
    setOrgFormError(null)
    try {
      await api.createOrg({ name: orgName.trim(), owner: orgOwner.trim() })
      setOrgName("")
      setOrgOwner("")
      await fetchOrgs()
      toast("Organização criada.")
    } catch (e) {
      setOrgFormError(e instanceof Error ? e.message : String(e))
      toast("Não foi possível criar a organização.", "err")
    } finally {
      setCreatingOrg(false)
    }
  }

  const handleAddMember = async (orgId: string) => {
    if (!memberUser.trim()) return
    setMemberBusy(true)
    setMemberError(null)
    try {
      const updated = await api.addOrgMember(orgId, { user_id: memberUser.trim(), role: memberRole })
      setOrgs((current) => current.map((org) => (org.id === updated.id ? updated : org)))
      setMemberUser("")
      setMemberFor(null)
      setConfirmingMember(false)
      toast("Membro adicionado.")
    } catch (e) {
      setMemberError(e instanceof Error ? e.message : String(e))
      toast("Não foi possível adicionar o membro.", "err")
    } finally {
      setMemberBusy(false)
    }
  }

  const memberOrg = orgs.find((org) => org.id === memberFor) ?? null

  return (
    <div className="view-grid">
      <Topbar
        title="Equipe"
        description="Quem pode entrar no sistema, com qual papel, e a que organização cada pessoa pertence."
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              void fetchUsers()
              void fetchOrgs()
            }}
            loading={usersLoading || orgsLoading}
          >
            <RefreshCw className="ic ic-sm" aria-hidden="true" /> Atualizar
          </Button>
        }
      />

      {/* Ids de usuário disponíveis, para não errar ao digitar dono ou membro. */}
      <datalist id="equipe-user-ids">
        {users.map((user) => (
          <option key={user.id} value={user.id}>
            {user.email}
          </option>
        ))}
      </datalist>

      <section className="card" aria-labelledby="membros-organizacao">
        <h2 id="membros-organizacao" className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
          Membros da organização
        </h2>

        {usersError && (
          <div className="stack-sm">
            <p className="error-text" role="alert">
              <AlertTriangle className="ic ic-sm" aria-hidden="true" />
              Não foi possível carregar os membros: {usersError}
            </p>
            <div>
              <Button variant="outline" size="sm" onClick={() => void fetchUsers()}>
                <RefreshCw className="ic ic-sm" aria-hidden="true" /> Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {!usersError && usersLoading && (
          <div className="stack-sm">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-[44px] w-full" />
            ))}
          </div>
        )}

        {!usersError && !usersLoading && users.length === 0 && (
          <EmptyState
            icon={<Users className="ic ic-lg" aria-hidden="true" />}
            title="Nenhum membro ainda"
            description="Convide a primeira pessoa para a organização. Ela entra com o e-mail e a senha que você definir."
            action={{ label: "Convidar pessoa", onClick: () => setInviteOpen(true) }}
          />
        )}

        {!usersError && !usersLoading && users.length > 0 && (
          <>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-13)", minWidth: "520px" }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--text-3)" }}>
                    <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                      Nome
                    </th>
                    <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                      E-mail
                    </th>
                    <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                      Papel
                    </th>
                    <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }} />
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }}>
                        <strong>
                          {user.name || user.email}
                          {!user.enabled && (
                            <span className="hint" style={{ marginLeft: "8px" }}>
                              Desativado
                            </span>
                          )}
                        </strong>
                      </td>
                      <td
                        className="mono"
                        style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }}
                      >
                        {user.email}
                        {user.sso_subject && (
                          <span className="hint" style={{ marginLeft: "8px" }}>
                            via SSO
                          </span>
                        )}
                      </td>
                      <td style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }}>
                        <Badge variant={roleVariant(user.role)} title={ROLE_HELP[user.role]}>
                          {ROLE_LABELS[user.role] ?? user.role}
                        </Badge>
                      </td>
                      <td
                        style={{
                          padding: "10px 12px",
                          borderBottom: "1px solid var(--glass-border)",
                          textAlign: "right",
                        }}
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Gerenciar ${user.name || user.email}`}
                          onClick={() => {
                            setMemberUser(user.id)
                            setMemberRole(user.role && ROLE_ORDER.includes(user.role) ? user.role : "viewer")
                            setMemberError(null)
                            setInviteOpen(false)
                          }}
                        >
                          <UserCog className="ic ic-sm" aria-hidden="true" /> Gerenciar
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="od-row" style={{ ["--od-gap" as string]: "12px", marginTop: "var(--sp-4)" }}>
              <Button variant="primary" size="sm" onClick={() => setInviteOpen((open) => !open)}>
                <UserPlus className="ic ic-sm" aria-hidden="true" /> Convidar pessoa
              </Button>
            </div>
          </>
        )}

        {inviteOpen && (
          <div className="stack-sm" style={{ marginTop: "var(--sp-4)" }}>
            <p className="section-title" style={{ fontSize: "var(--fs-14)", fontWeight: 600 }}>
              Convidar pessoa
            </p>

            <div className="od-grid" style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px" }}>
              <Input
                label="E-mail"
                placeholder="ex.: ana@empresa.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                hint="É com ele que a pessoa entra no sistema."
              />
              <Input
                label="Nome"
                placeholder="ex.: Ana Souza"
                value={name}
                onChange={(event) => setName(event.target.value)}
                hint="Opcional, só para identificar a pessoa na tela."
              />
              <Select
                label="Papel"
                value={role}
                onChange={setRole}
                options={ROLE_ORDER.map((value) => ({ value, label: ROLE_LABELS[value] }))}
              />
              <Input
                label="Senha (opcional)"
                type="password"
                placeholder="deixe em branco para entrar só por SSO"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                hint={ROLE_HELP[role]}
              />
            </div>

            <Input
              label="Organizações (opcional)"
              placeholder="ex.: default, marketing"
              value={orgsCsv}
              onChange={(event) => setOrgsCsv(event.target.value)}
              hint="Separe por vírgula. Em branco, a pessoa não entra em nenhuma organização ainda."
            />

            {userFormError && (
              <p className="error-text" role="alert">
                <AlertTriangle className="ic ic-sm" aria-hidden="true" />
                Não foi possível convidar: {userFormError}
              </p>
            )}

            <div className="od-cluster" style={{ ["--od-gap" as string]: "8px" }}>
              <Button variant="primary" size="sm" onClick={handleCreateUser} loading={creatingUser} disabled={!email.trim()}>
                <UserPlus className="ic ic-sm" aria-hidden="true" /> Convidar
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setInviteOpen(false)}>
                Cancelar
              </Button>
            </div>
          </div>
        )}

        {credentials &&
          (credentials.password ? (
            <div className="card" style={{ marginTop: "var(--sp-4)", borderColor: "var(--warning)" }}>
              <p className="od-row" style={{ ["--od-gap" as string]: "6px", fontWeight: 600 }}>
                <KeyRound className="ic ic-sm" aria-hidden="true" /> Senha de {credentials.user.email}
              </p>
              <div className="od-cluster" style={{ ["--od-gap" as string]: "8px", marginTop: "var(--sp-2)" }}>
                <code className="mono" style={{ overflowWrap: "anywhere" }}>
                  {credentials.password}
                </code>
                <Button variant="outline" size="sm" onClick={handleCopyPassword}>
                  {passwordCopied ? (
                    <Check className="ic ic-sm" aria-hidden="true" />
                  ) : (
                    <Copy className="ic ic-sm" aria-hidden="true" />
                  )}
                  {passwordCopied ? "copiado" : "copiar"}
                </Button>
              </div>
              <p className="hint od-row" style={{ ["--od-gap" as string]: "6px", marginTop: "var(--sp-2)" }}>
                <ShieldAlert className="ic ic-sm" aria-hidden="true" />
                <span>
                  Guarde agora: esta senha aparece uma única vez e não pode ser recuperada depois. Se perder, será
                  preciso criar outra.
                </span>
              </p>
              <p className="hint" style={{ marginTop: "var(--sp-2)" }}>
                Id do usuário: <span className="mono">{credentials.user.id}</span>
              </p>
            </div>
          ) : (
            <div className="card" style={{ marginTop: "var(--sp-4)" }}>
              <p className="od-row" style={{ ["--od-gap" as string]: "6px", fontWeight: 600 }}>
                <KeyRound className="ic ic-sm" aria-hidden="true" /> {credentials.user.email} foi criado sem senha
              </p>
              <p className="hint" style={{ marginTop: "var(--sp-2)" }}>
                Sem senha local: a pessoa entra só pelo login da empresa (SSO). Não há senha para guardar.
              </p>
              <p className="hint" style={{ marginTop: "var(--sp-2)" }}>
                Id do usuário: <span className="mono">{credentials.user.id}</span>
              </p>
            </div>
          ))}
      </section>

      <section className="card" aria-labelledby="organizacoes">
        <h2 id="organizacoes" className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
          Organizações
        </h2>
        <p className="card-sub" style={{ marginBottom: "var(--sp-3)" }}>
          Uma organização é a fronteira dos dados: cada uma tem os próprios clones, versões, agendamentos e índice de
          busca, e nada de uma aparece na outra.
        </p>

        {orgsError && (
          <div className="stack-sm">
            <p className="error-text" role="alert">
              <AlertTriangle className="ic ic-sm" aria-hidden="true" />
              Não foi possível carregar as organizações: {orgsError}
            </p>
            <div>
              <Button variant="outline" size="sm" onClick={() => void fetchOrgs()}>
                <RefreshCw className="ic ic-sm" aria-hidden="true" /> Tentar de novo
              </Button>
            </div>
          </div>
        )}

        {!orgsError && orgsLoading && (
          <div className="stack-sm">
            {[0, 1].map((index) => (
              <Skeleton key={index} className="h-[44px] w-full" />
            ))}
          </div>
        )}

        {!orgsError && !orgsLoading && orgs.length === 0 && (
          <EmptyState
            icon={<Building2 className="ic ic-lg" aria-hidden="true" />}
            title="Nenhuma organização cadastrada"
            description="Crie a primeira no formulário abaixo, indicando o id de um usuário como dono."
          />
        )}

        {!orgsError && !orgsLoading && orgs.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-13)", minWidth: "520px" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--text-3)" }}>
                  <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                    Nome
                  </th>
                  <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                    Dono
                  </th>
                  <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                    Membros
                  </th>
                  <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)", fontWeight: 600 }}>
                    Dados
                  </th>
                  <th style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }} />
                </tr>
              </thead>
              <tbody>
                {orgs.map((org) => (
                  <tr key={org.id}>
                    <td style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }}>
                      <strong>{org.name}</strong>
                      <span className="hint mono" style={{ display: "block" }}>
                        {org.id}
                      </span>
                    </td>
                    <td
                      className="mono"
                      style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }}
                    >
                      {org.owner || "—"}
                    </td>
                    <td
                      style={{
                        padding: "10px 12px",
                        borderBottom: "1px solid var(--glass-border)",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {Object.keys(org.members).length}
                    </td>
                    <td style={{ padding: "10px 12px", borderBottom: "1px solid var(--glass-border)" }}>
                      <Badge variant={org.has_data ? "info" : "neutral"}>
                        {org.has_data ? "Com dados" : "Sem dados"}
                      </Badge>
                    </td>
                    <td
                      style={{
                        padding: "10px 12px",
                        borderBottom: "1px solid var(--glass-border)",
                        textAlign: "right",
                      }}
                    >
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setMemberFor(memberFor === org.id ? null : org.id)
                          setMemberUser("")
                          setMemberError(null)
                        }}
                      >
                        <UsersRound className="ic ic-sm" aria-hidden="true" /> Gerenciar
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {memberOrg && (
          <div className="card" style={{ marginTop: "var(--sp-4)" }}>
            <p style={{ fontWeight: 600 }}>
              Adicionar membro em <span className="mono">{memberOrg.id}</span>
            </p>

            {Object.keys(memberOrg.members).length > 0 && (
              <div className="od-cluster" style={{ ["--od-gap" as string]: "6px", marginTop: "var(--sp-2)" }}>
                <span className="hint">Já fazem parte:</span>
                {Object.entries(memberOrg.members).map(([id, memberRole]) => (
                  <span key={id} className="chip" title={ROLE_LABELS[memberRole] ?? memberRole}>
                    <span className="mono">{id}</span>
                  </span>
                ))}
              </div>
            )}

            <div className="od-grid" style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px", marginTop: "var(--sp-3)" }}>
              <Input
                label="Id do usuário"
                placeholder="ex.: 3f9a1c22b7d4e001"
                list="equipe-user-ids"
                value={memberUser}
                onChange={(event) => setMemberUser(event.target.value)}
                hint={
                  memberUser.trim()
                    ? `Quem entra: ${users.find((user) => user.id === memberUser.trim())?.email ?? "id ainda fora da lista de usuários"}.`
                    : "O id aparece na tabela de membros acima."
                }
              />
              <Select
                label="Papel"
                value={memberRole}
                onChange={setMemberRole}
                options={ROLE_ORDER.map((value) => ({ value, label: ROLE_LABELS[value] }))}
              />
            </div>

            {memberError && (
              <p className="error-text" role="alert">
                <AlertTriangle className="ic ic-sm" aria-hidden="true" />
                Não foi possível adicionar o membro: {memberError}
              </p>
            )}

            <div className="od-cluster" style={{ ["--od-gap" as string]: "8px", marginTop: "var(--sp-2)" }}>
              <Button
                variant="primary"
                size="sm"
                loading={memberBusy}
                disabled={!memberUser.trim()}
                onClick={() => setConfirmingMember(true)}
              >
                <UsersRound className="ic ic-sm" aria-hidden="true" /> Adicionar
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setMemberFor(null)
                  setMemberError(null)
                }}
              >
                Cancelar
              </Button>
            </div>
          </div>
        )}

        <div className="stack-sm" style={{ marginTop: "var(--sp-4)" }}>
          <p style={{ fontWeight: 600, display: "flex", alignItems: "center", gap: "8px" }}>
            <Building2 className="ic ic-sm" aria-hidden="true" /> Nova organização
          </p>

          <div className="od-grid" style={{ ["--od-cols" as string]: 2, ["--od-gap" as string]: "16px" }}>
            <Input
              label="Nome"
              placeholder="ex.: Marketing"
              value={orgName}
              onChange={(event) => setOrgName(event.target.value)}
              hint="O id da organização é gerado a partir deste nome."
            />
            <Input
              label="Id do dono"
              placeholder="ex.: 3f9a1c22b7d4e001"
              list="equipe-user-ids"
              value={orgOwner}
              onChange={(event) => setOrgOwner(event.target.value)}
              hint="O dono entra automaticamente como administrador da organização."
            />
          </div>

          {orgFormError && (
            <p className="error-text" role="alert">
              <AlertTriangle className="ic ic-sm" aria-hidden="true" />
              Não foi possível criar a organização: {orgFormError}
            </p>
          )}

          <p className="hint od-row" style={{ ["--od-gap" as string]: "6px" }}>
            <AlertTriangle className="ic ic-sm" aria-hidden="true" />
            <span>O id do dono precisa ser o de um usuário que já existe na tabela acima.</span>
          </p>

          <div>
            <Button
              variant="primary"
              size="sm"
              onClick={handleCreateOrg}
              loading={creatingOrg}
              disabled={!orgName.trim() || !orgOwner.trim()}
            >
              <Building2 className="ic ic-sm" aria-hidden="true" /> Criar organização
            </Button>
          </div>
        </div>
      </section>

      <Modal
        open={confirmingMember}
        title="Adicionar este membro?"
        body={
          memberOrg
            ? `${memberUser.trim() || "O usuário"} entra em ${memberOrg.name} como ${ROLE_LABELS[memberRole] ?? memberRole}.`
            : ""
        }
        confirmLabel="Adicionar"
        onConfirm={() => {
          if (memberOrg) void handleAddMember(memberOrg.id)
        }}
        onClose={() => {
          if (!memberBusy) setConfirmingMember(false)
        }}
      />
    </div>
  )
}
