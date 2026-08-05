"""PKA-160 — an unrecognized VINCTOR_HERMES_UNMAPPED_POLICY must not be silent.

Only the exact value `block` turns blocking on. That exactness is deliberate and
stays (PKA-128's precedent: a typo must never silently turn enforcement on OR
off, in either direction). The defect is that it was also SILENT: an operator
who set `Block`, `BLOCK`, `true`, `1` or `yes` got the permissive default with
no signal anywhere, believed the boundary was blocking unmapped tools, and had
no way to find out short of reading the source.

Every one of those spellings is a plausible thing to write. `true`/`1`/`yes` in
particular are what `_enabled()` accepts for the OTHER env vars in this same
plugin, so an operator generalising from those lands exactly here.

Two surfaces, because they answer different questions:
  - a startup warning tells an operator who is not looking that they are wrong;
  - `doctor` tells an operator who IS looking what is actually in effect, which
    is the question `doctor` exists to answer.
"""

from __future__ import annotations

import io
import json

import pytest

from vinctor_hermes_plugin.boundary import (
    VinctorHermesBoundary,
    unmapped_policy_warning,
)
from vinctor_hermes_plugin.cli import run

# Spellings an operator plausibly writes meaning "block", none of which do.
MISSPELLINGS = ["Block", "BLOCK", "bLoCk", "true", "TRUE", "1", "yes", "on", "blok", "deny"]

# Values that must NOT warn: the two documented spellings, and absence.
RECOGNIZED = ["block", "defer"]


@pytest.mark.parametrize("value", MISSPELLINGS)
def test_unrecognized_value_warns_and_names_what_is_actually_in_effect(value: str) -> None:
    message = unmapped_policy_warning({"VINCTOR_HERMES_UNMAPPED_POLICY": value})
    assert message is not None, f"{value!r} silently fell back to the permissive default"
    # The warning has to carry all three facts or it cannot be acted on: which
    # variable, what the operator wrote, and what is in force instead.
    assert "VINCTOR_HERMES_UNMAPPED_POLICY" in message
    assert value in message
    assert "defer" in message


@pytest.mark.parametrize("value", RECOGNIZED)
def test_recognized_values_are_silent(value: str) -> None:
    assert unmapped_policy_warning({"VINCTOR_HERMES_UNMAPPED_POLICY": value}) is None


@pytest.mark.parametrize("env", [{}, {"VINCTOR_HERMES_UNMAPPED_POLICY": None}])
def test_unset_is_silent(env: dict[str, str | None]) -> None:
    """Not configuring the variable is the documented default, not a mistake."""
    assert unmapped_policy_warning(env) is None


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_and_whitespace_are_silent(value: str) -> None:
    """An empty value is how a shell renders an unset variable through most
    templating and container tooling (`FOO=${BAR}` with BAR unset). Warning on
    it would fire on ordinary deployments that never configured the variable at
    all — noise that trains operators to ignore the warning that matters."""
    assert unmapped_policy_warning({"VINCTOR_HERMES_UNMAPPED_POLICY": value}) is None


def test_the_warning_does_not_change_the_effective_policy() -> None:
    """PKA-128's rule is untouched: only the exact `block` blocks. A typo must
    never silently turn enforcement ON either — warning about `Block` must not
    be a back door to treating it AS `block`."""
    from vinctor_hermes_plugin.boundary import _unmapped_policy

    assert _unmapped_policy({"VINCTOR_HERMES_UNMAPPED_POLICY": "block"}) == "block"
    for value in MISSPELLINGS:
        assert _unmapped_policy({"VINCTOR_HERMES_UNMAPPED_POLICY": value}) == "defer", value


def test_boundary_construction_emits_the_warning_once(capsys: pytest.CaptureFixture[str]) -> None:
    VinctorHermesBoundary.from_env(env={"VINCTOR_HERMES_UNMAPPED_POLICY": "Block"})
    captured = capsys.readouterr()
    assert "VINCTOR_HERMES_UNMAPPED_POLICY" in captured.err
    assert captured.err.count("VINCTOR_HERMES_UNMAPPED_POLICY") == 1
    # stdout is the plugin's data channel; a warning there could corrupt it.
    assert captured.out == ""


def test_boundary_construction_is_silent_for_a_recognized_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    VinctorHermesBoundary.from_env(env={"VINCTOR_HERMES_UNMAPPED_POLICY": "block"})
    assert capsys.readouterr().err == ""


def _doctor(env: dict[str, str | None]) -> tuple[int, dict, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = run(["doctor", "--json"], stdout=stdout, stderr=stderr, env=env)
    return code, json.loads(stdout.getvalue()), stderr.getvalue()


def test_doctor_reports_the_effective_policy_when_unset() -> None:
    _, payload, _ = _doctor({})
    assert payload["unmapped_policy"] == "defer"
    assert payload["unmapped_policy_warning"] is None


def test_doctor_reports_the_effective_policy_when_blocking() -> None:
    _, payload, _ = _doctor({"VINCTOR_HERMES_UNMAPPED_POLICY": "block"})
    assert payload["unmapped_policy"] == "block"
    assert payload["unmapped_policy_warning"] is None


def test_doctor_reports_defer_and_warns_for_a_misspelling() -> None:
    """THE POINT of putting this in doctor. An operator who set `Block` and runs
    `doctor` to check their work must be told the boundary is deferring, not be
    shown a clean report that never mentions the setting they got wrong."""
    code, payload, _ = _doctor({"VINCTOR_HERMES_UNMAPPED_POLICY": "Block"})
    assert payload["unmapped_policy"] == "defer"
    assert payload["unmapped_policy_warning"] is not None
    assert "Block" in payload["unmapped_policy_warning"]
    # A misconfigured optional policy is not an invalid config: `doctor` still
    # exits 0 and reports valid, or CI pipelines gating on it break for a
    # setting that was never required.
    assert code == 0
    assert payload["valid"] is True


def test_doctor_text_output_mentions_the_policy() -> None:
    """The default (non-JSON) rendering is what an operator actually runs."""
    stdout, stderr = io.StringIO(), io.StringIO()
    run(["doctor"], stdout=stdout, stderr=stderr, env={"VINCTOR_HERMES_UNMAPPED_POLICY": "Block"})
    out = stdout.getvalue()
    assert "unmapped_policy" in out
    assert "defer" in out
