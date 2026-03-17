from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from autolang import TransparentTranslator, install


class NullWriter:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None


_NULL_WRITER = NullWriter()


@dataclass(slots=True)
class BenchmarkContext:
    translator: TransparentTranslator
    report_id: int
    user: str
    name_width: int
    city: str
    total: float
    currency: str
    ordered_at: datetime
    success_rate: float
    attempts: int
    expected_output: str


async def context():
    translator = install(str(Path(__file__).resolve().parent / "locales"), "es")
    case = BenchmarkContext(
        translator=translator,
        report_id=271828,
        user="alice-admin",
        name_width=18,
        city="sao paulo",
        total=8642.75,
        currency="USD",
        ordered_at=datetime(2026, 3, 11, 19, 42, 8),
        success_rate=0.8735,
        attempts=37,
        expected_output="",
    )
    case.expected_output = _render_standard_print(case)

    cold_output = _render_autolang_translation(case)
    if cold_output != case.expected_output:
        raise AssertionError(
            "Autolang benchmark output mismatch during warmup.\n"
            f"expected={case.expected_output!r}\n"
            f"actual={cold_output!r}"
        )

    hot_output = _render_autolang_translation(case)
    if hot_output != case.expected_output:
        raise AssertionError(
            "Autolang benchmark output mismatch after cache warmup.\n"
            f"expected={case.expected_output!r}\n"
            f"actual={hot_output!r}"
        )

    yield case


def _render_standard_print(case: BenchmarkContext) -> str:
    fmt = case.translator.format
    report_id = case.report_id
    user = case.user
    name_width = case.name_width
    city = case.city
    total = case.total
    currency = case.currency
    ordered_at = case.ordered_at
    success_rate = case.success_rate
    attempts = case.attempts
    medium_format = "medium"
    return (
        f"Informe {report_id:06d}: usuario {user!r:>{name_width}} "
        f"en {city.title()} gasto {fmt.currency(total, currency)} "
        f"el {fmt.datetime(ordered_at, format=medium_format)} "
        f"con tasa de exito {success_rate:.2%} tras {attempts} intentos."
    )


def _render_autolang_translation(case: BenchmarkContext) -> str:
    report_id = case.report_id
    user = case.user
    name_width = case.name_width
    city = case.city
    total = case.total
    currency = case.currency
    ordered_at = case.ordered_at
    success_rate = case.success_rate
    attempts = case.attempts
    medium_format = "medium"
    fmt = case.translator.format
    return case.translator.translate(
        f"Report {report_id:06d}: user {user!r:>{name_width}} "
        f"in {city.title()} spent {fmt.currency(total, currency)} "
        f"on {fmt.datetime(ordered_at, format=medium_format)} "
        f"with success rate {success_rate:.2%} after {attempts} attempts."
    )


async def benchmark_standard_print(context):
    print(_render_standard_print(context), file=_NULL_WRITER)
    return 1


async def benchmark_autolang_translation(context):
    print(_render_autolang_translation(context), file=_NULL_WRITER)
    return 1


"""
Average CPS (Calls Per Second) per Function:

|                                |      CPS |
|:-------------------------------|---------:|
| benchmark_autolang_translation |  5760.08 |
| benchmark_standard_print       | 12329.1  |
"""