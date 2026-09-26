"use client"
import Link from "next/link"
import { MODES, MODE_ORDER } from "@/lib/labels"
import { Topbar } from "@/components/Navbar"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Download,
  Search,
  Package,
  FolderTree,
  FileCode2,
  Table2,
  ShieldCheck,
  Gauge,
  ArrowRight,
  Lightbulb,
} from "lucide-react"

const steps = [
  {
    n: 1,
    title: "Cole o endereço do site",
    body: "Vá em Nova extração e informe o endereço completo da página que quer copiar, começando com https://.",
  },
  {
    n: 2,
    title: "Escolha o que quer receber",
    body: "Cada modo entrega uma coisa diferente. Se estiver em dúvida, use \"Página única\" para testar rápido, ou clique em Analisar para o Zfrog recomendar.",
  },
  {
    n: 3,
    title: "Acompanhe e baixe",
    body: "A extração aparece em Execuções. Quando o status virar Concluído, clique em Download para pegar o arquivo ZIP.",
  },
]

const glossary = [
  {
    term: "Extração",
    body: "Uma tarefa de cópia ou leitura de site. Cada vez que você inicia, cria uma extração com um identificador próprio.",
  },
  {
    term: "Analisar",
    body: "Verificação rápida que descobre se o site precisa de navegador e qual modo funciona melhor. Não baixa nada.",
  },
  {
    term: "Páginas percorridas (profundidade)",
    body: "Quantos links o Zfrog segue a partir da página inicial. 0 = só ela. 1 = ela e os links dela. Quanto maior, mais arquivos e mais tempo.",
  },
  {
    term: "Navegador de verdade",
    body: "Um Chrome sem janela que executa o JavaScript do site. Necessário em aplicativos modernos onde o conteúdo só aparece depois que a página carrega.",
  },
  {
    term: "Rastreadores",
    body: "Scripts de publicidade e estatística (Google Analytics, Facebook Pixel e outros). O Zfrog remove automaticamente do que você baixa.",
  },
  {
    term: "Velocidade (limite de requisições)",
    body: "Quantos pedidos por segundo o Zfrog faz ao site. Valores baixos são mais educados e reduzem o risco de bloqueio.",
  },
]

export default function HelpPage() {
  return (
    <div className="space-y-6 max-w-[1100px] animate-[slide-in_0.3s_ease]">
      <Topbar
        title="Ajuda"
        description="O que o Zfrog faz, como usar e qual modo escolher."
      />

      {/* O que a ferramenta faz */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="h-4 w-4" /> O que o Zfrog faz
          </CardTitle>
          <CardDescription>Em uma frase</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-[13.5px] leading-relaxed">
          <p>
            O Zfrog copia sites para o seu computador. Você informa um endereço e ele baixa as páginas, imagens e
            estilos, deixando tudo pronto para abrir sem internet.
          </p>
          <p>
            Ele também consegue <strong className="text-foreground">extrair dados</strong> — em vez do site visual, você
            recebe uma tabela com títulos, textos, links e imagens de cada página.
          </p>
          <p className="text-muted-foreground">
            Durante o processo, o Zfrog ajusta os links para funcionarem offline e remove scripts de rastreamento.
          </p>
        </CardContent>
      </Card>

      {/* Como usar */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ArrowRight className="h-4 w-4" /> Como usar em 3 passos
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {steps.map((s) => (
            <div key={s.n} className="flex gap-3 rounded-[12px] border bg-card/50 p-4">
              <div className="h-7 w-7 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-[12px] font-semibold shrink-0">
                {s.n}
              </div>
              <div>
                <p className="text-[13.5px] font-medium">{s.title}</p>
                <p className="text-[12.5px] text-muted-foreground mt-0.5 leading-relaxed">{s.body}</p>
              </div>
            </div>
          ))}
          <Link href="/probe" className="inline-block pt-1">
            <Button size="sm">
              Começar agora <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </CardContent>
      </Card>

      {/* Qual modo escolher */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="h-4 w-4" /> Qual modo escolher?
          </CardTitle>
          <CardDescription>Os quatro modos, o que cada um faz e quando usar</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {MODE_ORDER.map((m) => {
            const info = MODES[m]
            return (
              <div key={m} className="rounded-[12px] border bg-card/50 p-4">
                <div className="flex items-center gap-2">
                  <span className="text-[15px]">{info.icon}</span>
                  <span className="text-[14px] font-semibold">{info.label}</span>
                </div>
                <p className="text-[13px] mt-2 leading-relaxed">{info.what}</p>
                <div className="grid sm:grid-cols-2 gap-3 mt-3">
                  <div className="rounded-[10px] bg-secondary p-3">
                    <p className="text-[10.5px] uppercase tracking-widest text-muted-foreground font-medium">
                      Use quando
                    </p>
                    <p className="text-[12px] mt-1 leading-relaxed">{info.when}</p>
                  </div>
                  <div className="rounded-[10px] bg-secondary p-3">
                    <p className="text-[10.5px] uppercase tracking-widest text-muted-foreground font-medium">
                      Você recebe
                    </p>
                    <p className="text-[12px] mt-1 leading-relaxed">{info.output}</p>
                  </div>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* O que você recebe */}
      <div className="grid md:grid-cols-3 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FolderTree className="h-4 w-4" /> Arquivos do site
            </CardTitle>
          </CardHeader>
          <CardContent className="text-[12.5px] text-muted-foreground leading-relaxed">
            Nos modos <strong className="text-foreground">Site completo</strong> e{" "}
            <strong className="text-foreground">Site com JavaScript</strong> você recebe o HTML mais as pastas de
            imagens e estilos, com os links já ajustados para abrir offline.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode2 className="h-4 w-4" /> Arquivo único
            </CardTitle>
          </CardHeader>
          <CardContent className="text-[12.5px] text-muted-foreground leading-relaxed">
            No modo <strong className="text-foreground">Página única</strong> sai um só arquivo{" "}
            <span className="font-mono">.html</span> com imagens e estilos embutidos. Bom para guardar e enviar por
            e-mail.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Table2 className="h-4 w-4" /> Dados em tabela
            </CardTitle>
          </CardHeader>
          <CardContent className="text-[12.5px] text-muted-foreground leading-relaxed">
            No modo <strong className="text-foreground">Dados em tabela</strong> saem dois arquivos:{" "}
            <span className="font-mono">dados.json</span> (completo, para programas) e{" "}
            <span className="font-mono">dados.csv</span> (abre no Excel e no Google Planilhas).
          </CardContent>
        </Card>
      </div>

      {/* Glossário */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-4 w-4" /> Palavras que aparecem na tela
          </CardTitle>
        </CardHeader>
        <CardContent className="grid sm:grid-cols-2 gap-3">
          {glossary.map((g) => (
            <div key={g.term} className="rounded-[12px] bg-secondary p-3">
              <p className="text-[13px] font-medium">{g.term}</p>
              <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">{g.body}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Boas práticas */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" /> Para não ser bloqueado
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-[13px]">
          <p className="flex gap-2">
            <Gauge className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
            <span>
              Reduza a <Link href="/config" className="text-primary underline">velocidade</Link> em sites grandes ou com
              proteção. 1 pedido por segundo costuma ser seguro.
            </span>
          </p>
          <p className="flex gap-2">
            <Search className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
            <span>
              Comece com uma <strong className="text-foreground">profundidade baixa</strong> (0 ou 1) para ver o
              resultado antes de percorrer o site inteiro.
            </span>
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-center pb-4">
        <Link href="/probe">
          <Button>
            Ir para Nova extração <ArrowRight className="h-4 w-4" />
          </Button>
        </Link>
      </div>
    </div>
  )
}
