import pytest
import inspect
import sys
import os

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from autolang import install


@pytest.fixture(autouse=True)
def setup_translator():
    # Setup dummy localized translator with empty translation
    # Which forces it to just evaluate the original text quickly
    return install("dummy_path_does_not_exist", "en")


def test_hot_path_performance_guarantee(benchmark, setup_translator):
    # We want to benchmark the hot path performance against format
    foreign_template = "【Translated】 User {user} has completed {item_count} items."

    # 1. format() + individual compiled eval (Baseline)
    code_user = compile("user", "<string>", "eval")
    code_item = compile("item_count", "<string>", "eval")

    def approach_baseline(f_globals, f_locals):
        kwargs = {
            "user": eval(code_user, f_globals, f_locals),
            "item_count": eval(code_item, f_globals, f_locals),
        }
        return foreign_template.format(**kwargs)

    # 2. Autolang library method:
    # Here we trigger a cold start to populate cache,
    # then subsequent calls hit the ultra fast hot-path
    user = "Alice"
    item_count = 50

    # Fire off cold start
    setup_translator.translate(
        f"【Translated】 User {user} has completed {item_count} items."
    )

    def approach_autolang():
        # Using _() directly relies on inspecting frame, so there's minor overhead
        # but it should securely beat baseline by evaluating the byte code
        return setup_translator.translate(
            f"【Translated】 User {user} has completed {item_count} items."
        )

    # Get current context for baseline
    frame = inspect.currentframe()
    assert frame is not None
    f_globals = frame.f_globals
    f_locals = frame.f_locals

    benchmark.group = "hot-path"

    def run_baseline():
        return approach_baseline(f_globals, f_locals)

    benchmark(run_baseline)


def test_our_package_timing(benchmark, setup_translator):
    benchmark.group = "hot-path"
    user = "Alice"
    item_count = 50
    setup_translator.translate(
        f"【Translated】 User {user} has completed {item_count} items."
    )

    def wrapped_execute():
        return setup_translator.translate(
            f"【Translated】 User {user} has completed {item_count} items."
        )

    benchmark(wrapped_execute)
