import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from autolang.toml_io import load_string_table, write_string_table


def test_write_string_table_uses_triple_quoted_values(tmp_path):
    path = tmp_path / "es.toml"

    write_string_table(str(path), {"Hello {name}": "Hola {name}"})

    assert path.read_text(encoding="utf-8") == (
        '"Hello {name}" = """\n'
        'Hola {name}"""\n'
        "# --------------------\n"
    )


def test_write_string_table_preserves_multiline_values_without_literal_newline_escape(
    tmp_path,
):
    path = tmp_path / "cue.toml"
    value = "Location: app.py:1\nDefinition: name = 'Alice'"

    write_string_table(str(path), {"Hello {name}": value})

    content = path.read_text(encoding="utf-8")

    assert "\\n" not in content
    assert '"""' in content
    assert (
        "Location: app.py:1\nDefinition: name = 'Alice'\"\"\"\n"
        "# --------------------\n"
    ) in content
    assert load_string_table(str(path)) == {"Hello {name}": value}
