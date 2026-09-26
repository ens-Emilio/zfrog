import { JobMode, JobStatus } from "./api"

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

/** Very short label for the progress timeline (10px text). */
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
  probing: "Verificando como o site é feito para escolher a melhor forma de baixar.",
  processing: "Organizando os arquivos: ajustando links e removendo rastreadores.",
  running: "Baixando o conteúdo do site. O tempo depende do tamanho.",
  completed: "Terminou. O arquivo está pronto para baixar.",
  failed: "Não foi possível concluir. Veja o motivo em detalhes.",
  cancelled: "Interrompido por você.",
}

export interface ModeInfo {
  /** Nome curto exibido nos cards e na navegação. */
  label: string
  icon: string
  /** O que o modo faz, em uma frase. */
  what: string
  /** Quando escolher este modo. */
  when: string
  /** O que o usuário recebe no fim. */
  output: string
}

export const MODES: Record<JobMode, ModeInfo> = {
  auto: {
    label: "Automático",
    icon: "🐸",
    what: "Olha a página antes de capturar e escolhe o motor: navegador quando o conteúdo só aparece com JavaScript, captura leve quando a página já vem pronta.",
    when: "Você não sabe (ou não quer decidir) qual motor usar. É o padrão.",
    output: "A captura visual da página: HTML renderizado, os arquivos que o navegador carregou e um screenshot de página inteira.",
  },
  mirror: {
    label: "Site completo",
    icon: "🌐",
    what: "Baixa a página indicada e todas as páginas ligadas a ela, junto com imagens, estilos e arquivos. Mantém a estrutura de pastas do site.",
    when: "Você quer o site inteiro para ler offline, fazer backup ou publicar em outro lugar.",
    output: "ZIP com vários arquivos .html e as pastas de imagens e estilos.",
  },
  singlepage: {
    label: "Página única",
    icon: "📄",
    what: "Salva somente esta página em um único arquivo HTML, com imagens e estilos embutidos dentro dele.",
    when: "Você quer guardar um artigo, uma receita ou uma página específica sem baixar o site todo.",
    output: "Um arquivo .html que abre no navegador e funciona sem internet.",
  },
  scrape: {
    label: "Site com JavaScript",
    icon: "🧩",
    what: "Abre o site em um navegador de verdade e espera o JavaScript montar a página, como faria um visitante.",
    when: "O site é um aplicativo moderno (React, Vue, Angular) e o modo \"Site completo\" trás páginas vazias.",
    output: "A página já montada (HTML) mais os arquivos que o JavaScript carregou.",
  },
  extract: {
    label: "Dados em tabela",
    icon: "📊",
    what: "Lê as páginas e separa as informações de cada uma: título, texto, links e imagens.",
    when: "Você quer os dados para analisar, não o visual do site. Por exemplo: catálogo de produtos ou lista de notícias.",
    output: "Dois arquivos: dados.json (completo) e dados.csv (abre no Excel).",
  },
  analyze: {
    label: "Auditoria técnica",
    icon: "🔍",
    what: "Verifica o site em vários aspectos: SEO, acessibilidade, performance, stack tecnológica e qualidade do conteúdo.",
    when: "Você quer saber se o site está bem construído, se tem problemas de acessibilidade ou SEO, ou documentar a tecnologia usada.",
    output: "Relatório em JSON e Markdown com scores e lista de problemas encontrados.",
  },
  compare: {
    label: "Comparar fielidade",
    icon: "⚖️",
    what: "Mede o quanto um clone é fiel ao site original, comparando visual, estrutura HTML, conteúdo textual e cobertura de arquivos.",
    when: "Você quer verificar se o que foi baixado é uma cópia fiel, ou comparar dois motores diferentes no mesmo site.",
    output: "Fidelity Score (0-100) com sub-scores detalhados em JSON e Markdown.",
  },
  ask: {
    label: "Perguntar ao site",
    icon: "💬",
    what: "Faz uma pergunta em linguagem natural sobre o conteúdo do site e recebe uma resposta com as fontes encontradas.",
    when: "Você quer extrair dados ou entender algo do site sem escrever seletores ou código. Ex.: 'Quais são os preços?' ou 'Qual o e-mail de contato?'.",
    output: "Resposta em texto + dados extraídos em JSON + trechos relevantes.",
  },
  pdf: {
    label: "PDF da página",
    icon: "📕",
    what: "Abre a página em um navegador de verdade e salva o resultado como um arquivo PDF em A4, com cores e imagens.",
    when: "Você quer guardar uma página ou um relatório em PDF, para imprimir ou enviar por e-mail.",
    output: "Um arquivo .pdf pronto para abrir, imprimir ou arquivar.",
  },
  summarize: {
    label: "Resumo IA",
    icon: "📝",
    what: "Lê o conteúdo da página com inteligência artificial e escreve um resumo curto com os pontos principais.",
    when: "Você quer entender uma página longa em segundos, sem ler tudo.",
    output: "Resumo em texto (summary.json e summary.md) com título e pontos-chave.",
  },
  delta: {
    label: "Só o que mudou",
    icon: "🔁",
    what: "Compara o site com a última cópia e baixa apenas as páginas que mudaram de verdade, em vez de baixar tudo de novo.",
    when: "Você acompanha um site e quer economizar tempo e banda a cada nova cópia.",
    output: "As páginas alteradas + um relatório (delta_report.json) do que mudou e do que foi economizado.",
  },
  entities: {
    label: "Nomes e dados",
    icon: "🏷️",
    what: "Encontra no texto os nomes de pessoas, empresas, lugares, datas e produtos.",
    when: "Você quer uma lista organizada do que aparece na página, sem ler tudo.",
    output: "entities.json e entities.md com cada nome, o tipo e a confiança.",
  },
  translate: {
    label: "Traduzir",
    icon: "🌎",
    what: "Traduz o conteúdo da página para o idioma escolhido, mantendo o texto inteiro.",
    when: "O conteúdo está em outro idioma e você quer ler ou arquivar em português.",
    output: "translation.json e translation.md com o texto traduzido.",
  },
  sentiment: {
    label: "Tom do texto",
    icon: "🙂",
    what: "Diz se o conteúdo é positivo, negativo ou neutro e o quanto, com uma justificativa curta.",
    when: "Você acompanha avaliações, notícias ou comentários e quer medir o clima.",
    output: "enrichment.json e enrichment.md com o tom e a nota.",
  },
  tags: {
    label: "Assuntos",
    icon: "📌",
    what: "Lê a página e sugere etiquetas curtas com os assuntos principais.",
    when: "Você quer organizar muito conteúdo por tema sem marcar página por página.",
    output: "enrichment.json e enrichment.md com a lista de assuntos.",
  },
  video: {
    label: "Vídeo e transmissões",
    icon: "🎬",
    what: "Procura vídeos e transmissões na página, entende o formato e baixa os pedaços do vídeo.",
    when: "A página tem um player (HLS ou DASH) e você quer guardar o vídeo.",
    output: "streams.json, streams.md e o arquivo do vídeo quando o download for possível.",
  },
  api_discovery: {
    label: "Descobrir API",
    icon: "🔌",
    what: "Encontra os endereços de API que a página usa por trás, em vez de raspar o HTML.",
    when: "Você quer dados limpos e estáveis de um site que carrega tudo por API.",
    output: "api_endpoints.json e api_endpoints.md com método, tipo e endereço de cada chamada.",
  },
}

export const MODE_ORDER: JobMode[] = ["auto", "singlepage", "mirror", "scrape", "delta", "extract", "analyze", "compare", "ask", "pdf", "summarize", "entities", "translate", "sentiment", "tags", "video", "api_discovery"]
