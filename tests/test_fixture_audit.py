import json
from pathlib import Path

from scripts.audit_fixture_results import run_audit, write_report


def test_audit_runs_all_default_fixtures() -> None:
    report = run_audit(top_k=5)
    assert len(report["fixtures"]) == 6
    for item in report["fixtures"]:
        assert item["frame_count"] >= 6
        assert item["final_status"] in {"collecting", "pending", "confirmed"}


def test_left_right_has_final_top_candidates() -> None:
    report = run_audit(top_k=5)
    fixtures = {item["name"]: item for item in report["fixtures"]}
    assert fixtures["stream_left_right_single.jsonl"]["final_top_candidates"]


def test_repeat_same_word_confirmed_at_most_once() -> None:
    report = run_audit(top_k=5)
    fixtures = {item["name"]: item for item in report["fixtures"]}
    assert fixtures["stream_repeat_same_word.jsonl"]["confirmed_count"] <= 1


def test_audit_json_output_is_stable(tmp_path: Path) -> None:
    report = run_audit(top_k=3)
    output_md = tmp_path / "fixture_audit.md"
    output_json = tmp_path / "fixture_audit.json"
    write_report(report, output_md, output_json)
    data = json.loads(output_json.read_text(encoding="utf-8"))
    assert len(data["fixtures"]) == 6
    assert "frame_count" in data["fixtures"][0]
    assert "final_status" in data["fixtures"][0]
    assert output_md.exists()

