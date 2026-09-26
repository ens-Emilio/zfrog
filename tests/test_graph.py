"""Tests for entity relationship mapping (no real model required)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from zfrog.ai import graph as graph_mod
from zfrog.ai.graph import (
    KnowledgeGraph,
    build_from_entities,
    build_graph,
    describe,
    find_relationships,
    node_id,
    to_dot,
    to_json,
)


def _page(url: str, entities: list[tuple[str, str]], text: str = "") -> dict:
    """A page in the shape ai/entities.py produces, plus its text."""
    return {
        "url": url,
        "entities": [{"name": name, "type": type_, "confidence": 0.8} for name, type_ in entities],
        "text": text,
    }


def _edge(graph: KnowledgeGraph, source: str, target: str, relation: str):
    """The edge between two ids with one relation, or None."""
    for edge in graph.edges:
        if (edge.source, edge.target, edge.relation) == (source, target, relation):
            return edge
    return None


def _undirected(graph: KnowledgeGraph, first: str, second: str, relation: str):
    """The edge between two ids in either direction, or None."""
    return _edge(graph, first, second, relation) or _edge(graph, second, first, relation)


# ── node_id ───────────────────────────────────────────────────────────────


def test_node_id_is_stable_across_case_accents_and_punctuation():
    ids = {
        node_id("José Silva"),
        node_id("jose silva"),
        node_id("JOSÉ  SILVA"),
        node_id("José Silva!"),
        node_id("josé   silva"),
    }

    assert ids == {"jose-silva"}


def test_node_id_ignores_the_type_but_uses_it_for_an_unusable_name():
    assert node_id("Acme", "organization") == node_id("acme", "person") == "acme"
    assert node_id("São Paulo") == "sao-paulo"
    assert node_id("München") == "munchen"
    assert node_id("!!!", "location") == "location"
    assert node_id("!!!") == ""


# ── build_graph ───────────────────────────────────────────────────────────


def test_shared_entity_across_pages_is_one_node_with_two_sources():
    graph = build_graph(
        [
            _page(
                "https://a.test/1",
                [("Acme", "organization"), ("Ana", "person")],
                "Ana trabalha na Acme.",
            ),
            _page("https://a.test/2", [("Acme", "organization")], "Acme abriu vagas."),
        ]
    )

    acme = [node for node in graph.nodes if node.id == "acme"]
    assert len(acme) == 1
    assert acme[0].name == "Acme"
    assert acme[0].type == "organization"
    assert acme[0].mentions == 2
    assert acme[0].sources == ["https://a.test/1", "https://a.test/2"]
    assert len(graph.nodes) == 2


def test_entity_spelled_differently_on_each_page_is_still_one_node():
    graph = build_graph(
        [
            _page("https://a.test/1", [("José Silva", "person")]),
            _page("https://a.test/2", [("JOSE SILVA", "person")]),
        ]
    )

    assert [node.id for node in graph.nodes] == ["jose-silva"]
    assert graph.nodes[0].mentions == 2
    assert graph.nodes[0].sources == ["https://a.test/1", "https://a.test/2"]


def test_co_occurrence_weight_counts_the_pages_where_both_appear():
    graph = build_graph(
        [
            _page("https://a.test/1", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/2", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/3", [("Ana", "person"), ("Beta", "organization")]),
        ]
    )

    pair = _undirected(graph, "ana", "acme", "co_occurrence")
    assert pair is not None
    assert pair.weight == 2
    assert pair.sources == ["https://a.test/1", "https://a.test/2"]
    other = _undirected(graph, "ana", "beta", "co_occurrence")
    assert other is not None and other.weight == 1
    assert len(graph.edges) == 2


def test_entity_alone_on_a_page_gets_a_node_and_no_edge():
    graph = build_graph([_page("https://a.test/1", [("Zeta", "product")], "O Zeta foi lançado.")])

    assert len(graph.nodes) == 1
    assert graph.nodes[0].id == "zeta"
    assert graph.nodes[0].mentions == 1
    assert graph.nodes[0].sources == ["https://a.test/1"]
    assert graph.edges == []


def test_located_in_is_created_for_a_location_in_the_same_sentence():
    graph = build_graph(
        [
            _page(
                "https://a.test/1",
                [("Acme", "organization"), ("São Paulo", "location")],
                "A Acme fica em São Paulo. O time cresceu muito no ano passado.",
            )
        ]
    )

    located = _edge(graph, "sao-paulo", "acme", "located_in")
    assert located is not None
    assert located.weight == 1
    assert located.sources == ["https://a.test/1"]
    assert located.source == "sao-paulo" and located.target == "acme"


def test_located_in_is_not_created_across_sentences():
    graph = build_graph(
        [
            _page(
                "https://a.test/1",
                [("Acme", "organization"), ("São Paulo", "location")],
                "A Acme abriu vagas. O escritório de São Paulo contratou duas pessoas.",
            )
        ]
    )

    assert [edge.relation for edge in graph.edges] == ["co_occurrence"]
    assert _undirected(graph, "acme", "sao-paulo", "co_occurrence") is not None


def test_located_in_ignores_a_page_without_text():
    graph = build_graph(
        [_page("https://a.test/1", [("Acme", "organization"), ("São Paulo", "location")])]
    )

    assert [edge.relation for edge in graph.edges] == ["co_occurrence"]


def test_located_in_needs_the_full_name_not_a_fragment():
    graph = build_graph(
        [
            _page(
                "https://a.test/1",
                [("Acme", "organization"), ("São Paulo", "location")],
                "A Acme contratou o Paulão como diretor.",
            )
        ]
    )

    assert [edge.relation for edge in graph.edges] == ["co_occurrence"]


def test_empty_input_and_pages_without_entities_produce_an_empty_graph():
    assert build_graph([]) == KnowledgeGraph(nodes=[], edges=[])
    assert build_graph([_page("https://a.test/1", [], "Acme em São Paulo.")]) == KnowledgeGraph(
        nodes=[], edges=[]
    )


def test_weight_one_co_occurrence_edges_are_dropped_only_in_large_graphs():
    entities = [(f"Entidade {index}", "other") for index in range(51)]

    large = build_graph([_page("https://a.test/1", entities)])
    assert len(large.nodes) == 51
    assert large.edges == []

    small = build_graph([_page("https://a.test/1", entities[:10])])
    assert len(small.nodes) == 10
    assert len(small.edges) == 45

    reinforced = build_graph(
        [
            _page("https://a.test/1", entities + [("Par A", "other"), ("Par B", "other")]),
            _page("https://a.test/2", [("Par A", "other"), ("Par B", "other")]),
        ]
    )
    assert len(reinforced.nodes) == 53
    assert len(reinforced.edges) == 1
    assert reinforced.edges[0].weight == 2


# ── find_relationships ────────────────────────────────────────────────────


def test_find_relationships_returns_touching_edges_strongest_first():
    graph = build_graph(
        [
            _page("https://a.test/1", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/2", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/3", [("Ana", "person"), ("Beta", "organization")]),
        ]
    )

    edges = find_relationships(graph, "ana")

    assert [edge.weight for edge in edges] == [2, 1]
    assert all(edge.source == "ana" or edge.target == "ana" for edge in edges)
    touching = {edge.source for edge in edges} | {edge.target for edge in edges}
    assert touching == {"ana", "acme", "beta"}
    assert find_relationships(graph, "inexistente") == []


# ── describe ──────────────────────────────────────────────────────────────


def test_describe_mentions_the_counts_and_the_top_entities():
    graph = build_graph(
        [
            _page("https://a.test/1", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/2", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/3", [("Ana", "person"), ("Beta", "organization")]),
        ]
    )

    summary = describe(graph)

    assert "3 entidades" in summary
    assert "2 relações" in summary
    assert "Ana (3)" in summary
    assert "co_occurrence" in summary


def test_describe_handles_the_singular_and_the_empty_graph():
    single = build_graph([_page("https://a.test/1", [("Zeta", "product")])])

    assert "1 entidade" in describe(single)
    assert "0 relações" in describe(single)
    empty = describe(KnowledgeGraph(nodes=[], edges=[]))
    assert empty == "Grafo vazio: nenhuma entidade encontrada."


# ── to_dot / to_json ──────────────────────────────────────────────────────


def test_to_dot_labels_every_node_and_edge_and_escapes_quotes():
    graph = build_graph(
        [
            _page(
                "https://a.test/1",
                [('He said "hi"', "person"), ("Acme", "organization"), ("Back\\slash", "other")],
                'He said "hi" na Acme, junto com Back\\slash.',
            )
        ]
    )

    dot = to_dot(graph)

    assert dot.startswith("digraph")
    assert dot.rstrip().endswith("}")
    assert '"he-said-hi"' in dot
    assert 'label="He said \\"hi\\" (person)"' in dot
    assert 'label="Acme (organization)"' in dot
    assert 'label="Back\\\\slash (other)"' in dot
    for edge in graph.edges:
        assert f'"{edge.source}" -> "{edge.target}" [label="{edge.relation}"];' in dot
    assert len(graph.edges) == 3


def test_to_json_is_client_ready():
    graph = build_graph(
        [
            _page("https://a.test/1", [("Ana", "person"), ("Acme", "organization")]),
            _page("https://a.test/2", [("Ana", "person"), ("Acme", "organization")]),
        ]
    )

    payload = to_json(graph)

    assert payload["nodes"][0] == {
        "id": "ana",
        "name": "Ana",
        "type": "person",
        "mentions": 2,
        "sources": ["https://a.test/1", "https://a.test/2"],
    }
    assert payload["edges"] == [
        {
            "source": "acme",
            "target": "ana",
            "relation": "co_occurrence",
            "weight": 2,
            "sources": ["https://a.test/1", "https://a.test/2"],
        }
    ]


# ── build_from_entities ───────────────────────────────────────────────────


class _Relation(BaseModel):
    """Stand-in for the schema the model is asked to fill."""

    source: str
    target: str
    relation: str = ""


class _RelationList(BaseModel):
    relations: list[_Relation] = Field(default_factory=list)


PAGES = [
    _page(
        "https://a.test/1",
        [("Ana", "person"), ("Acme", "organization")],
        "Ana trabalha na Acme desde 2020.",
    ),
    _page("https://a.test/2", [("Ana", "person"), ("Beta", "organization")], "Ana deixou a Beta."),
]


async def test_ai_failure_still_returns_the_co_occurrence_graph(monkeypatch):
    async def broken(messages, response_model, **kwargs):
        raise RuntimeError("modelo fora do ar")

    monkeypatch.setattr(graph_mod, "is_available", lambda: True)
    monkeypatch.setattr(graph_mod, "complete_structured", broken)

    graph = await build_from_entities(PAGES)

    assert graph == build_graph(PAGES)
    assert len(graph.nodes) == 3
    assert _undirected(graph, "ana", "acme", "co_occurrence") is not None


async def test_ai_relations_are_added_on_top_of_co_occurrence(monkeypatch):
    async def fake(messages, response_model, **kwargs):
        assert response_model is graph_mod.RelationProposalList
        assert "Ana" in messages[-1]["content"]
        return _RelationList(
            relations=[
                _Relation(source="Ana", target="Acme", relation="trabalha_em"),
                _Relation(source="Ana", target="Fantasma", relation="conhece"),
                _Relation(source="Acme", target="Acme", relation="funde_se"),
                _Relation(source="Beta", target="Ana", relation=""),
            ]
        )

    monkeypatch.setattr(graph_mod, "is_available", lambda: True)
    monkeypatch.setattr(graph_mod, "complete_structured", fake)

    graph = await build_from_entities(PAGES)

    assert _edge(graph, "ana", "acme", "trabalha_em") is not None
    assert _edge(graph, "beta", "ana", graph_mod.DEFAULT_RELATION) is not None
    assert _undirected(graph, "ana", "acme", "co_occurrence") is not None
    assert not any("fantasma" in (edge.source, edge.target) for edge in graph.edges)
    assert not any(edge.source == edge.target for edge in graph.edges)
    assert len(graph.nodes) == 3


async def test_ai_is_not_called_when_there_is_nothing_to_relate(monkeypatch):
    async def forbidden(messages, response_model, **kwargs):
        raise AssertionError("the AI must not be called")

    monkeypatch.setattr(graph_mod, "is_available", lambda: True)
    monkeypatch.setattr(graph_mod, "complete_structured", forbidden)

    pages = [_page("https://a.test/1", [("Zeta", "product")])]

    assert await build_from_entities(pages) == build_graph(pages)


async def test_unavailable_ai_returns_the_co_occurrence_graph(monkeypatch):
    async def forbidden(messages, response_model, **kwargs):
        raise AssertionError("the AI must not be called")

    monkeypatch.setattr(graph_mod, "is_available", lambda: False)
    monkeypatch.setattr(graph_mod, "complete_structured", forbidden)

    graph = await build_from_entities(PAGES)

    assert graph == build_graph(PAGES)
