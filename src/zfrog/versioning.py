"""Histórico de versões estilo git para clones de sites.

Cada commit grava os arquivos de um clone no armazenamento endereçado por
conteúdo (deduplicação por SHA-256) e referencia o snapshot de mudanças
correspondente. Ramos são ponteiros para o último commit, guardados em
``<root>/<slug>/refs.json``; os commits ficam serializados em
``<root>/<slug>/objects/<id>.json``.

O layout é intencionalmente simples: o histórico é um encadeamento por
``parent``, então operações como ``rollback`` só precisam dos blobs e do
registro do commit.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from zfrog.config import settings
from zfrog.diff import DiffReport, diff_snapshots, snapshots_dir, url_slug
from zfrog.storage.content_addressed import ContentAddressedStore

logger = logging.getLogger(__name__)

# 12 caracteres hexadecimais bastam para uso humano; colisões são checadas
# contra os commits já gravados antes de aceitar um id novo.
ID_LENGTH = 12
# Prefixo mínimo aceito em `resolve`: abaixo disso o risco de ambiguidade é alto.
MIN_PREFIX_LENGTH = 4
HEAD_REF = "HEAD"
DEFAULT_BRANCH = "main"
# O store de blobs nunca faz parte do conteúdo de um clone.
STORE_DIRNAME = ".store"
# Ids são hexadecimais; qualquer outra coisa em `resolve` não é prefixo de id.
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


@dataclass
class Version:
    """Um commit: os arquivos de um clone mais os metadados do snapshot."""

    id: str
    url: str
    snapshot: str
    captured_at: str
    message: str
    parent: str | None
    branch: str
    pages: int
    files: dict[str, str]


def _read_snapshot_meta(path: Path) -> dict:
    """Ler um snapshot JSON; ausente ou ilegível vira ``{}`` (com aviso)."""
    if not path.is_file():
        logger.warning("snapshot inexistente: %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("snapshot ilegível %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _is_safe_relative(rel: str) -> bool:
    """Rejeitar caminhos absolutos ou com ``..`` antes de escrever no destino."""
    parts = Path(rel).parts
    return bool(parts) and not Path(rel).is_absolute() and ".." not in parts


class VersionStore:
    """Histórico de commits por URL, apoiado no store endereçado por conteúdo."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(settings.versions_dir)
        self.store = ContentAddressedStore(self.root / "store")

    # ------------------------------------------------------------------ paths

    def _site_dir(self, url: str) -> Path:
        return self.root / url_slug(url)

    def _refs_path(self, url: str) -> Path:
        return self._site_dir(url) / "refs.json"

    def _objects_dir(self, url: str) -> Path:
        return self._site_dir(url) / "objects"

    # ------------------------------------------------------------------- refs

    def _read_refs(self, url: str) -> dict[str, str]:
        """Ler os ponteiros de ramo; site desconhecido vira ``{}``."""
        path = self._refs_path(url)
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("refs ilegíveis em %s: %s", path, exc)
            return {}
        branches = data.get("branches") if isinstance(data, dict) else None
        if not isinstance(branches, dict):
            return {}
        return {str(name): str(commit) for name, commit in branches.items()}

    def _write_refs(self, url: str, branches: dict[str, str]) -> None:
        path = self._refs_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"branches": {name: branches[name] for name in sorted(branches)}}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # --------------------------------------------------------------- versions

    def _new_id(self, url: str) -> str:
        objects_dir = self._objects_dir(url)
        while True:
            candidate = uuid.uuid4().hex[:ID_LENGTH]
            if not (objects_dir / f"{candidate}.json").exists():
                return candidate

    def _version_path(self, url: str, version_id: str) -> Path:
        return self._objects_dir(url) / f"{version_id}.json"

    def _write_version(self, version: Version) -> None:
        path = self._version_path(version.url, version.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(version), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_version(self, url: str, version_id: str) -> Version | None:
        path = self._version_path(url, version_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("commit ilegível %s: %s", path, exc)
            return None
        if not isinstance(data, dict):
            return None
        known = {f.name for f in fields(Version)}
        try:
            return Version(**{key: value for key, value in data.items() if key in known})
        except TypeError as exc:
            logger.warning("commit inválido %s: %s", path, exc)
            return None

    def _walk(self, url: str, version_id: str | None) -> list[Version]:
        """Seguir a cadeia de ``parent`` a partir de um commit (mais novo primeiro)."""
        chain: list[Version] = []
        seen: set[str] = set()
        current = version_id
        while current and current not in seen:
            seen.add(current)
            version = self._load_version(url, current)
            if version is None:
                logger.warning("commit %s ausente para %s", current, url)
                break
            chain.append(version)
            current = version.parent
        return chain

    # -------------------------------------------------------------- blobs

    def _store_output(self, output_dir: Path) -> dict[str, str]:
        """Guardar cada arquivo do clone e devolver ``caminho -> sha256``.

        ``store_directory`` devolve ``hash -> caminho``, o que colapsa arquivos
        de conteúdo idêntico num único par; como o commit precisa de todos os
        caminhos, o armazenamento é feito arquivo a arquivo (o store continua
        deduplicando por hash).
        """
        files: dict[str, str] = {}
        if not output_dir.is_dir():
            logger.warning("diretório de saída inexistente: %s", output_dir)
            return files
        for path in sorted(output_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(output_dir)
            if rel.parts[0] == STORE_DIRNAME:
                continue
            files[str(rel)] = self.store.store_file(path)
        return files

    # -------------------------------------------------------------- public API

    def commit(
        self,
        url: str,
        snapshot_path: Path,
        output_dir: Path | None = None,
        message: str = "",
        branch: str = DEFAULT_BRANCH,
    ) -> Version:
        """Gravar um commit com os arquivos de ``output_dir`` e avançar o ramo.

        Args:
            url: URL do site versionado.
            snapshot_path: Snapshot de mudanças correspondente (só o nome é guardado).
            output_dir: Diretório do clone; ``None`` grava um commit sem arquivos.
            message: Mensagem do commit.
            branch: Ramo a avançar (criado implicitamente se ainda não existir).

        Returns:
            A ``Version`` gravada.
        """
        snapshot_path = Path(snapshot_path)
        branches = self._read_refs(url)
        parent = branches.get(branch)
        snapshot = _read_snapshot_meta(snapshot_path)
        pages = snapshot.get("pages")
        files = self._store_output(Path(output_dir)) if output_dir is not None else {}

        version = Version(
            id=self._new_id(url),
            url=url,
            snapshot=snapshot_path.name,
            captured_at=str(snapshot.get("captured_at") or ""),
            message=message,
            parent=parent,
            branch=branch,
            pages=len(pages) if isinstance(pages, list) else 0,
            files=files,
        )
        self._write_version(version)

        branches[branch] = version.id
        self._write_refs(url, branches)
        logger.info("versão %s gravada para %s (%d arquivo(s))", version.id, url, len(files))
        return version

    def log(self, url: str, branch: str | None = None) -> list[Version]:
        """Listar commits do mais novo para o mais antigo.

        Sem ``branch``, devolve o histórico de todos os ramos. URL ou ramo
        desconhecido resulta em lista vazia (listagens não falham).
        """
        branches = self._read_refs(url)
        if branch is not None:
            tip = branches.get(branch)
            return self._walk(url, tip) if tip else []

        versions: list[Version] = []
        seen: set[str] = set()
        for name in sorted(branches):
            for version in self._walk(url, branches[name]):
                if version.id not in seen:
                    seen.add(version.id)
                    versions.append(version)
        versions.sort(key=lambda version: version.captured_at, reverse=True)
        return versions

    def head(self, url: str, branch: str = DEFAULT_BRANCH) -> Version | None:
        """Commit apontado pelo ramo, ou ``None`` quando o ramo não existe."""
        version_id = self._read_refs(url).get(branch)
        if version_id is None:
            return None
        return self._load_version(url, version_id)

    def branches(self, url: str) -> list[str]:
        """Nomes dos ramos existentes (ordenados); URL desconhecida vira ``[]``."""
        return sorted(self._read_refs(url))

    def create_branch(self, url: str, name: str, from_branch: str = DEFAULT_BRANCH) -> None:
        """Criar ``name`` apontando para o commit atual de ``from_branch``."""
        branches = self._read_refs(url)
        if from_branch not in branches:
            raise ValueError(f"ramo de origem desconhecido: '{from_branch}' em {url}")
        target = branches[from_branch]
        if name in branches:
            if branches[name] == target:
                return
            raise ValueError(f"ramo já existe: '{name}' em {url}")
        branches[name] = target
        self._write_refs(url, branches)
        logger.info("ramo %s criado a partir de %s em %s", name, from_branch, url)

    def resolve(self, url: str, ref: str) -> Version | None:
        """Resolver ``ref`` (``HEAD``, ramo ou prefixo de id) para uma ``Version``.

        Raises:
            ValueError: URL sem histórico, ramo/ref desconhecido ou prefixo ambíguo.
        """
        text = str(ref or "").strip()
        if not text:
            raise ValueError("referência de versão vazia")

        branches = self._read_refs(url)
        if not branches:
            raise ValueError(f"nenhuma versão salva para {url}")

        if text == HEAD_REF:
            tip = branches.get(DEFAULT_BRANCH)
            if tip is None:
                raise ValueError(f"nenhuma versão no ramo '{DEFAULT_BRANCH}' para {url}")
            version = self._load_version(url, tip)
            if version is None:
                raise ValueError(f"commit {tip} de '{DEFAULT_BRANCH}' não encontrado para {url}")
            return version

        if text in branches:
            version = self._load_version(url, branches[text])
            if version is None:
                raise ValueError(f"commit {branches[text]} do ramo '{text}' não encontrado para {url}")
            return version

        return self._resolve_prefix(url, text)

    def _require(self, url: str, ref: str) -> Version:
        """Como ``resolve``, mas garante uma versão em vez de ``None``."""
        version = self.resolve(url, ref)
        if version is None:
            raise ValueError(f"versão desconhecida: '{ref}' em {url}")
        return version

    def _resolve_prefix(self, url: str, prefix: str) -> Version:
        if len(prefix) < MIN_PREFIX_LENGTH:
            raise ValueError(f"referência curta demais: '{prefix}' (mínimo {MIN_PREFIX_LENGTH} caracteres)")
        if not _HEX_DIGITS.issuperset(prefix):
            raise ValueError(f"versão desconhecida: '{prefix}' em {url}")
        objects_dir = self._objects_dir(url)
        matches = sorted(p.stem for p in objects_dir.glob(f"{prefix}*.json")) if objects_dir.is_dir() else []
        if not matches:
            raise ValueError(f"versão desconhecida: '{prefix}' em {url}")
        if len(matches) > 1:
            raise ValueError(f"prefixo ambíguo: '{prefix}' corresponde a {len(matches)} versões em {url}")
        version = self._load_version(url, matches[0])
        if version is None:
            raise ValueError(f"commit {matches[0]} ilegível em {url}")
        return version

    def rollback(self, url: str, ref: str, dest: Path | None = None) -> Path:
        """Restaurar os arquivos de uma versão em ``dest`` e devolver o caminho.

        Blobs ausentes são pulados com aviso; o restante é restaurado.
        """
        version = self._require(url, ref)
        destination = Path(dest) if dest is not None else self._site_dir(url) / f"checkout-{version.id}"
        destination.mkdir(parents=True, exist_ok=True)

        restored = 0
        for rel, digest in sorted(version.files.items()):
            if not _is_safe_relative(rel):
                logger.warning("caminho inválido no commit %s: %s", version.id, rel)
                continue
            blob = self.store.get(digest)
            if blob is None:
                logger.warning("blob %s ausente; %s não restaurado", digest, rel)
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob, target)
            restored += 1

        logger.info("versão %s restaurada em %s (%d arquivo(s))", version.id, destination, restored)
        return destination

    def diff_versions(self, url: str, ref_a: str, ref_b: str) -> DiffReport:
        """Comparar os snapshots de duas versões (ordem corrigida pelo timestamp)."""
        version_a = self._require(url, ref_a)
        version_b = self._require(url, ref_b)

        site_snapshots = snapshots_dir() / url_slug(url)
        path_a = site_snapshots / version_a.snapshot
        path_b = site_snapshots / version_b.snapshot
        for version, path in ((version_a, path_a), (version_b, path_b)):
            if not path.is_file():
                raise ValueError(
                    f"snapshot '{version.snapshot}' da versão {version.id} não encontrado em {site_snapshots}"
                )
        return diff_snapshots(path_a, path_b)
