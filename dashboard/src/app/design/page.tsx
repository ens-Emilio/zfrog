"use client"

import { useState, type CSSProperties } from "react"
import { Topbar } from "@/components/Navbar"
import { Button } from "@/components/ui/button"
import { Input, Switch, Textarea } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge, StatusBadge } from "@/components/ui/badge"
import { Chip, ModeCard, Progress, Stepper } from "@/components/ui/ds"
import { ICONS, Icon, type IconName } from "@/lib/icons"
import { MODES, RECOMMENDED_MODES, STATUS_LABELS, STATUS_SHORT } from "@/lib/labels"
import { useMotion, useTheme } from "@/lib/prefs"
import type { JobMode, JobStatus } from "@/lib/api"
import styles from "./design.module.css"

/**
 * A documentação viva do Pond Glass: os mesmos tokens, classes e componentes que
 * as telas do painel usam, montados com os componentes reais do dashboard — não
 * com HTML estático copiado do protótipo. Se um valor mudar em ds-tokens.css,
 * esta página muda junto.
 */

const SECTIONS = [
  { id: "cores", label: "Cores" },
  { id: "tipografia", label: "Tipografia" },
  { id: "espaco", label: "Espaço" },
  { id: "icones", label: "Ícones" },
  { id: "componentes", label: "Componentes" },
  { id: "movimento", label: "Movimento" },
  { id: "acessibilidade", label: "Acessibilidade" },
  { id: "atalhos", label: "Atalhos" },
]

/** A escala Frog: a única família de ação do sistema. */
const FROG_SCALE = [
  { token: "frog-50", hex: "#EDFBF3", note: "highlight claro" },
  { token: "frog-100", hex: "#D3F7E1", note: "badges suaves" },
  { token: "frog-200", hex: "#A8EFC5", note: "hover claro" },
  { token: "frog-300", hex: "#6FE3A4", note: "ícones dark" },
  { token: "frog-400", hex: "#3BD487", note: "acento dark" },
  { token: "frog-500", hex: "#17B877", note: "acento light" },
  { token: "frog-600", hex: "#0E9663", note: "links claro (AA)" },
  { token: "frog-700", hex: "#0C7751", note: "hover primário" },
  { token: "frog-800", hex: "#0B5E41", note: "bordas fortes" },
  { token: "frog-900", hex: "#094D36", note: "texto s/ frog claro" },
]

/** Pond apoia: informação, gradientes e etiquetas. Nunca botão primário. */
const POND_SCALE = [
  { token: "pond-300", hex: "#7FE7DC", note: "detalhes dark" },
  { token: "pond-400", hex: "#38D6C4", note: "info dark" },
  { token: "pond-500", hex: "#14B8A6", note: "apoio claro" },
]

/** Fundo, vidro, texto e as quatro semânticas — lidos dos tokens, não copiados. */
const SURFACES: { label: string; value: string; style: CSSProperties }[] = [
  {
    label: "Fundo",
    value: "dark #0B120E / #111A15 · light #F4F8F5 / #FFFFFF",
    style: { background: "linear-gradient(150deg, var(--bg-2), var(--bg-0))" },
  },
  { label: "Vidro", value: "--glass", style: { background: "var(--glass)" } },
  { label: "Texto principal", value: "dark #E9F2EC · light #0C1B14", style: { background: "var(--text-1)" } },
  { label: "Texto secundário", value: "var(--text-2)", style: { background: "var(--text-2)" } },
  { label: "Texto de apoio", value: "var(--text-3)", style: { background: "var(--text-3)" } },
  { label: "Acento", value: "var(--accent) — frog", style: { background: "var(--accent)" } },
  { label: "Sucesso", value: "frog-500 · reusa o acento", style: { background: "var(--success)" } },
  { label: "Atenção", value: "#E8B33C âmbar", style: { background: "var(--warning)" } },
  { label: "Erro", value: "#E5484D — o único vermelho", style: { background: "var(--danger)" } },
  { label: "Informação", value: "pond-400", style: { background: "var(--info)" } },
]

const TYPE_ROWS: {
  tag: string
  size: string
  text: string
  display?: boolean
  mono?: boolean
  weight?: number
  muted?: boolean
}[] = [
  { tag: "40 / display", size: "var(--fs-40)", text: "zfrog", display: true, weight: 700 },
  { tag: "32 / destaque", size: "var(--fs-32)", text: "Execuções", display: true, weight: 700 },
  { tag: "24 / título", size: "var(--fs-24)", text: "Nova extração", display: true, weight: 600 },
  { tag: "20 / seção", size: "var(--fs-20)", text: "Estatísticas", display: true, weight: 600 },
  { tag: "18 / subtítulo", size: "var(--fs-18)", text: "Por região", display: true, weight: 600 },
  { tag: "16 / corpo grande", size: "var(--fs-16)", text: "Baixe um site inteiro ou apenas os dados que importam." },
  {
    tag: "14 / corpo",
    size: "var(--fs-14)",
    text: "Respeitamos o robots.txt por padrão e você pode cancelar a qualquer momento.",
  },
  { tag: "13 / apoio forte", size: "var(--fs-13)", text: "Uma máquina parada de responder não recebe novas cópias." },
  { tag: "12 / apoio", size: "var(--fs-12)", text: "Atualizado automaticamente", muted: true },
  { tag: "11 / micro", size: "var(--fs-11)", text: "Último sinal de vida há 2 minutos", muted: true },
  { tag: "mono", size: "var(--fs-13)", text: "./zfrog probe https://exemplo.com", mono: true },
]

const SPACES = [
  { token: "--sp-1", px: 4 },
  { token: "--sp-2", px: 8 },
  { token: "--sp-3", px: 12 },
  { token: "--sp-4", px: 16 },
  { token: "--sp-5", px: 20 },
  { token: "--sp-6", px: 24 },
  { token: "--sp-8", px: 32 },
  { token: "--sp-10", px: 40 },
  { token: "--sp-12", px: 48 },
]

const RADII = [
  { token: "--r-sm", value: "8px", css: "var(--r-sm)" },
  { token: "--r-control", value: "10px", css: "var(--r-control)" },
  { token: "--r-card", value: "16px", css: "var(--r-card)" },
  { token: "--r-lg", value: "20px", css: "var(--r-lg)" },
  { token: "--r-pill", value: "999px", css: "var(--r-pill)" },
]

const SHADOWS = [
  { token: "--shadow-1", value: "0 1px 2px", css: "var(--shadow-1)", use: "controles soltos" },
  { token: "--shadow-2", value: "0 8px 32px", css: "var(--shadow-2)", use: "camada de vidro padrão" },
  { token: "--shadow-pop", value: "0 24px 70px", css: "var(--shadow-pop)", use: "modais e toasts" },
]

const MOTION_TOKENS = [
  { token: "--t-fast", value: "150ms", use: "feedback de hover e foco" },
  { token: "--t-base", value: "220ms", use: "switches e transições de cor" },
  { token: "--t-slow", value: "300ms", use: "troca de tela, barras e modais" },
  { token: "--ease-out", value: "cubic-bezier(.16,1,.3,1)", use: "entradas e deslocamentos" },
]

const CONSOLE_LINES = [
  { ts: "14:02", lvl: "lvl-info", tag: "INFO", text: "Worker iniciado · concorrência 4" },
  { ts: "14:02", lvl: "lvl-ok", tag: "OK", text: "robots.txt permite o caminho" },
  { ts: "14:03", lvl: "lvl-warn", tag: "WARN", text: "GET /banner@2x.png → 404" },
  { ts: "14:04", lvl: "lvl-err", tag: "ERR", text: "GET /produtos → 403 Forbidden" },
]

const TIMELINE_POINTS = [
  { id: 1, when: "12 de março de 2026 · 09:20", what: "3 páginas mudaram", detail: "Preço e disponibilidade na página de produto." },
  { id: 2, when: "28 de fevereiro de 2026 · 18:04", what: "12 páginas novas", detail: "Seção de perguntas frequentes publicada." },
  { id: 3, when: "05 de fevereiro de 2026 · 11:47", what: "Primeira captura", detail: "Referência inicial do site." },
]

const BAR_ROWS = [
  { name: "wget", pct: 100, value: "412 · 96% ok" },
  { name: "playwright", pct: 63, value: "259 · 91% ok" },
  { name: "scrapy", pct: 34, value: "138 · 88% ok" },
]

const WEEKLY = [82, 88, 91, 86, 94, 96, 90, 93]

const DIFF_ROWS = [
  { sign: "-", kind: "del", text: "<p>Preço: R$ 199,00</p>" },
  { sign: "+", kind: "add", text: "<p>Preço: R$ 249,00</p>" },
  { sign: " ", kind: "same", text: "<p>Frete grátis para todo o Brasil</p>" },
]

const SHORTCUTS = [
  { what: "Abrir comandos rápidos", keys: ["Ctrl", "K"] },
  { what: "Buscar / comandos", keys: ["/"] },
  { what: "Fechar sobreposição", keys: ["Esc"] },
  { what: "Navegar na lista de comandos", keys: ["↑", "↓"] },
]

const A11Y_RULES = [
  "Contraste de texto de corpo ≥ 4,5:1 e de texto grande/ícones ≥ 3:1.",
  "Foco visível em todos os controles e ordem de tabulação coerente.",
  "Status nunca depende só de cor: sempre acompanha rótulo e forma.",
  "Alvos de toque com pelo menos 44px nos controles principais.",
  'Modais com role="dialog", foco preso e fechamento por Esc.',
  'Gráficos com descrição textual via role="img" e rótulos.',
]

const ICON_NAMES = [...Object.keys(ICONS), "i-frog"] as IconName[]

const STATUSES = Object.keys(STATUS_LABELS) as JobStatus[]

/** Uma amostra de cor: o preenchimento real e o valor em texto. */
function Swatch({ fill, title, value }: { fill: CSSProperties; title: string; value: string }) {
  return (
    <div className={styles.swatch}>
      <div className={styles.fill} style={fill} aria-hidden="true" />
      <div className={styles.meta}>
        <strong>{title}</strong>
        <code>{value}</code>
      </div>
    </div>
  )
}

export default function DesignPage() {
  const [theme, toggleTheme] = useTheme()
  const [motion, setMotion] = useMotion()
  const [mode, setMode] = useState<JobMode>(RECOMMENDED_MODES[0])
  const [chip, setChip] = useState<"all" | "ok" | "err">("all")
  const [keepHtml, setKeepHtml] = useState(true)
  const [depth, setDepth] = useState(4)
  const [point, setPoint] = useState(TIMELINE_POINTS[0].id)

  const current = MODES[mode]

  return (
    <div className="view-grid">
      <Topbar
        title="Design system"
        description="Pond Glass — tokens, componentes e padrões do zfrog"
        action={
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label={theme === "dark" ? "Mudar para o tema claro" : "Mudar para o tema escuro"}
          >
            <Icon name={theme === "dark" ? "i-sun" : "i-moon"} />
          </Button>
        }
      />

      <div className={styles.wrap}>
        <div className={styles.section}>
          <h1 style={{ fontSize: "var(--fs-40)" }}>Design system do zfrog</h1>
          <p className={styles.sub}>
            Paleta &quot;Pond Glass&quot;: base minimalista e silenciosa com camadas de vidro sobre dois brilhos
            ambientes (verde-sapo e teal-lagoa). Uma família de acento, uma de apoio, e neutros esverdeados fazendo o
            resto. Estas são as decisões que o painel aplica em todas as rotas do produto.
          </p>
          <nav className={styles.anchors} aria-label="Seções do design system">
            {SECTIONS.map((section) => (
              <a key={section.id} className={styles.anchor} href={`#${section.id}`}>
                {section.label}
              </a>
            ))}
          </nav>
        </div>

        <section className={styles.section} id="cores" aria-labelledby="cores-titulo">
          <h2 id="cores-titulo">Cores — Pond Glass</h2>
          <p className={styles.sub}>
            Regra <strong>60-30-10</strong>: 60% neutros/fundo, 30% superfícies de vidro, 10% frog+pond. Vidro só em
            camada flutuante (navbar, cards, modais, overlays) — o layout base permanece flat. Máximo{" "}
            <strong>2 brilhos ambientes</strong> por tela: frog-500 a 14–18% no topo-esquerda, pond-500 a 10–14% na
            base-direita.
          </p>
          <ul className={styles.ruleList}>
            <li>60% neutros e fundo · 30% vidro · 10% frog e pond.</li>
            <li>Vidro só em camada flutuante; o layout base é flat.</li>
            <li>No máximo dois brilhos ambientes por tela.</li>
          </ul>

          <h3>Frog — acento principal (única cor de ação)</h3>
          <div className={styles.swatches}>
            {FROG_SCALE.map((color) => (
              <Swatch
                key={color.token}
                fill={{ background: `var(--${color.token})` }}
                title={color.token}
                value={`${color.hex} · ${color.note}`}
              />
            ))}
          </div>

          <h3>Pond — apoio (info, gradientes, etiquetas; nunca botão primário)</h3>
          <div className={styles.swatches}>
            {POND_SCALE.map((color) => (
              <Swatch
                key={color.token}
                fill={{ background: `var(--${color.token})` }}
                title={color.token}
                value={`${color.hex} · ${color.note}`}
              />
            ))}
          </div>

          <h3>Neutros esverdeados + semânticas</h3>
          <div className={styles.swatches}>
            {SURFACES.map((surface) => (
              <Swatch key={surface.label} fill={surface.style} title={surface.label} value={surface.value} />
            ))}
          </div>

          <div className={styles.demoRow}>
            {STATUSES.map((status) => (
              <StatusBadge key={status} status={status} />
            ))}
            <Badge variant="warning">4 erros</Badge>
            <Badge variant="danger">Falhou</Badge>
            <Badge variant="neutral">Na fila</Badge>
          </div>
        </section>

        <section className={styles.section} id="tipografia" aria-labelledby="tipografia-titulo">
          <h2 id="tipografia-titulo">Tipografia</h2>
          <p className={styles.sub}>
            <strong>Space Grotesk</strong> nos títulos e números (personalidade técnica), <strong>Inter</strong> no
            corpo (legibilidade) e <strong>JetBrains Mono</strong> para endereços, logs e código.
          </p>
          <div>
            {TYPE_ROWS.map((row) => (
              <div className={styles.typeRow} key={row.tag}>
                <span className={styles.typeTag}>{row.tag}</span>
                <span
                  style={{
                    fontFamily: row.mono ? "var(--font-mono)" : row.display ? "var(--font-display)" : undefined,
                    fontSize: row.size,
                    fontWeight: row.weight,
                    color: row.muted ? "var(--text-3)" : undefined,
                  }}
                >
                  {row.text}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.section} id="espaco" aria-labelledby="espaco-titulo">
          <h2 id="espaco-titulo">Espaçamento, raios e elevação</h2>
          <p className={styles.sub}>
            Ritmo em múltiplos de 4/8. Raios de 10px em controles, 16px em cartões e pílula para chips e badges. A
            elevação nas superfícies de vidro combina desfoque, borda sutil e um realce interno de 1px.
          </p>

          <div className={styles.specGrid}>
            {SPACES.map((space) => (
              <div className="card" key={space.token}>
                <span className="hint">
                  {space.token} · {space.px}px
                </span>
                <div className={styles.spaceBar} style={{ width: space.px, marginTop: "var(--sp-2)" }} />
              </div>
            ))}
          </div>

          <div className={styles.specGrid}>
            {RADII.map((radius) => (
              <div className="card" key={radius.token}>
                <span className="hint" style={{ display: "block", marginBottom: "var(--sp-2)" }}>
                  {radius.token} · {radius.value}
                </span>
                <div className={styles.radiusBox} style={{ borderRadius: radius.css }} />
              </div>
            ))}
          </div>

          <div className={styles.specGrid}>
            {SHADOWS.map((shadow) => (
              <div key={shadow.token} className={styles.shadowBox} style={{ boxShadow: shadow.css }}>
                <strong className="card-title">{shadow.token}</strong>
                <span className="card-sub">{shadow.value}</span>
                <span className="hint">{shadow.use}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={styles.section} id="icones" aria-labelledby="icones-titulo">
          <h2 id="icones-titulo">Ícones</h2>
          <p className={styles.sub}>
            Uma única família (traço de 1,75px, cantos arredondados), sempre em SVG herdando a cor do texto. Nunca
            emojis como ícones funcionais. No dashboard cada símbolo é um componente <span className="mono">lucide-react</span>{" "}
            exposto por <span className="mono">@/lib/icons</span>; o sapo da marca é SVG próprio.
          </p>
          <div className={styles.iconGrid}>
            {ICON_NAMES.map((name) => (
              <span className={styles.iconCell} key={name}>
                <Icon name={name} size="lg" />
                <span>{name}</span>
              </span>
            ))}
          </div>
        </section>

        <section className={styles.section} id="componentes" aria-labelledby="componentes-titulo">
          <h2 id="componentes-titulo">Componentes e estados</h2>
          <p className={styles.sub}>
            Controles com estado padrão, hover, foco e desabilitado. O anel de foco aparece em navegação por teclado e
            nunca é removido.
          </p>

          <div className="card stack-md">
            <h3 className="card-title">Botões</h3>
            <div className={styles.demoRow}>
              <Button variant="primary">Primário</Button>
              <Button variant="secondary">Secundário</Button>
              <Button variant="ghost">Fantasma</Button>
              <Button variant="destructive">Perigo</Button>
              <Button variant="primary" size="sm">
                Pequeno
              </Button>
              <Button variant="primary" size="lg">
                Alvo de 44px
              </Button>
              <Button variant="secondary" loading>
                Carregando
              </Button>
              <Button variant="primary" disabled>
                Desabilitado
              </Button>
              <Button variant="ghost" size="icon" aria-label="Atualizar">
                <Icon name="i-refresh" />
              </Button>
            </div>
          </div>

          <div className="card stack-md">
            <h3 className="card-title">Chips e badges</h3>
            <div className={styles.demoRow}>
              <Chip active={chip === "all"} onClick={() => setChip("all")}>
                Todas
              </Chip>
              <Chip active={chip === "ok"} onClick={() => setChip("ok")}>
                Concluídas
              </Chip>
              <Chip active={chip === "err"} onClick={() => setChip("err")}>
                Com erro
              </Chip>
              <Badge variant="success">
                <span className="dot" aria-hidden="true" />
                Concluído
              </Badge>
              <Badge variant="accent">
                <span className="dot" aria-hidden="true" />
                Baixando
              </Badge>
              <Badge variant="info">
                <span className="dot" aria-hidden="true" />
                Analisando
              </Badge>
            </div>
          </div>

          <div className="card stack-md">
            <h3 className="card-title">Campos</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="Endereço do site"
                className="input-mono"
                placeholder="https://exemplo.com"
                defaultValue="https://docs.python.org"
                hint="Sempre com o começo https://."
              />
              <Input
                label="Com erro"
                defaultValue="exemplo.com"
                error="Inclua o começo do endereço, por exemplo https://."
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Select
                label="Modo de captura"
                value={mode}
                onChange={(next) => setMode(next as JobMode)}
                hint="O modo escolhido para a execução."
                options={RECOMMENDED_MODES.map((key) => ({
                  value: key,
                  label: MODES[key].label,
                  icon: MODES[key].icon,
                }))}
              />
              <Textarea label="Proxies" placeholder="http://usuario:senha@host:porta" hint="Um por linha." />
            </div>
            <div className={styles.demoRow}>
              <Switch
                checked={keepHtml}
                onChange={setKeepHtml}
                label="Guardar também o HTML original"
                hint="Sem isto, só o conteúdo tratado fica salvo."
              />
            </div>
            <div className="field" style={{ maxWidth: 320 }}>
              <label className="label" htmlFor="ds-range">
                Profundidade máxima
              </label>
              <input
                id="ds-range"
                className="range"
                type="range"
                min={1}
                max={16}
                value={depth}
                onChange={(event) => setDepth(Number(event.target.value))}
              />
              <span className="hint">{depth} níveis a partir da página inicial.</span>
            </div>
          </div>

          <div className="card stack-md">
            <h3 className="card-title">Progresso e etapas</h3>
            <Progress value={62} label="Execução em andamento: 62% concluído" />
            <Progress value={100} state="done" label="Execução concluída" />
            <Progress value={38} state="error" label="Execução interrompida por erro" />
            <Stepper
              steps={[STATUS_SHORT.pending, STATUS_SHORT.probing, STATUS_SHORT.running, STATUS_SHORT.completed]}
              current={2}
            />
            <p className="hint">
              Em andamento usa o gradiente de acento, concluído usa o verde de sucesso e o erro fica no vermelho único.
            </p>
          </div>

          <div className="two-col">
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
                Console
              </h3>
              <div className="console" role="log" aria-label="Exemplo de console de execução">
                {CONSOLE_LINES.map((line) => (
                  <div className="line" key={`${line.ts}-${line.tag}`}>
                    <span className="ts">{line.ts}</span>
                    <span className={`lvl ${line.lvl}`}>{line.tag}</span>
                    <span>{line.text}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
                Seletor de modo
              </h3>
              <p className="card-sub" style={{ marginBottom: "var(--sp-3)" }}>
                Tiles quadrados em uma linha para os modos recomendados (o Auto, com o sapo da marca, vem primeiro), com
                os avançados em um menu ao lado. A descrição do modo escolhido aparece logo abaixo.
              </p>
              <div className="mode-grid" style={{ marginBottom: "var(--sp-3)" }}>
                {RECOMMENDED_MODES.map((key) => (
                  <ModeCard
                    key={key}
                    active={mode === key}
                    icon={<Icon name={MODES[key].icon} size="lg" />}
                    label={MODES[key].label}
                    onClick={() => setMode(key)}
                  />
                ))}
              </div>
              <div className="mode-summary">
                <span>
                  <strong>{current.label}</strong> — {current.what}
                </span>
                <span className="mode-out">Você recebe: {current.output}</span>
              </div>
            </div>
          </div>

          <div className="two-col">
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
                Linha do tempo
              </h3>
              <div className="timeline">
                {TIMELINE_POINTS.map((item) => (
                  <div className={`tl-item${point === item.id ? " is-selected" : ""}`} key={item.id}>
                    <button
                      type="button"
                      className="tl-btn"
                      aria-pressed={point === item.id}
                      onClick={() => setPoint(item.id)}
                    >
                      <span className="hint">{item.when}</span>
                      <strong>{item.what}</strong>
                      <span className="card-sub">{item.detail}</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
                Diferença entre versões
              </h3>
              <div className="diff">
                {DIFF_ROWS.map((row) => (
                  <div className="diff-row" key={row.text}>
                    <span className="sign" aria-hidden="true">
                      {row.sign}
                    </span>
                    <span className={row.kind}>
                      <span className="visually-hidden">
                        {row.kind === "add" ? "Adicionado: " : row.kind === "del" ? "Removido: " : "Igual: "}
                      </span>
                      {row.text}
                    </span>
                  </div>
                ))}
              </div>
              <p className="hint" style={{ marginTop: "var(--sp-3)" }}>
                O sinal da esquerda é decoração; cada linha diz em texto se foi adicionada, removida ou mantida.
              </p>
            </div>
          </div>

          <div className="two-col">
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
                Execuções por motor
              </h3>
              {BAR_ROWS.map((row) => (
                <div className="bar-row" key={row.name}>
                  <span className="od-truncate">{row.name}</span>
                  <span className="bar-track">
                    <span className="bar-fill" style={{ width: `${row.pct}%` }} />
                  </span>
                  <span className="val">{row.value}</span>
                </div>
              ))}
            </div>

            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-2)" }}>
                Taxa de sucesso por semana
              </h3>
              <div
                className="chart"
                role="img"
                aria-label="Gráfico de barras da taxa de sucesso semanal: variou entre 78% e 96% nas últimas 8 semanas."
              >
                {WEEKLY.map((value, index) => (
                  <div className="col" key={`semana-${index + 1}`}>
                    <span className="v">{value}%</span>
                    <span
                      className={`bar${index === WEEKLY.length - 1 ? " is-today" : ""}`}
                      style={{ height: `${value}%` }}
                    />
                    <span className="x">S{index + 1}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className={styles.section} id="movimento" aria-labelledby="movimento-titulo">
          <h2 id="movimento-titulo">Movimento</h2>
          <p className={styles.sub}>
            Curto e funcional: 150–300ms, saída com <span className="mono">ease-out</span> e entrada com{" "}
            <span className="mono">ease-in</span> quando aplicável. O movimento explica mudança de estado — nunca
            decora. Tudo respeita <span className="mono">prefers-reduced-motion</span> e o controle manual em
            Configurações.
          </p>
          <div className={styles.specGrid}>
            {MOTION_TOKENS.map((token) => (
              <div className="card" key={token.token}>
                <strong className="card-title">{token.token}</strong>
                <p className="card-sub" style={{ marginTop: "var(--sp-1)" }}>
                  {token.value}
                </p>
                <p className="hint">{token.use}</p>
              </div>
            ))}
          </div>
          <div className="card">
            <Switch
              checked={motion === "reduced"}
              onChange={(value) => setMotion(value ? "reduced" : "full")}
              label="Reduzir animações"
              hint="O mesmo interruptor de Configurações. Vale para esta sessão e para as próximas visitas."
            />
          </div>
        </section>

        <section className={styles.section} id="acessibilidade" aria-labelledby="acessibilidade-titulo">
          <h2 id="acessibilidade-titulo">Acessibilidade</h2>
          <div className="two-col">
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
                <Icon name="i-accessibility" size="sm" /> Regras aplicadas
              </h3>
              <ul className={styles.ruleList}>
                {A11Y_RULES.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </div>
            <div className="card">
              <h3 className="card-title" style={{ marginBottom: "var(--sp-3)" }}>
                <Icon name="i-keyboard" size="sm" /> Atalhos
              </h3>
              <div className="stack-sm" style={{ fontSize: "var(--fs-13)", color: "var(--text-2)" }}>
                {SHORTCUTS.map((shortcut) => (
                  <div className="row-between" key={shortcut.what}>
                    <span>{shortcut.what}</span>
                    <span className="od-cluster" style={{ "--od-gap": "4px" } as CSSProperties}>
                      {shortcut.keys.map((key) => (
                        <span className="kbd" key={key}>
                          {key}
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <footer className={styles.foot}>
          <p>
            Pond Glass · documentação viva do painel zfrog. Os valores vêm de{" "}
            <span className="mono">ds-tokens.css</span> e <span className="mono">ds-components.css</span>, os mesmos que
            as telas usam.
          </p>
        </footer>
      </div>
    </div>
  )
}
