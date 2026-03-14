import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from autolang.cli.static_analysis import analyze_static_cues, suggest_placeholder_candidates


def test_suggest_placeholder_candidates_is_greedy_when_type_is_unknown():
    candidates, recommended, confidence, notes = suggest_placeholder_candidates(
        expression="value",
        placeholder="{value}",
        annotation=None,
        definition_source="value = source.value",
        has_conversion=False,
        has_format_spec=False,
    )

    assert candidates == (
        "{value}",
        "{fmt.date(value)}",
        "{fmt.time(value)}",
        "{fmt.datetime(value)}",
        "{fmt.decimal(value)}",
        "{fmt.number(value)}",
        '{fmt.currency(value, "USD")}',
        "{fmt.compact_decimal(value)}",
        '{fmt.compact_currency(value, "USD")}',
        "{fmt.compact_decimal(value * 1000)}",
        "{fmt.compact_decimal(value * 1000000)}",
        "{fmt.compact_decimal(value * 1000000000)}",
        '{fmt.compact_currency(value * 1000, "USD")}',
        '{fmt.compact_currency(value * 1000000, "USD")}',
        '{fmt.compact_currency(value * 1000000000, "USD")}',
        "{fmt.percent(value)}",
        "{fmt.percent(value / 100)}",
        "{fmt.timedelta(value)}",
    )
    assert recommended == "{value}"
    assert confidence == "low"
    assert any("greedy" in note for note in notes)


def test_suggest_placeholder_candidates_prunes_using_exact_type_information():
    candidates, recommended, confidence, notes = suggest_placeholder_candidates(
        expression="created_at",
        placeholder="{created_at}",
        annotation="datetime",
        definition_source="created_at = created_at",
        has_conversion=False,
        has_format_spec=False,
    )

    assert candidates == (
        "{created_at}",
        "{fmt.date(created_at)}",
        "{fmt.time(created_at)}",
        "{fmt.datetime(created_at)}",
    )
    assert recommended == "{fmt.datetime(created_at)}"
    assert confidence == "high"
    assert any("datetime-like" in note for note in notes)


def test_suggest_placeholder_candidates_keeps_plain_text_only_for_strings():
    candidates, recommended, confidence, notes = suggest_placeholder_candidates(
        expression="name",
        placeholder="{name}",
        annotation="str",
        definition_source="name = 'Alice'",
        has_conversion=False,
        has_format_spec=False,
    )

    assert candidates == ("{name}",)
    assert recommended == "{name}"
    assert confidence == "low"
    assert any("text-like" in note for note in notes)


def test_suggest_placeholder_candidates_treats_currency_type_as_number():
    candidates, recommended, confidence, notes = suggest_placeholder_candidates(
        expression="amount",
        placeholder="{amount}",
        annotation="Decimal",
        definition_source="amount = amount",
        has_conversion=False,
        has_format_spec=False,
    )

    assert candidates == (
        "{amount}",
        "{fmt.decimal(amount)}",
        "{fmt.number(amount)}",
        '{fmt.currency(amount, "USD")}',
        "{fmt.compact_decimal(amount)}",
        '{fmt.compact_currency(amount, "USD")}',
        "{fmt.compact_decimal(amount * 1000)}",
        "{fmt.compact_decimal(amount * 1000000)}",
        "{fmt.compact_decimal(amount * 1000000000)}",
        '{fmt.compact_currency(amount * 1000, "USD")}',
        '{fmt.compact_currency(amount * 1000000, "USD")}',
        '{fmt.compact_currency(amount * 1000000000, "USD")}',
        "{fmt.percent(amount)}",
        "{fmt.percent(amount / 100)}",
        "{fmt.timedelta(amount)}",
    )
    assert recommended == "{amount}"
    assert confidence == "low"
    assert any("numeric" in note for note in notes)


# ---------------------------------------------------------------------------
# Type inference tests (via analyze_static_cues end-to-end)
# ---------------------------------------------------------------------------


def _extract_cue_text(source: str) -> str:
    """Helper: analyze source and return the cue_text of the first template."""
    cues = analyze_static_cues(source)
    assert cues, "Expected at least one template cue"
    return cues[0].cue_text


def test_infers_len_expression_as_number():
    source = (
        "from autolang import tt\n"
        "items = [1, 2, 3]\n"
        "tt(f'{len(items)} items')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "numeric" in cue_text.lower() or "number" in cue_text.lower(), cue_text


def test_infers_variable_from_len_as_number():
    source = (
        "from autolang import tt\n"
        "items = [1, 2, 3]\n"
        "count = len(items)\n"
        "tt(f'{count} items')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "numeric" in cue_text.lower() or "number" in cue_text.lower(), cue_text


def test_infers_function_return_annotation():
    source = (
        "from autolang import tt\n"
        "def get_count() -> int:\n"
        "    return 42\n"
        "count = get_count()\n"
        "tt(f'{count} items')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "numeric" in cue_text.lower() or "number" in cue_text.lower(), cue_text


def test_unpacked_tuple_return_propagates_element_annotation():
    source = (
        "from autolang import tt\n"
        "def load_counts() -> tuple[str, int]:\n"
        "    return 'done', 3\n"
        "label, count = load_counts()\n"
        "tt(f'{count} items')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "annotation: int" in cue_text.lower(), cue_text
    assert "numeric" in cue_text.lower() or "number" in cue_text.lower(), cue_text


def test_starred_unpack_preserves_numeric_annotation_for_leading_target():
    source = (
        "from autolang import tt\n"
        "def load_values() -> tuple[int, str, bool]:\n"
        "    return 3, 'ok', True\n"
        "count, *rest = load_values()\n"
        "tt(f'{count} items')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "annotation: int" in cue_text.lower(), cue_text
    assert "numeric" in cue_text.lower() or "number" in cue_text.lower(), cue_text


def test_starred_unpack_records_tuple_slice_annotation():
    source = (
        "from autolang import tt\n"
        "def load_values() -> tuple[int, str, bool]:\n"
        "    return 3, 'ok', True\n"
        "count, *rest = load_values()\n"
        "tt(f'{rest}')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "annotation: list[str | bool]" in cue_text.lower(), cue_text


def test_starred_unpack_preserves_numeric_annotation_for_trailing_target():
    source = (
        "from autolang import tt\n"
        "def load_values() -> tuple[str, bool, int]:\n"
        "    return 'ok', True, 3\n"
        "*rest, count = load_values()\n"
        "tt(f'{count} items')\n"
    )
    cue_text = _extract_cue_text(source)
    assert "annotation: int" in cue_text.lower(), cue_text
    assert "numeric" in cue_text.lower() or "number" in cue_text.lower(), cue_text
