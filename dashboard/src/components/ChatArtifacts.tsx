import { Link } from "@tanstack/react-router"

export function InspectionArtifact({ url }: { url: string }) {
  const host = url.replace(/^https?:\/\//, "").split("/")[0] || url

  return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Screenshot & Design Tokens · {host}</strong>
        <span className="small muted" style={{ fontFamily: "var(--font-mono)" }}>
          1280×800 · auditado
        </span>
      </div>
      <div className="zf-artifact-body">
        <div className="grid2">
          <div style={{ border: "1px solid var(--line)", padding: "12px", background: "var(--bg)" }}>
            <div className="small muted" style={{ fontFamily: "var(--font-mono)" }}>Tipografia & Ritmo</div>
            <div style={{ marginTop: "8px", fontSize: "13px", lineHeight: 1.5 }}>
              <div><span className="muted">Mono:</span> Iosevka · 400/500 · 13px</div>
              <div><span className="muted">Escala:</span> 12 / 13 / 15px</div>
              <div><span className="muted">Line-height:</span> 1.5</div>
            </div>
          </div>
          <div style={{ border: "1px solid var(--line)", padding: "12px", background: "var(--bg)" }}>
            <div className="small muted" style={{ fontFamily: "var(--font-mono)" }}>WCAG 2.2 AA Contrast</div>
            <div style={{ marginTop: "8px", fontSize: "13px" }}>
              <div>fg/bg <strong>15.2:1</strong> <span className="small muted">· AAA</span></div>
              <div>muted/bg <strong>6.75:1</strong> <span className="small muted">· AA</span></div>
              <div>accent/ink <strong>5.36:1 / 7.73:1</strong> <span className="small muted">· AA/AAA</span></div>
            </div>
          </div>
        </div>

        <div className="row" style={{ marginTop: "12px" }}>
          <span className="chip active">radius 0</span>
          <span className="chip active">hairline 1px</span>
          <span className="chip active">100ms</span>
          <span className="chip">sem sombras</span>
          <Link
            to="/probe"
            search={{ url }}
            className="copy-btn"
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
        <strong>Tabela Comparativa — {siteA} × {siteB}</strong>
        <Link to="/comparar" className="copy-btn" style={{ textDecoration: "none" }}>
          Abrir Comparador completo →
        </Link>
      </div>
      <div className="zf-artifact-body" style={{ padding: 0 }}>
        <div style={{ overflow: "auto" }}>
          <table className="mini-table">
            <thead>
              <tr>
                <th>Atributo</th>
                <th>{siteA}</th>
                <th>{siteB}</th>
                <th>Divergência</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Paleta Acento</td>
                <td><i className="swatch" style={{ background: "#4f6b3a" }} /> #4f6b3a (swamp)</td>
                <td><i className="swatch" style={{ background: "#68655d" }} /> neutro</td>
                <td>{siteA} usa cor técnica; {siteB} monocromático</td>
              </tr>
              <tr>
                <td>Densidade</td>
                <td>alta · 13px base</td>
                <td>média · 15px base</td>
                <td>{siteA} +14% mais compacto</td>
              </tr>
              <tr>
                <td>Border Radius</td>
                <td>0px (plano)</td>
                <td>6px</td>
                <td>{siteA} adota TUI rigorosa</td>
              </tr>
              <tr>
                <td>Superfície Base</td>
                <td>#f4f2ec papel quente</td>
                <td>#ffffff neutro frio</td>
                <td>temperatura de cor distinta</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export function DatasetsArtifact() {
  return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Catálogo de Datasets Locais</strong>
        <Link to="/datasets" className="copy-btn" style={{ textDecoration: "none" }}>
          Abrir Datasets →
        </Link>
      </div>
      <div className="zf-artifact-body" style={{ padding: 0 }}>
        <div style={{ overflow: "auto" }}>
          <table className="mini-table">
            <thead>
              <tr>
                <th>Dataset</th>
                <th className="num">Registros</th>
                <th>Atualização</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>Referências UI</strong> <span className="small muted">· capturas + tokens</span></td>
                <td className="num">2.847</td>
                <td>hoje</td>
              </tr>
              <tr>
                <td><strong>Tokens WCAG</strong> <span className="small muted">· contraste auditado</span></td>
                <td className="num">14.223</td>
                <td>ontem</td>
              </tr>
              <tr>
                <td><strong>Competidores SEO</strong> <span className="small muted">· grafo de mercado</span></td>
                <td className="num">542</td>
                <td>há 3 dias</td>
              </tr>
              <tr>
                <td><strong>Snapshots Temporais</strong> <span className="small muted">· histórico de DOM</span></td>
                <td className="num">8.156</td>
                <td>esta semana</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export function CollectionArtifact() {
  return (
    <div className="zf-artifact">
      <div className="zf-artifact-head">
        <strong>Grade de Referências do Acervo</strong>
        <Link to="/colecao" className="copy-btn" style={{ textDecoration: "none" }}>
          Abrir Coleção completa →
        </Link>
      </div>
      <div className="zf-artifact-body">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "10px" }}>
          {[
            { name: "Linear App", tags: "escuro · 3 cores · mono" },
            { name: "Notion Docs", tags: "neutro · sans · limpo" },
            { name: "Vercel Platform", tags: "monocromático · acento azul" },
          ].map((item, idx) => (
            <div key={idx} style={{ border: "1px solid var(--line)", background: "var(--bg)", padding: "10px" }}>
              <div
                style={{
                  aspectRatio: "16/10",
                  background: "var(--sel-bg)",
                  borderBottom: "1px solid var(--line)",
                  display: "grid",
                  placeItems: "center",
                  color: "var(--fg-dim)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  marginBottom: "8px",
                }}
              >
                16:10 preview
              </div>
              <div style={{ fontWeight: 500, fontSize: "13px" }}>{item.name}</div>
              <div className="small muted" style={{ marginTop: "2px" }}>{item.tags}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
