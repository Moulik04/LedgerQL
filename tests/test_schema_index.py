from ledgerql.schema_index import get_schema_context


def test_get_schema_context_keeps_table_sections_drops_narrative(tmp_path):
    schema_md = tmp_path / "schema.md"
    schema_md.write_text(
        "# Schema\n"
        "\n"
        "Some intro paragraph that should be dropped.\n"
        "\n"
        "## companies\n"
        "\n"
        "One row per company.\n"
        "\n"
        "| Column | Type |\n"
        "|---|---|\n"
        "| cik | INTEGER |\n"
        "\n"
        "## filings\n"
        "\n"
        "Filing info.\n"
        "\n"
        "## financial_facts\n"
        "\n"
        "Facts info.\n"
        "\n"
        "## Concept views\n"
        "\n"
        "View info.\n"
        "\n"
        "## Some Other Section\n"
        "\n"
        "This should be dropped.\n"
    )
    context = get_schema_context(schema_md)
    assert "cik" in context
    assert "Filing info." in context
    assert "Facts info." in context
    assert "View info." in context
    assert "Some intro paragraph" not in context
    assert "Some Other Section" not in context
    assert "This should be dropped" not in context


def test_get_schema_context_default_path_reads_real_schema():
    context = get_schema_context()
    assert "v_revenue" in context
    assert "v_net_income" in context
    assert "v_total_assets" in context
    assert "v_cash" in context
    assert len(context) > 200
