import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from autolang.cli.static_analysis import suggest_placeholder_candidates


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
