 # Plano de Implementação: Zfrog Desktop Nativo com Tauri v2
 
 Status: **CONCLUÍDO (100%)** — todas as fases implementadas e validadas. Ver §5 Checklist.
 
 Este documento estabelece a arquitetura, etapas e especificações técnicas para transformar o **zfrog** (Dashboard TUI em React 19 + Motor Python/FastAPI/Playwright) em uma aplicação desktop nativa instalável para **Linux** (`.deb`, `.AppImage`) e **Windows** (`.exe` NSIS, `.msi`).
---

## 1. Por que Tauri v2 para o Zfrog?

1. **Reaproveitamento Total da UI TUI**: O frontend já desenvolvido em `dashboard/` (React 19, TanStack Router/Query, Tailwind v4 e tipografia Iosevka) é compilado diretamente e embutido sem adaptações visuais complexas.
2. **Consumo Mínimo de Recursos**: Utiliza a WebView nativa do sistema operacional (Edge WebView2 no Windows e WebKitGTK no Linux) — consome entre 40 MB e 70 MB de RAM (contra 250 MB+ de uma solução baseada em Electron).
3. **Segurança e Arquitetura Sidecar**: O backend Python (`zfrog serve` / CLI) é empacotado como um processo filho (*sidecar*) estritamente isolado e gerenciado pelo runtime em Rust do Tauri, com comunicação via loopback autenticado.
4. **Instalação em 1 Clique**: Elimina para o usuário final a necessidade de ter Node.js, `npm`, `uv` ou Python instalados previamente no terminal.

---

## 2. Topologia da Arquitetura

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Zfrog Desktop (Janela do SO)                     │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Webview Nativa (Frontend TUI)                 │  │
│  │  - React 19 + TanStack Router + Tailwind CSS 4                   │  │
│  │  - Interface estilo Terminal (Pond Glass / TUI monospaçada)      │  │
│  │  - Cliente HTTP consumindo a API local em 127.0.0.1:<PORT>       │  │
│  └─────────────────────────────────┬────────────────────────────────┘  │
│                                    │ IPC (@tauri-apps/api)             │
│  ┌─────────────────────────────────▼────────────────────────────────┐  │
│  │                  Tauri Core (Rust Runtime v2)                    │  │
│  │  - Gerenciador de Janela, Tray Icon, Notificações e Atalhos      │  │
│  │  - File Dialogs nativos (abrir/salvar referências e tokens)      │  │
│  │  - Gerenciador do Ciclo de Vida do Processo Sidecar (Python)     │  │
│  └─────────────────────────────────┬────────────────────────────────┘  │
│                                    │ Spawna, monitora e encerra        │
│  ┌─────────────────────────────────▼────────────────────────────────┐  │
│  │              Python Sidecar Engine (zfrog-api standalone)        │  │
│  │  - FastAPI + Uvicorn (porta dinâmica e token efêmero)            │  │
│  │  - Motores: jump, tongue, Scrapy, Playwright                     │  │
│  │  - SQLite local (catalog.db, metrics.db, search.db)              │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Fases de Execução

### Fase 1: Fundação do Tauri v2 no Repositório
Configurar o ambiente Rust e a estrutura de pastas integrada ao `dashboard/`.

- [x] **1.1. Inicialização do Projeto Tauri**:
  - Criar `src-tauri/` na raiz ou no diretório de frontend.
  - Configurar `src-tauri/Cargo.toml` com as dependências do Tauri v2:
    - `tauri` (v2)
    - `tauri-plugin-shell` (para orquestração de processos)
    - `tauri-plugin-dialog` (para escolha de diretórios de exportação)
    - `tauri-plugin-notification` (avisos de conclusão de capturas e diffs)
    - `tauri-plugin-opener` (abrir pastas no explorador do sistema)
    - `portpicker` (alocação de porta livre para a API local)
- [x] **1.2. Configuração de Build (`src-tauri/tauri.conf.json`)**:
  - Apontar `build.frontendDist` para `../dashboard/dist`.
  - Apontar `build.devUrl` para `http://localhost:3000`.
  - Definir identificador: `com.zfrog.desktop`.
- [x] **1.3. Integração de Scripts npm (`dashboard/package.json`)**:
  - `"desktop:dev": "tauri dev"`
  - `"desktop:build": "tauri build"`

---

### Fase 2: Estratégia de Sidecar do Backend Python
O backend do zfrog precisa rodar de forma transparente sem exigir instalação de interpretador Python pelo usuário.

- [x] **2.1. Criação do Entrypoint Standalone para o Sidecar**:
  - Criar `src/zfrog/desktop_entry.py`:
    - Recebe argumentos de porta (`--port`), host (`127.0.0.1`) e token efêmero de autenticação (`--auth-token`).
    - Configura os diretórios de dados padrão do usuário (ex: `~/.local/share/zfrog` no Linux e `%APPDATA%\zfrog` no Windows para os bancos SQLite e saídas `output/`).
- [x] **2.2. Script de Congelamento do Executável (PyInstaller / PyOxidizer)**:
  - Script para gerar os binários nomeados de acordo com a convenção de target do Tauri:
    - Linux: `src-tauri/binaries/zfrog-api-x86_64-unknown-linux-gnu`
    - Windows: `src-tauri/binaries/zfrog-api-x86_64-pc-windows-msvc.exe`
- [x] **2.3. Gestão de Ciclo de Vida em Rust (`src-tauri/src/lib.rs`)**:
  - **No Boot do App**:
    1. Escolher uma porta livre via `portpicker::pick_unused_port()`.
    2. Gerar uma chave de sessão efêmera aleatória.
    3. Iniciar o processo do sidecar passando `--port` e `--auth-token`.
    4. Executar polling no endpoint de healthcheck (`GET http://127.0.0.1:{port}/health`) com timeout de 8 segundos.
    5. Injetar a URL base e o token no frontend via evento ou comando Tauri inicial.
  - **No Encerramento do App**:
    - Interceptar evento `WindowEvent::CloseRequested` e sinais de encerramento (`SIGINT`/`SIGTERM`) para matar graciosamente o processo filho, evitando processos zumbis de Python no sistema.

---

### Fase 3: Integração com o SO e Experiência Desktop TUI
Aproveitar os recursos de sistema operacional para elevar a experiência além de uma simples aba de navegador.

- [x] **3.1. Estética e Janela Nativa**:
  - Janela com decoração minimalista compatível com o tema TUI (Pond Glass).
  - Título e controles customizados respeitando o ritmo visual de 1px hairlines.
  - Tamanho inicial padrão: 1280×820 (com mínimo de 960×600).
- [x] **3.2. Bandeja do Sistema (System Tray)**:
  - Ícone do sapinho (`mascot.png`) na área de notificação/bandeja do sistema.
  - Menu de contexto:
    - *Exibir / Ocultar Zfrog*
    - *Novo Jump (Captura Rápida)*
    - *Abrir Pasta de Referências*
    - *Status dos Workers / Jobs*
    - *Sair*
- [x] **3.3. Atalhos Globais e Notificações**:
  - Atalho global opcional (ex: `Super+Alt+Z` / `Win+Alt+Z`) para trazer o zfrog para o foco ou abrir modal de captura rápida.
  - Notificações nativas do sistema disparadas quando:
    - Uma extração (`jump` ou `tongue`) for concluída.
    - Um agendamento recorrente capturar um diff com alterações relevantes.
- [x] **3.4. Diálogos Nativos do SO**:
  - Seleção de pasta de saída de exportação via seletor nativo do SO (`dialog.open({ directory: true })`).
  - Ação "Abrir na pasta" que revela a referência ou screenshot no explorador nativo (Dolphin/Nautilus no Linux, Windows Explorer no Windows).

---

### Fase 4: Gestão do Playwright e Navegadores no Desktop
Os motores `jump` e visual extraction utilizam Playwright. Em um app desktop, há duas estratégias recomendadas:

- [x] **4.1. Estratégia Híbrida de Browser**:
  - **Modo Primário**: Tentar usar navegadores já instalados na máquina do usuário através das opções `channel="chrome"` ou `channel="msedge"` do Playwright (o Windows sempre terá Edge instalado, e no Linux a maioria dos desenvolvedores possui Chrome/Chromium).
  - **Modo Fallback / Primeiro Uso**: Se nenhum navegador compatível for encontrado, exibir na interface TUI uma barra de progresso para download do Chromium headless isolado em `~/.cache/zfrog/browsers`.

---

### Fase 5: Pipeline de Distribuição e Empacotamento (CI/CD)

- [x] **5.1. Alvos Linux**:
  - Gerar pacote `.AppImage` (compatível com qualquer distribuição sem dependência de gerenciador de pacotes).
  - Gerar pacote `.deb` para distribuições baseadas em Debian/Ubuntu com dependências declaradas (`libwebkit2gtk-4.1-0`).
- [x] **5.2. Alvos Windows**:
  - Gerar instalador `.exe` (NSIS) leve com assistente de instalação.
  - Suporte a instalação por usuário (sem exigir privilégios de Administrador).
- [x] **5.3. Workflow de Release no GitHub Actions (`.github/workflows/desktop.yml`)**:
  - Matriz com runners `ubuntu-latest` e `windows-latest`.
  - Passos:
    1. Instalação de Rust, Node.js e Python.
    2. Build do executável Python (PyInstaller).
    3. Build do frontend Vite (`npm run build`).
    4. Execução do `tauri build` gerando os artefatos finais assinados anexados às releases do GitHub.

---

## 4. Estrutura de Arquivos Proposta

```
zfrog/
├── docs/
│   └── PLANO-TAURI.md              # Este documento de referência
├── src/
│   └── zfrog/
│       └── desktop_entry.py        # Ponto de entrada do sidecar com flags desktop
├── dashboard/                      # Frontend TUI React 19 já existente
│   └── src/
│       ├── lib/
│       │   └── desktop.ts          # Wrappers para APIs do Tauri (tray, dialog, fs)
│       └── ...
└── src-tauri/                      # Novo módulo nativo Rust
    ├── Cargo.toml                  # Dependências Rust e plugins Tauri
    ├── tauri.conf.json             # Configuração da janela, bundle e sidecar
    ├── icons/                      # Ícones em múltiplos formatos (.ico, .png)
    ├── binaries/                   # Binários congelados do backend por target
    └── src/
        ├── lib.rs                  # Ciclo de vida, setup, interceptações de encerramento
        └── main.rs                 # Executável de entrada
```

---

## 5. Checklist de Verificação e Próximos Passos

| Etapa | Responsável | Critério de Sucesso |
|---|---|---|
| **1. Instalação do Rust e Tauri CLI** | Dev / Ambiente | `cargo --version` e `npm run tauri -- --version` funcionando |
| **2. Teste de Janela Nativa Simples** | Frontend | `dashboard` abrindo dentro de uma janela nativa Tauri |
| **3. Build Standalone do Sidecar** | Backend | Binário `zfrog-api` iniciando a API FastAPI sem depender de `python -m` |
| **4. Comunicação Frontend-Backend** | Integração | Dashboard realizando queries e jumps através da porta efêmera |
| **5. Fechamento Limpo** | SO | Ao fechar a janela, nenhum processo de backend permanece ativo |
| **6. Geração de Instaladores** | Build / CI | Binários `.AppImage` e `.exe` instalando e rodando em máquinas limpas |

