"use client"
import { useEffect, useState } from "react"
import { api, AppUser, Organization } from "@/lib/api"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input, Select } from "@/components/ui/input"
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

export default function EquipePage() {
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

  const [orgName, setOrgName] = useState("")
  const [orgOwner, setOrgOwner] = useState("")
  const [creatingOrg, setCreatingOrg] = useState(false)
  const [orgFormError, setOrgFormError] = useState<string | null>(null)

  const [memberFor, setMemberFor] = useState<string | null>(null)
  const [memberUser, setMemberUser] = useState("")
  const [memberRole, setMemberRole] = useState("viewer")
  const [memberBusy, setMemberBusy] = useState(false)
  const [memberError, setMemberError] = useState<string | null>(null)

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
      await fetchUsers()
    } catch (e) {
      setUserFormError(e instanceof Error ? e.message : String(e))
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
    } catch (e) {
      setOrgFormError(e instanceof Error ? e.message : String(e))
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
    } catch (e) {
      setMemberError(e instanceof Error ? e.message : String(e))
    } finally {
      setMemberBusy(false)
    }
  }

  const memberOrg = orgs.find((org) => org.id === memberFor) ?? null

  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Equipe"
        description="Quem pode entrar no sistema, com qual papel, e a que organização cada pessoa pertence."
        action={
          <Button
            onClick={() => {
              fetchUsers()
              fetchOrgs()
            }}
            loading={usersLoading || orgsLoading}
            size="sm"
            variant="outline"
          >
            <RefreshCw className="h-4 w-4" /> Atualizar
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" /> Usuários
          </CardTitle>
          <CardDescription>
            Cada pessoa tem um e-mail, um papel e uma ou mais organizações. A senha local só é usada quando não há
            login da empresa (SSO).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {usersError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível carregar os usuários.</p>
              <p className="mt-1">{usersError}</p>
              <p className="mt-1 text-muted-foreground">
                Confira se o sistema está no ar e clique em <strong className="text-foreground/80">Atualizar</strong>.
              </p>
            </div>
          )}

          {!usersError && users.length === 0 && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <Users className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] font-medium">
                {usersLoading ? "Carregando os usuários…" : "Nenhum usuário cadastrado"}
              </p>
              <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                {usersLoading
                  ? "Um instante."
                  : "Crie o primeiro usuário no formulário abaixo. Ele já pode entrar com o e-mail e a senha que você definir."}
              </p>
            </div>
          )}

          {users.length > 0 && (
            <div className="overflow-x-auto rounded-[12px] border">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Id</th>
                    <th className="px-4 py-3 font-medium">E-mail</th>
                    <th className="px-4 py-3 font-medium">Nome</th>
                    <th className="px-4 py-3 font-medium">Papel</th>
                    <th className="px-4 py-3 font-medium">Organizações</th>
                    <th className="px-4 py-3 font-medium">Situação</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {users.map((user) => (
                    <tr key={user.id} className="hover:bg-accent/50">
                      <td className="px-4 py-3 text-[12px] font-mono text-muted-foreground">{user.id}</td>
                      <td className="px-4 py-3 text-[12.5px] break-all">
                        {user.email}
                        {user.sso_subject && (
                          <span className="ml-2 text-[11px] text-muted-foreground">via SSO</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[12.5px]">{user.name || "—"}</td>
                      <td className="px-4 py-3 text-[12.5px] whitespace-nowrap" title={ROLE_HELP[user.role]}>
                        {ROLE_LABELS[user.role] ?? user.role}
                      </td>
                      <td className="px-4 py-3 text-[12px]">
                        {user.orgs.length === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {user.orgs.map((org) => (
                              <span key={org} className="rounded-full bg-secondary px-2 py-0.5 font-mono">
                                {org}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap ${
                            user.enabled
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
                              : "bg-zinc-500/10 text-zinc-500 ring-zinc-500/20"
                          }`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${user.enabled ? "bg-emerald-500" : "bg-zinc-400"}`}
                          />
                          {user.enabled ? "Ativo" : "Desativado"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="border-t pt-4 space-y-3">
            <p className="text-[13px] font-semibold flex items-center gap-2">
              <UserPlus className="h-4 w-4" /> Novo usuário
            </p>

            <div className="grid sm:grid-cols-2 gap-3">
              <Input
                label="E-mail"
                placeholder="ex.: ana@empresa.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                hint="É com ele que a pessoa entra no sistema."
              />
              <Input
                label="Nome"
                placeholder="ex.: Ana Souza"
                value={name}
                onChange={(e) => setName(e.target.value)}
                hint="Opcional, só para identificar a pessoa na tela."
              />
              <Select label="Papel" value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLE_ORDER.map((value) => (
                  <option key={value} value={value}>
                    {ROLE_LABELS[value]}
                  </option>
                ))}
              </Select>
              <Input
                label="Senha (opcional)"
                type="password"
                placeholder="deixe em branco para entrar só por SSO"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                hint={ROLE_HELP[role]}
              />
            </div>

            <Input
              label="Organizações (opcional)"
              placeholder="ex.: default, marketing"
              value={orgsCsv}
              onChange={(e) => setOrgsCsv(e.target.value)}
              hint="Separe por vírgula. Em branco, a pessoa não entra em nenhuma organização ainda."
            />

            {userFormError && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">Não foi possível criar o usuário.</p>
                <p className="mt-1">{userFormError}</p>
              </div>
            )}

            {credentials &&
              (credentials.password ? (
                <div className="rounded-[12px] bg-amber-500/10 border border-amber-500/20 p-4 text-[13px]">
                  <p className="flex items-center gap-1.5 font-medium text-amber-700 dark:text-amber-400">
                    <KeyRound className="h-4 w-4" /> Senha de {credentials.user.email}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <code className="rounded-[8px] border bg-background px-3 py-1.5 font-mono text-[15px] break-all">
                      {credentials.password}
                    </code>
                    <Button size="sm" variant="outline" onClick={handleCopyPassword}>
                      {passwordCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                      {passwordCopied ? "copiado" : "copiar"}
                    </Button>
                  </div>
                  <p className="mt-2 flex items-start gap-1.5 text-amber-700 dark:text-amber-400">
                    <ShieldAlert className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    Guarde agora: esta senha aparece uma única vez e não pode ser recuperada depois. Se perder, será
                    preciso criar outra.
                  </p>
                  <p className="mt-2 text-muted-foreground">
                    Id do usuário: <span className="font-mono text-foreground/80">{credentials.user.id}</span>
                  </p>
                </div>
              ) : (
                <div className="rounded-[12px] border bg-secondary/40 p-4 text-[13px]">
                  <p className="flex items-center gap-1.5 font-medium">
                    <KeyRound className="h-4 w-4" /> {credentials.user.email} foi criado sem senha
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    Sem senha local: a pessoa entra só pelo login da empresa (SSO). Não há senha para guardar.
                  </p>
                  <p className="mt-2 text-muted-foreground">
                    Id do usuário: <span className="font-mono text-foreground/80">{credentials.user.id}</span>
                  </p>
                </div>
              ))}

            <Button onClick={handleCreateUser} loading={creatingUser} disabled={!email.trim()}>
              <UserPlus className="h-4 w-4" /> Criar usuário
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4" /> Organizações
          </CardTitle>
          <CardDescription>
            Uma organização é a fronteira dos dados: cada uma tem os próprios clones, versões, agendamentos e índice de
            busca, e nada de uma aparece na outra.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {orgsError && (
            <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
              <p className="font-medium">Não foi possível carregar as organizações.</p>
              <p className="mt-1">{orgsError}</p>
              <p className="mt-1 text-muted-foreground">
                Confira se o sistema está no ar e clique em <strong className="text-foreground/80">Atualizar</strong>.
              </p>
            </div>
          )}

          {!orgsError && orgs.length === 0 && (
            <div className="rounded-[12px] border border-dashed p-10 text-center">
              <Building2 className="h-8 w-8 mx-auto text-muted-foreground/40 mb-2" />
              <p className="text-[13px] font-medium">
                {orgsLoading ? "Carregando as organizações…" : "Nenhuma organização cadastrada"}
              </p>
              <p className="text-[12.5px] text-muted-foreground mt-1 max-w-md mx-auto">
                {orgsLoading
                  ? "Um instante."
                  : "Crie a primeira no formulário abaixo, indicando o id de um usuário como dono."}
              </p>
            </div>
          )}

          {orgs.length > 0 && (
            <div className="overflow-x-auto rounded-[12px] border">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b bg-muted/30 text-[11px] uppercase tracking-widest text-muted-foreground">
                    <th className="px-4 py-3 font-medium">Id</th>
                    <th className="px-4 py-3 font-medium">Nome</th>
                    <th className="px-4 py-3 font-medium">Dono</th>
                    <th className="px-4 py-3 font-medium">Membros</th>
                    <th className="px-4 py-3 font-medium">Dados</th>
                    <th className="px-4 py-3 font-medium" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {orgs.map((org) => (
                    <tr key={org.id} className="hover:bg-accent/50">
                      <td className="px-4 py-3 text-[12px] font-mono text-muted-foreground">{org.id}</td>
                      <td className="px-4 py-3 text-[12.5px] font-medium">{org.name}</td>
                      <td className="px-4 py-3 text-[12px] font-mono text-muted-foreground">{org.owner || "—"}</td>
                      <td className="px-4 py-3 text-[12.5px] tabular-nums">{Object.keys(org.members).length}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap ${
                            org.has_data
                              ? "bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/20"
                              : "bg-zinc-500/10 text-zinc-500 ring-zinc-500/20"
                          }`}
                        >
                          {org.has_data ? "Com dados" : "Sem dados"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setMemberFor(memberFor === org.id ? null : org.id)
                            setMemberUser("")
                            setMemberError(null)
                          }}
                        >
                          <UsersRound className="h-3.5 w-3.5" /> Adicionar membro
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {memberOrg && (
            <div className="rounded-[12px] border bg-muted/20 p-4 space-y-3">
              <p className="text-[13px] font-semibold">
                Adicionar membro em <span className="font-mono">{memberOrg.id}</span>
              </p>

              {Object.keys(memberOrg.members).length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[12px] text-muted-foreground">Já fazem parte:</span>
                  {Object.entries(memberOrg.members).map(([id, memberRole]) => (
                    <span
                      key={id}
                      className="rounded-full bg-secondary px-2 py-0.5 text-[11.5px] font-mono"
                      title={ROLE_LABELS[memberRole] ?? memberRole}
                    >
                      {id}
                    </span>
                  ))}
                </div>
              )}

              <div className="grid sm:grid-cols-2 gap-3">
                <Input
                  label="Id do usuário"
                  placeholder="ex.: 3f9a1c22b7d4e001"
                  list="equipe-user-ids"
                  value={memberUser}
                  onChange={(e) => setMemberUser(e.target.value)}
                  hint="O id aparece na tabela de usuários acima."
                />
                <Select label="Papel" value={memberRole} onChange={(e) => setMemberRole(e.target.value)}>
                  {ROLE_ORDER.map((value) => (
                    <option key={value} value={value}>
                      {ROLE_LABELS[value]}
                    </option>
                  ))}
                </Select>
              </div>

              {memberError && (
                <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                  <p className="font-medium">Não foi possível adicionar o membro.</p>
                  <p className="mt-1">{memberError}</p>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  loading={memberBusy}
                  disabled={!memberUser.trim()}
                  onClick={() => handleAddMember(memberOrg.id)}
                >
                  <UsersRound className="h-3.5 w-3.5" /> Adicionar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
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

          <div className="border-t pt-4 space-y-3">
            <p className="text-[13px] font-semibold flex items-center gap-2">
              <Building2 className="h-4 w-4" /> Nova organização
            </p>

            <div className="grid sm:grid-cols-2 gap-3">
              <Input
                label="Nome"
                placeholder="ex.: Marketing"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                hint="O id da organização é gerado a partir deste nome."
              />
              <Input
                label="Id do dono"
                placeholder="ex.: 3f9a1c22b7d4e001"
                list="equipe-user-ids"
                value={orgOwner}
                onChange={(e) => setOrgOwner(e.target.value)}
                hint="O dono entra automaticamente como administrador da organização."
              />
            </div>

            {orgFormError && (
              <div className="rounded-[12px] bg-destructive/10 border border-destructive/20 p-3 text-[13px] text-destructive">
                <p className="font-medium">Não foi possível criar a organização.</p>
                <p className="mt-1">{orgFormError}</p>
              </div>
            )}

            <div className="flex items-start gap-1.5 text-[12px] text-muted-foreground">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>O id do dono precisa ser o de um usuário que já existe na tabela acima.</span>
            </div>

            <Button
              onClick={handleCreateOrg}
              loading={creatingOrg}
              disabled={!orgName.trim() || !orgOwner.trim()}
            >
              <Building2 className="h-4 w-4" /> Criar organização
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
