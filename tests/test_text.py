"""Tests for the shared HTML text extraction."""

from zfrog.utils.text import extract_main_text, extract_text

PAGE = """<!DOCTYPE html>
<html><head><title>T</title><style>body{color:red}</style></head>
<body>
  <nav>Início Sobre</nav>
  <h1>Relatório anual</h1>
  <p>O faturamento cresceu.</p>
  <ul><li>Item um</li><li>Item dois</li></ul>
  <table><tr><td>Preço</td><td>R$ 90</td></tr></table>
  <script>var x = 'texto que nao deve aparecer';</script>
  <noscript>Ative o JavaScript</noscript>
  <footer>Rodapé 2026</footer>
</body></html>"""


def test_extract_text_keeps_lists_and_tables():
    """Regression: trafilatura silently dropped a whole <ul>, so a search for
    text that was on the page found nothing."""
    text = extract_text(PAGE)

    assert "Item um" in text
    assert "Item dois" in text
    assert "R$ 90" in text
    assert "Preço" in text
    assert "Relatório anual" in text
    assert "O faturamento cresceu." in text


def test_extract_text_drops_non_content():
    text = extract_text(PAGE)

    assert "texto que nao deve aparecer" not in text
    assert "Ative o JavaScript" not in text
    assert "color:red" not in text


def test_extract_text_handles_degenerate_input():
    assert extract_text("") == ""
    assert extract_text("   ") == ""
    assert extract_text("sem html") == "sem html"


def test_extract_main_text_falls_back_and_stays_non_empty():
    """Article extraction may prune boilerplate, but must never return nothing."""
    text = extract_main_text(PAGE)

    assert "Relatório anual" in text
    assert "texto que nao deve aparecer" not in text
    assert extract_main_text("") == ""
    assert extract_main_text("sem html") == "sem html"
