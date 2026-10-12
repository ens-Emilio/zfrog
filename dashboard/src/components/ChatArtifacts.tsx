import { Link } from "@tanstack/react-router"

export function InspectionArtifact({ url }: { url: string }) {
  const host = url.replace(/^https?:\/\//, "").split("/")[0] || url

  return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Inspeção · {host}</strong>
        <span className="zf-meta" style={{ fontFamily: "var(--font-mono)" }}>
          prévia no chat
        </span>
      </div>
      <div className="zf-artifact-body">
        <div className="zf-split zf-split--2">
          <div style={{ border: "1px solid var(--border)", padding: "12px", background: "var(--bg)" }}>
            <div className="zf-meta" style={{ fontFamily: "var(--font-mono)" }}>O que será analisado</div>
            <div style={{ marginTop: "8px", fontSize: "13px", lineHeight: 1.5 }}>
              <div>Captura da página e extração de estilos</div>
              <div className="zf-meta" style={{ marginTop: "4px" }}>Fontes, cores e espaçamento reais aparecem após a captura.</div>
            </div>
          </div>
          <div style={{ border: "1px solid var(--border)", padding: "12px", background: "var(--bg)" }}>
            <div className="zf-meta" style={{ fontFamily: "var(--font-mono)" }}>Acessibilidade</div>
            <div style={{ marginTop: "8px", fontSize: "13px" }}>
              <div>Contraste e estrutura serão auditados na página capturada.</div>
              <div className="zf-meta" style={{ marginTop: "4px" }}>O relatório completo abre no Inspector.</div>
            </div>
          </div>
        </div>

        <div className="zf-row" style={{ marginTop: "12px" }}>
          <span className="zf-chip">captura</span>
          <span className="zf-chip">estilos</span>
          <span className="zf-chip">sem dados fictícios</span>
          <Link
            to="/probe"
            search={{ url }}
            className="zf-btn zf-btn--ghost"
            style={{ marginLeft: "auto", textDecoration: "none" }}
          >
            Abrir no Inspector completo →
          </Link>
        </div>
      </div>
    </div>
  )
}

export function ComparisonArtifact({ siteA, siteB }: { siteA: string; siteB: string }) {
  return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Comparação — {siteA} × {siteB}</strong>
        <Link to="/comparar" className="zf-btn zf-btn--ghost" style={{ textDecoration: "none" }}>
          Abrir Comparador →
        </Link>
      </div>
      <div className="zf-artifact-body">
        <div style={{ border: "1px solid var(--border)", padding: "12px", background: "var(--bg)", fontSize: "13px", lineHeight: 1.5 }}>
          Prévia do chat. A tabela com paleta, densidade, radius e superfície real será preenchida
          após a análise das duas URLs. Nenhum valor acima é inventado.
        </div>
        <div className="zf-row" style={{ marginTop: "12px" }}>
          <span className="zf-chip">{siteA}</span>
          <span className="zf-chip">{siteB}</span>
          <span className="zf-chip">comparação real só após capturar</span>
        </div>
      </div>
    </div>
  )
}

export function DatasetsArtifact() { return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Datasets</strong>
        <Link to="/datasets" className="zf-btn zf-btn--ghost" style={{ textDecoration: "none" }}>
          Abrir Datasets →
        </Link>
      </div>
      <div className="zf-artifact-body">
        <div style={{ border: "1px solid var(--border)", padding: "12px", background: "var(--bg)", fontSize: "13px", lineHeight: 1.5 }}>
          O catálogo com contagens e datas reais fica em Datasets. Nenhum número é inventado no chat.
        </div>
      </div>
    </div>
  )
}

export function CollectionArtifact() {
  return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Coleção</strong>
        <Link to="/colecao" className="zf-btn zf-btn--ghost" style={{ textDecoration: "none" }}>
          Abrir Coleção →
        </Link>
      </div>
      <div className="zf-artifact-body">
        <div style={{ border: "1px solid var(--border)", padding: "12px", background: "var(--bg)", fontSize: "13px", lineHeight: 1.5 }}>
          A grade com previews reais fica em Coleção. O chat inicia a busca; os resultados vêm dos dados capturados.
        </div>
      </div>
    </div>
  )
}
