import pytest

from nougencode.core.evidence_kernel import EvidenceState
from nougencode.core.obligation_ledger import Obligation, ObligationLedger, VerifierResult


def _ob(i="o1", owner="alice", fx=("f1",), auth=2):
    return Obligation(i, "claim " + i, owner, frozenset(fx), auth)


def _res(i="o1", verdict="pass", auth=2, fx=("f1",)):
    return VerifierResult(i, verdict, auth, frozenset(fx))


def test_empty_ledger_is_unknown_never_verified():
    v = ObligationLedger().verdict()
    assert v.state is EvidenceState.UNKNOWN and not v.open_ids


def test_pass_with_fixtures_and_authority_closes():
    led = ObligationLedger(); led.add(_ob())
    assert led.record(_res()).closed
    assert led.verdict().state is EvidenceState.VERIFIED


@pytest.mark.parametrize("res,why", [
    (_res(verdict="unknown"), "verdict"),
    (_res(fx=()), "fixtures"),
    (_res(auth=1), "authority"),
])
def test_each_missing_condition_blocks_closure(res, why):
    # negative controls: dropping any single condition must leave the obligation open
    led = ObligationLedger(); led.add(_ob())
    out = led.record(res)
    assert not out.closed and why in " ".join(out.reasons)
    assert led.verdict().state is EvidenceState.UNKNOWN


def test_fail_dominates_even_when_others_closed():
    led = ObligationLedger(); led.add(_ob("a")); led.add(_ob("b"))
    led.record(_res("a")); led.record(_res("b", verdict="fail"))
    v = led.verdict()
    assert v.state is EvidenceState.FAILED and v.failed_ids == ("b",)


def test_rerun_can_close_a_previously_failed_obligation():
    led = ObligationLedger(); led.add(_ob())
    led.record(_res(verdict="fail"))
    led.record(_res())
    assert led.verdict().state is EvidenceState.VERIFIED


@pytest.mark.parametrize("owner", ["", "shared", "alice, bob", "alice and bob", "TBD"])
def test_owner_must_be_exactly_one_named_party(owner):
    with pytest.raises(ValueError):
        ObligationLedger().add(_ob(owner=owner))


def test_duplicate_ids_and_unknown_ids_are_refused():
    led = ObligationLedger(); led.add(_ob())
    with pytest.raises(ValueError):
        led.add(_ob())
    with pytest.raises(KeyError):
        led.record(_res("missing"))
    with pytest.raises(ValueError):
        led.record(_res(verdict="maybe"))
