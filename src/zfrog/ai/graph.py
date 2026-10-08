"""Relationship mapping: the entities of cloned pages as a knowledge graph.

Pure AI layer (no engine/browser concerns) so it is testable in isolation.
`build_graph` turns per-page entity lists into nodes (who) and edges (who
relates to whom, and through what); `build_from_entities` optionally asks the
model to name those relations instead of settling for plain co-occurrence.

Never raises for a missing/unavailable AI: `build_from_entities` degrades to the
co-occurrence graph built by `build_graph`.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from zfrog.ai.client import complete_structured, is_available

logger = logging.getLogger(__name__)

# Relation labels produced without a model.
CO_OCCURRENCE = "co_occurrence"
LOCATED_IN = "located_in"

# Relation assumed when the model proposes one without naming it.
DEFAULT_RELATION = "related_to"

# Confidence assumed when a page omits it or sends something unusable.
DEFAULT_CONFIDENCE = 0.8

# Entity types that carry the located_in relation.
LOCATION_TYPE = "location"
ORGANIZATION_TYPE = "organization"

# Noise control: above this many nodes, co-occurrence edges seen on a single
# page (weight 1) are dropped, because in a large graph almost every pair ends
# up "related" by mere presence. Located_in edges are kept — they are evidence
# from the text, not from presence.
MAX_NODES_BEFORE_FILTER = 50

# AI pass budget: how many pages are worth a call, and how much of each text.
MAX_RELATION_PAGES = 20
MAX_RELATION_CHARS = 2000

# A sentence ends on terminal punctuation or on a line break.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?\u2026])[ \t\u00a0]+|\n+")

# Every run of non-alphanumerics becomes a single dash in an id.
_SLUG_SEPARATORS = re.compile(r"[\W_]+")

RELATIONS_PROMPT = (
    "You map relations between entities of a page. "
    "You will receive a list of entities and the page text. "
    "Propose only relations between pairs of entities from the list that the text supports, "
    "using a short snake_case verb for 'relation' "
    "(for example 'works_at', 'belongs_to', 'located_in', 'founded'). "
    "Use the entity names exactly as they appear in the list. "
    "Do not invent relations the text does not support."
)


@dataclass
class Node:
    """One distinct entity in the graph."""

    id: str
    name: str
    type: str
    mentions: int
    sources: list[str]


@dataclass
class Edge:
    """One relationship between two nodes."""

    source: str
    target: str
    relation: str
    weight: int
    sources: list[str]


@dataclass
class KnowledgeGraph:
    """The nodes and edges built from the entities of a set of pages."""

    nodes: list[Node]
    edges: list[Edge]


class ProposedRelation(BaseModel):
    """One relation proposed by the model between two entities of a page."""

    source: str = Field(description="Name of the source entity, as it appears in the list")
    target: str = Field(description="Name of the target entity, as it appears in the list")
    relation: str = Field(default="", description="Relation between them, in snake_case")


class RelationProposalList(BaseModel):
    """The relations proposed by the model for a single page."""

    relations: list[ProposedRelation] = Field(default_factory=list)


@dataclass
class _NodeDraft:
    """Accumulator for one node while pages are being folded together."""

    name: str
    type: str
    confidence: float
    mentions: int = 1
    sources: list[str] = field(default_factory=list)


@dataclass
class _EdgeDraft:
    """Accumulator for one edge while pages are being folded together."""

    weight: int = 1
    sources: list[str] = field(default_factory=list)


def _fold(text: object) -> str:
    """Casefold and strip accents, so ``"Jose"`` and ``"JOSE"`` compare equal."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _slug(text: object) -> str:
    """Slug from folded text: every non-alphanumeric run becomes one dash."""
    return _SLUG_SEPARATORS.sub("-", _fold(text)).strip("-")


def node_id(name: str, type: str = "") -> str:
    """Stable id for an entity name.

    The id depends on the name alone, so the same entity always gets the same
    id: it is the casefolded name with accents stripped and every run of
    non-alphanumerics replaced by a single dash (``"Jose  Silva"`` and
    ``"JOSE silva"`` both become ``"jose-silva"``). ``type`` is only used when
    the name has no alphanumeric character at all; when neither does, the id is
    the empty string and the entity is not graphable.
    """
    return _slug(name) or _slug(type)


def _to_confidence(value: object) -> float:
    """Coerce a page-provided confidence into a float clamped to 0-1."""
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    if not math.isfinite(confidence):
        return DEFAULT_CONFIDENCE
    return max(0.0, min(1.0, confidence))


def _field(payload: object, name: str) -> object:
    """Read ``name`` from a pydantic model, a dict or any duck-typed object."""
    if isinstance(payload, dict):
        return payload.get(name)
    return getattr(payload, name, None)


def _page_url(page: dict) -> str:
    """URL of a page, falling back to its local path."""
    return str(page.get("url") or page.get("path") or "").strip()


def _clean_entity(item: object) -> dict | None:
    """Normalize one page entity into ``{"name", "type", "confidence"}``.

    Returns ``None`` for entries without a usable name.
    """
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip()
        entity_type = str(item.get("type") or "").strip().lower()
        confidence = item.get("confidence")
    else:
        name = str(getattr(item, "name", "") or "").strip()
        entity_type = str(getattr(item, "type", "") or "").strip().lower()
        confidence = getattr(item, "confidence", None)

    if not name:
        return None
    return {
        "name": name,
        "type": entity_type or "other",
        "confidence": _to_confidence(confidence),
    }


def _page_entities(page: dict) -> list[dict]:
    """Normalize the entity list of one page, dropping the unusable entries."""
    items = page.get("entities") or []
    if not isinstance(items, list):
        return []
    cleaned = (_clean_entity(item) for item in items)
    return [item for item in cleaned if item is not None]


def _distinct_ids(entities: list[dict]) -> list[str]:
    """Ids of the entities of one page, deduplicated, in first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for entity in entities:
        key = node_id(entity["name"])
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _named_by_type(entities: list[dict], entity_type: str) -> list[tuple[str, str]]:
    """``(id, name)`` of the entities of one type on a page, deduplicated."""
    found: dict[str, str] = {}
    for entity in entities:
        if entity["type"] != entity_type:
            continue
        key = node_id(entity["name"])
        if key and key not in found:
            found[key] = entity["name"]
    return list(found.items())


def _sentences(text: object) -> list[str]:
    """Fold a page's text and split it into non-empty sentences."""
    return [piece.strip() for piece in _SENTENCE_BREAK.split(_fold(text)) if piece.strip()]


def _mentions_folded(sentence: str, name: str) -> bool:
    """True when a folded ``name`` appears in a folded ``sentence`` as a word."""
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", sentence) is not None


def _same_sentence(sentences: list[str], first: str, second: str) -> bool:
    """True when both names appear inside one and the same sentence."""
    left, right = _fold(first).strip(), _fold(second).strip()
    if not left or not right:
        return False
    return any(_mentions_folded(sentence, left) and _mentions_folded(sentence, right)
               for sentence in sentences)


def _add_node(nodes: dict[str, _NodeDraft], entity: dict, url: str) -> None:
    """Register one entity mention, keeping the spelling of the best-confidence one."""
    key = node_id(entity["name"], entity["type"])
    if not key:
        return
    current = nodes.get(key)
    if current is None:
        nodes[key] = _NodeDraft(
            name=entity["name"],
            type=entity["type"],
            confidence=entity["confidence"],
            sources=[url] if url else [],
        )
        return
    current.mentions += 1
    if url and url not in current.sources:
        current.sources.append(url)
    if entity["confidence"] > current.confidence:
        current.name = entity["name"]
        current.type = entity["type"]
        current.confidence = entity["confidence"]


def _add_edge(
    edges: dict[tuple[str, str, str], _EdgeDraft],
    source: str,
    target: str,
    relation: str,
    url: str,
) -> None:
    """Count one page of evidence for one directed relation."""
    key = (source, target, relation)
    current = edges.get(key)
    if current is None:
        edges[key] = _EdgeDraft(sources=[url] if url else [])
        return
    current.weight += 1
    if url and url not in current.sources:
        current.sources.append(url)


def _add_co_occurrences(
    edges: dict[tuple[str, str, str], _EdgeDraft],
    entities: list[dict],
    url: str,
) -> None:
    """One edge per pair of distinct entities seen together on a page."""
    ids = _distinct_ids(entities)
    for index, source in enumerate(ids):
        for target in ids[index + 1 :]:
            first, second = sorted((source, target))
            _add_edge(edges, first, second, CO_OCCURRENCE, url)


def _add_located_in(
    edges: dict[tuple[str, str, str], _EdgeDraft],
    entities: list[dict],
    text: object,
    url: str,
) -> None:
    """Location -> organization edges when both are named in one sentence."""
    locations = _named_by_type(entities, LOCATION_TYPE)
    organizations = _named_by_type(entities, ORGANIZATION_TYPE)
    if not locations or not organizations:
        return
    sentences = _sentences(text)
    if not sentences:
        return
    for location_id, location_name in locations:
        for organization_id, organization_name in organizations:
            if location_id == organization_id:
                continue
            if _same_sentence(sentences, location_name, organization_name):
                _add_edge(edges, location_id, organization_id, LOCATED_IN, url)


def build_graph(pages: list[dict]) -> KnowledgeGraph:
    """Build a knowledge graph from the entities extracted page by page.

    Args:
        pages: One dict per page, shaped ``{"url": str, "entities": [{"name",
            "type", "confidence"}], "text": str}`` — what ``ai/entities.py``
            returns for a page, plus the page text. A page without entities
            contributes nothing.

    Returns:
        One node per distinct entity (deduplicated by `node_id`), accumulating
        its mentions and the URLs it was seen on; ``co_occurrence`` edges
        between entities seen on the same page (weight = number of pages where
        both appear); and ``located_in`` edges from a location to an
        organization when both are named in the same sentence of the page.
        Above `MAX_NODES_BEFORE_FILTER` nodes, weight-1 co-occurrence edges are
        dropped as noise (almost every pair co-occurs somewhere in a big graph);
        located_in edges are kept, since they come from the text, not presence.
    """
    nodes: dict[str, _NodeDraft] = {}
    edges: dict[tuple[str, str, str], _EdgeDraft] = {}

    for page in pages or []:
        if not isinstance(page, dict):
            continue
        entities = _page_entities(page)
        if not entities:
            continue
        url = _page_url(page)
        for entity in entities:
            _add_node(nodes, entity, url)
        _add_co_occurrences(edges, entities, url)
        _add_located_in(edges, entities, page.get("text"), url)

    graph_nodes = [
        Node(
            id=key,
            name=draft.name,
            type=draft.type,
            mentions=draft.mentions,
            sources=draft.sources,
        )
        for key, draft in nodes.items()
    ]
    graph_edges = [
        Edge(
            source=source,
            target=target,
            relation=relation,
            weight=draft.weight,
            sources=draft.sources,
        )
        for (source, target, relation), draft in edges.items()
    ]
    if len(graph_nodes) > MAX_NODES_BEFORE_FILTER:
        graph_edges = [
            edge
            for edge in graph_edges
            if edge.relation != CO_OCCURRENCE or edge.weight > 1
        ]
    return KnowledgeGraph(nodes=graph_nodes, edges=graph_edges)


def _edge_sort_key(edge: Edge) -> tuple:
    """Strongest first, then a stable order so output never shuffles."""
    return (-edge.weight, edge.relation, edge.source, edge.target)


def find_relationships(graph: KnowledgeGraph, node_id_value: str) -> list[Edge]:
    """Every edge touching a node, strongest first.

    Args:
        graph: Graph to search.
        node_id_value: `node_id` of the entity of interest.

    Returns:
        The touching edges ordered by descending weight, or ``[]`` for an
        unknown id.
    """
    touching = [
        edge
        for edge in graph.edges
        if edge.source == node_id_value or edge.target == node_id_value
    ]
    return sorted(touching, key=_edge_sort_key)


def _plural(count: int, singular: str, plural: str) -> str:
    """``"1 relation"`` / ``"3 relations"``."""
    return f"{count} {singular if count == 1 else plural}"


def describe(graph: KnowledgeGraph, limit: int = 10) -> str:
    """Short Portuguese summary of a graph: sizes, top entities, top relations."""
    if not graph.nodes:
        return "Empty graph: no entities found."
    limit = max(1, limit)
    names = {node.id: node.name for node in graph.nodes}

    most_mentioned = sorted(graph.nodes, key=lambda node: (-node.mentions, node.name.casefold()))
    parts = [
        "Graph with "
        + _plural(len(graph.nodes), "entity", "entities")
        + " and "
        + _plural(len(graph.edges), "relation", "relations")
        + "."
    ]
    parts.append(
        "Most mentioned: "
        + ", ".join(f"{node.name} ({node.mentions})" for node in most_mentioned[:limit])
        + "."
    )
    if graph.edges:
        strongest = sorted(graph.edges, key=_edge_sort_key)[:limit]
        parts.append(
            "Strongest relations: "
            + ", ".join(
                f"{names.get(edge.source, edge.source)} -{edge.relation}-> "
                f"{names.get(edge.target, edge.target)} ({edge.weight})"
                for edge in strongest
            )
            + "."
        )
    else:
        parts.append("No relations between the entities.")
    return " ".join(parts)


def _dot_escape(value: object) -> str:
    """Escape a label for a double-quoted Graphviz string."""
    text = str(value or "")
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", "\\n")


def to_dot(graph: KnowledgeGraph) -> str:
    """Graphviz DOT rendering: nodes labelled with name and type, edges with the relation."""
    lines = ["digraph entidades {", '    rankdir="LR";']
    for node in graph.nodes:
        label = f"{node.name} ({node.type})" if node.type else node.name
        lines.append(f'    "{_dot_escape(node.id)}" [label="{_dot_escape(label)}"];')
    for edge in graph.edges:
        lines.append(
            f'    "{_dot_escape(edge.source)}" -> "{_dot_escape(edge.target)}" '
            f'[label="{_dot_escape(edge.relation)}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def to_json(graph: KnowledgeGraph) -> dict:
    """Plain ``{"nodes": [...], "edges": [...]}`` payload, ready for a client."""
    return {
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "type": node.type,
                "mentions": node.mentions,
                "sources": list(node.sources),
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation,
                "weight": edge.weight,
                "sources": list(edge.sources),
            }
            for edge in graph.edges
        ],
    }


def _relation_messages(names: list[str], text: object) -> list[dict[str, str]]:
    """Prompt asking the model to relate the entities of one page."""
    listing = "\n".join(f"- {name}" for name in sorted(names, key=str.casefold))
    excerpt = str(text or "")[:MAX_RELATION_CHARS]
    return [
        {"role": "system", "content": RELATIONS_PROMPT},
        {"role": "user", "content": f"Entidades:\n{listing}\n\nTexto:\n\n{excerpt}"},
    ]


async def _propose_relations(pages: list[dict], graph: KnowledgeGraph) -> list[dict]:
    """Ask the model for the relations of each page; one entry per accepted proposal."""
    if not is_available():
        logger.info("AI unavailable: co-occurrence-only graph")
        return []

    known = {node.id: node.name for node in graph.nodes}
    proposals: list[dict] = []
    for page in (pages or [])[:MAX_RELATION_PAGES]:
        if not isinstance(page, dict):
            continue
        entities = _page_entities(page)
        ids = _distinct_ids(entities)
        if len(ids) < 2:
            continue
        names = [known[key] for key in ids if key in known]
        if len(names) < 2:
            continue
        result = await complete_structured(
            messages=_relation_messages(names, page.get("text")),
            response_model=RelationProposalList,
            temperature=0.0,
        )
        url = _page_url(page)
        proposals.extend(_accepted_proposals(result, ids, url))
    return proposals


def _accepted_proposals(result: object, page_ids: list[str], url: str) -> list[dict]:
    """Keep only the proposals whose both entities are on the page they came from."""
    items = _field(result, "relations")
    if not isinstance(items, (list, tuple)):
        return []
    allowed = set(page_ids)
    accepted: list[dict] = []
    for item in items:
        source = node_id(str(_field(item, "source") or ""))
        target = node_id(str(_field(item, "target") or ""))
        if not source or not target or source == target:
            continue
        if source not in allowed or target not in allowed:
            continue
        relation = str(_field(item, "relation") or "").strip() or DEFAULT_RELATION
        accepted.append({"source": source, "target": target, "relation": relation, "url": url})
    return accepted


def _merge_proposals(graph: KnowledgeGraph, proposals: list[dict]) -> KnowledgeGraph:
    """Add the proposed relations to the graph, counting one page of evidence each."""
    edges: dict[tuple[str, str, str], _EdgeDraft] = {
        (edge.source, edge.target, edge.relation): _EdgeDraft(
            weight=edge.weight, sources=list(edge.sources)
        )
        for edge in graph.edges
    }
    for proposal in proposals:
        _add_edge(
            edges,
            proposal["source"],
            proposal["target"],
            proposal["relation"],
            proposal["url"],
        )
    return KnowledgeGraph(
        nodes=list(graph.nodes),
        edges=[
            Edge(
                source=source,
                target=target,
                relation=relation,
                weight=draft.weight,
                sources=draft.sources,
            )
            for (source, target, relation), draft in edges.items()
        ],
    )


async def build_from_entities(pages: list[dict]) -> KnowledgeGraph:
    """Build a graph, letting the model name the relations it can see.

    The co-occurrence graph is always built first; the AI pass only *adds*
    named relations between entities that share a page. Any failure — no model,
    no JSON, a broken reply — leaves that co-occurrence graph untouched, so this
    never raises.

    Args:
        pages: Same shape as `build_graph`.

    Returns:
        The graph with the proposed relations added, or the plain
        co-occurrence graph when the model could not be used.
    """
    graph = build_graph(pages)
    if len(graph.nodes) < 2:
        return graph
    try:
        proposals = await _propose_relations(pages, graph)
    except Exception as exc:
        logger.warning("AI relation pass failed (%s); keeping the co-occurrence graph", exc)
        return graph
    if not proposals:
        return graph
    return _merge_proposals(graph, proposals)
