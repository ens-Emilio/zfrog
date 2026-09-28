import { JobMode, JobStatus } from "./api"
import type { IconName } from "./icons"

/** Short label for status pills and table cells. */
export const STATUS_LABELS: Record<JobStatus, string> = {
  pending: "Na fila",
  probing: "Analisando",
  processing: "Organizando",
  running: "Baixando",
  completed: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
}

/** Very short label for the progress stepper. */
export const STATUS_SHORT: Record<JobStatus, string> = {
  pending: "Fila",
  probing: "Análise",
  processing: "Organizar",
  running: "Baixar",
  completed: "Pronto",
  failed: "Falhou",
  cancelled: "Cancelado",
}

/** One sentence explaining what the status means, shown to the user. */
export const STATUS_HELP: Record<JobStatus, string> = {
  pending: "Aguardando um espaço livre para começar.",
  probing: "Verificando como o site é feito para escolher a melhor forma de capturar.",
  processing: "Organizando os arquivos: ajustando links e removendo rastreadores.",
  running: "Capturando o conteúdo do site. O tempo depende do tamanho.",
  completed: "Pronto. O resultado está disponível para baixar.",
  failed: "Algo deu errado. Veja o console da execução para o motivo.",
  cancelled: "Interrompida por você. O que já tinha sido capturado foi descartado.",
}

export interface ModeInfo {
  /** Nome curto exibido nos tiles e na navegação. */
  label: string
  /** Nome do ícone no design system. */
  icon: IconName
  /** O que o modo faz, em uma frase. */
  what: string
  /** Quando escolher este modo. */
  when: string
  /** O que o usuário recebe no fim. */
  output: string
  /** `rec` aparece como tile; `adv` fica no menu "Mais modos…". */
  group: "rec" | "adv"
}

/**
 * The extraction modes, in the order and with the wording of the design system.
 *
 * `auto` leads because it is the backend default: the probe picks the capture motor.
 * The four recommended tiles are the capture modes; everything else lives behind
 * "Mais modos…" so the first screen stays a single decision.
 */
export const MODES: Record<JobMode, ModeInfo> = {
  auto: {
    label: "Auto",
    icon: "i-frog",
    group: "rec",
    what: "O zfrog analisa o site e escolhe sozinho a melhor forma de capturar a referência.",
    when: "Você não quer pensar em modos: cole o endereço e deixe o zfrog decidir.",
    output: "O mesmo resultado do modo ideal, escolhido pelo zfrog.",
  },
  singlepage: {
    label: "Página única",
    icon: "i-file",
    group: "rec",
    what: "Salva esta página em um único arquivo HTML, com imagens e estilos embutidos.",
    when: "Você quer guardar um artigo, uma receita ou uma página específica.",
    output: "Um .html que abre no navegador e funciona sem internet.",
  },
  mirror: {
    label: "Site completo",
    icon: "i-globe",
    group: "rec",
    what: "Baixa a página e tudo que está ligado a ela, mantendo a estrutura de pastas.",
    when: "Você quer o site inteiro para ler offline, fazer backup ou republicar.",
    output: "ZIP com vários .html, imagens e estilos.",
  },
  scrape: {
    label: "Site com JavaScript",
    icon: "i-code",
    group: "rec",
    what: "Abre o site em um navegador de verdade e espera o JavaScript montar a página.",
    when: "O site é um app moderno (React, Vue, Angular) e o modo Site completo traz páginas vazias.",
    output: "A página já montada mais os arquivos que o JavaScript carregou.",
  },
  delta: {
    label: "Só o que mudou",
    icon: "i-repeat",
    group: "rec",
    what: "Compara com a última cópia e baixa apenas as páginas que mudaram de verdade.",
    when: "Você acompanha um site e quer economizar tempo e banda a cada nova cópia.",
    output: "Páginas alteradas + delta_report.json.",
  },
  extract: {
    label: "Dados em tabela",
    icon: "i-database",
    group: "adv",
    what: "Lê as páginas e separa título, texto, links e imagens de cada uma.",
    when: "Você quer os dados para analisar, não o visual do site.",
    output: "dados.json (completo) e dados.csv (abre no Excel).",
  },
  analyze: {
    label: "Auditoria técnica",
    icon: "i-search",
    group: "adv",
    what: "Verifica SEO, acessibilidade, performance, stack tecnológica e conteúdo.",
    when: "Você quer saber se o site está bem construído ou documentar a tecnologia usada.",
    output: "Relatório em JSON e Markdown com scores e problemas.",
  },
  compare: {
    label: "Comparar fidelidade",
    icon: "i-scale",
    group: "adv",
    what: "Mede o quanto uma captura é fiel ao original: visual, HTML, texto e arquivos.",
    when: "Você quer verificar se o que foi capturado é uma cópia fiel.",
    output: "Fidelity Score (0-100) com sub-scores em JSON e Markdown.",
  },
  ask: {
    label: "Perguntar ao site",
    icon: "i-message",
    group: "adv",
    what: "Faz uma pergunta em linguagem natural sobre o conteúdo e responde com as fontes.",
    when: "Você quer extrair dados sem escrever seletores ou código.",
    output: "Resposta em texto + dados em JSON + trechos relevantes.",
  },
  pdf: {
    label: "PDF da página",
    icon: "i-file-down",
    group: "adv",
    what: "Abre a página em um navegador e salva o resultado como PDF em A4.",
    when: "Você quer guardar uma página ou relatório para imprimir ou enviar.",
    output: "Um arquivo .pdf pronto para abrir e arquivar.",
  },
  summarize: {
    label: "Resumo IA",
    icon: "i-sparkles",
    group: "adv",
    what: "Lê o conteúdo com inteligência artificial e escreve um resumo curto.",
    when: "Você quer entender uma página longa em segundos.",
    output: "summary.json e summary.md com título e pontos-chave.",
  },
  entities: {
    label: "Nomes e dados",
    icon: "i-users",
    group: "adv",
    what: "Encontra no texto os nomes de pessoas, empresas, lugares, datas e produtos.",
    when: "Você quer uma lista organizada do que aparece na página, sem ler tudo.",
    output: "entities.json e entities.md com cada nome, o tipo e a confiança.",
  },
  translate: {
    label: "Traduzir",
    icon: "i-globe",
    group: "adv",
    what: "Traduz o conteúdo da página para o idioma escolhido, mantendo o texto inteiro.",
    when: "O conteúdo está em outro idioma e você quer ler ou arquivar em português.",
    output: "translation.json e translation.md com o texto traduzido.",
  },
  sentiment: {
    label: "Tom do texto",
    icon: "i-activity",
    group: "adv",
    what: "Diz se o conteúdo é positivo, negativo ou neutro e o quanto, com uma justificativa.",
    when: "Você acompanha avaliações, notícias ou comentários e quer medir o clima.",
    output: "enrichment.json e enrichment.md com o tom e a nota.",
  },
  tags: {
    label: "Assuntos",
    icon: "i-type",
    group: "adv",
    what: "Lê a página e sugere etiquetas curtas com os assuntos principais.",
    when: "Você quer organizar muito conteúdo por tema sem marcar página por página.",
    output: "enrichment.json e enrichment.md com a lista de assuntos.",
  },
  video: {
    label: "Vídeo e transmissões",
    icon: "i-play",
    group: "adv",
    what: "Procura vídeos e transmissões na página, entende o formato e baixa os pedaços.",
    when: "A página tem um player (HLS ou DASH) e você quer guardar o vídeo.",
    output: "streams.json, streams.md e o arquivo do vídeo quando o download for possível.",
  },
  api_discovery: {
    label: "Descobrir API",
    icon: "i-terminal",
    group: "adv",
    what: "Encontra os endereços de API que a página usa por trás, em vez de raspar o HTML.",
    when: "Você quer dados limpos e estáveis de um site que carrega tudo por API.",
    output: "api_endpoints.json e api_endpoints.md com método, tipo e endereço de cada chamada.",
  },
}

/** The four recommended tiles, `auto` first. */
export const RECOMMENDED_MODES = (Object.keys(MODES) as JobMode[]).filter((mode) => MODES[mode].group === "rec")

/** Everything behind "Mais modos…". */
export const ADVANCED_MODES = (Object.keys(MODES) as JobMode[]).filter((mode) => MODES[mode].group === "adv")

/** Every mode in display order: the recommended tiles, then the advanced menu. */
export const MODE_ORDER: JobMode[] = [...RECOMMENDED_MODES, ...ADVANCED_MODES]
