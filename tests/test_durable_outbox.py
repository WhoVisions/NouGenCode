import sqlite3

import pytest

from nougencode.fabric import (
    ChangeContract,
    ChangeFabricEngine,
    FunctionalRequirement,
    ReviewConstraint,
    TestMetadata,
)
from nougencode.fabric.durable_outbox import SQLitePostflightOutbox


def test_sqlite_outbox_survives_reopen_and_preserves_idempotent_chain(tmp_path):
    db_path = tmp_path / "mission-outbox.sqlite3"
    first = SQLitePostflightOutbox(db_path)
    rec1, created = first.append(
        "mission:one",
        "relay",
        {"status": "done", "task": "build"},
        timestamp="2026-09-29T14:00:00-04:00",
    )
    assert created is True
    assert rec1.sequence == 0

    reopened = SQLitePostflightOutbox(db_path)
    duplicate, created = reopened.append(
        "mission:one",
        "relay",
        {"task": "build", "status": "done"},
        timestamp="2026-09-29T18:00:00Z",
    )
    assert created is False
    assert duplicate.record_hash == rec1.record_hash
    assert duplicate.created_at == "2026-09-29T18:00:00.000000Z"

    rec2, created = reopened.append("mission:two", "shards", {"status": "verified"})
    assert created is True
    assert rec2.sequence == 1
    assert rec2.previous_hash == rec1.record_hash
    assert reopened.mark_delivered("mission:one") is True

    after_restart = SQLitePostflightOutbox(db_path)
    assert after_restart.count() == 2
    assert [record.dedup_key for record in after_restart.get_pending()] == ["mission:two"]
    assert after_restart.verify_chain() == (True, None)


def test_sqlite_outbox_detects_persisted_payload_tampering(tmp_path):
    db_path = tmp_path / "mission-outbox.sqlite3"
    outbox = SQLitePostflightOutbox(db_path)
    outbox.append("mission:one", "relay", {"status": "done"})

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE postflight_outbox SET payload_json = ? WHERE dedup_key = ?",
            ('{"status":"changed"}', "mission:one"),
        )

    valid, error = SQLitePostflightOutbox(db_path).verify_chain()
    assert valid is False
    assert error == "Tampered record at index 0: hash verification failed"


def test_sqlite_outbox_requires_persistent_path_and_object_payload(tmp_path):
    with pytest.raises(ValueError, match="persistent database path"):
        SQLitePostflightOutbox(":memory:")

    outbox = SQLitePostflightOutbox(tmp_path / "mission-outbox.sqlite3")
    with pytest.raises(ValueError, match="payload must be an object"):
        outbox.append("mission:one", "relay", ["not", "an", "object"])


def test_change_fabric_accepts_durable_outbox_provider(tmp_path):
    outbox = SQLitePostflightOutbox(tmp_path / "mission-outbox.sqlite3")
    engine = ChangeFabricEngine(outbox=outbox)
    contract = ChangeContract(
        contract_id="CC-DURABLE-001",
        title="Durable postflight proof",
        functional_requirements=(
            FunctionalRequirement(
                req_id="FR-01",
                description="Persist the result record",
                target_artifacts=("src/nougencode/fabric/engine.py",),
                invariants=("DURABLE_OUTBOX",),
                acceptance_tests=("tests/test_durable_outbox.py",),
            ),
        ),
        review_constraints=ReviewConstraint(
            constraint_id="RC-01",
            max_mutation_files=2,
            max_mutation_lines=100,
            required_reviewers=(),
            forbidden_patterns=(),
        ),
    )

    result = engine.execute_change_cycle(
        session_id="session-durable-001",
        contract=contract,
        modified_files=["src/nougencode/fabric/engine.py"],
        lines_changed=10,
        diff_text="+ durable outbox backend",
        test_candidates=(
            TestMetadata(
                test_id="tests/test_durable_outbox.py",
                target_files=("src/nougencode/fabric/engine.py",),
                historical_failure_rate=0.1,
                average_duration_ms=100.0,
            ),
        ),
    )

    restarted = SQLitePostflightOutbox(tmp_path / "mission-outbox.sqlite3")
    assert result.outbox_record.verify_integrity() is True
    assert restarted.count() == 1
    assert restarted.get_pending()[0].record_hash == result.receipt_hash
