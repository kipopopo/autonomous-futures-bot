from __future__ import annotations

import hashlib
import json
from pathlib import Path


def test_aug_sep_holdout_index_records_consumed_link_and_xrp_validations() -> None:
    repo = Path(__file__).resolve().parents[2]
    index_path = repo / "research/qualification-holdout-2026-08-2026-09/holdout-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    consumed = index["consumption"]["consumed_validation"]
    assert index["status"] == "partially_consumed"
    assert index["candidate_tuning_used"] is False
    assert index["qualification_decision_authority"] is False
    assert [item["symbol"] for item in consumed] == ["LINKUSDT", "XRPUSDT", "SUIUSDT"]

    for evidence in consumed:
        report_path = repo / evidence["report_path"]
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)

        assert evidence["family"] == report["family"] == "MACRO_SCALPER"
        assert evidence["symbol"] == report["symbol"]
        assert evidence["decision"] == report["decision"] == "REJECTED"
        assert evidence["execution_authority"] is report["execution_authority"] is False
        assert evidence["report_sha256"] == hashlib.sha256(report_bytes).hexdigest()
        assert evidence["report_hash"] == report["report_hash"]
        assert evidence["interval"] == report["candidate_validation"]["validation_interval"]
        assert evidence["shared_context_consumed"] == [{"symbol": "BTCUSDT", "timeframe": "1h"}]

    for entry in consumed[1:]:
        rep = json.loads((repo / entry["report_path"]).read_bytes())
        val = rep["candidate_validation"]
        assert val["holdout_context_status"] == "PARTIALLY_CONSUMED_SHARED_BTC_CONTEXT"
        assert val["policy_binding"]["starting_equity"] == "4224.09882354"
        assert val["policy_binding"]["trade_risk_pct"] == "0.5"
        assert val["policy_binding"]["daily_loss_pct"] == "5"

    portfolio_consumed = index["consumption"]["consumed_portfolio_validation"]
    assert len(portfolio_consumed) == 1
    p_entry = portfolio_consumed[0]
    assert p_entry["portfolio_id"] == "macro-scalper-uninspected-3sym-medium-frequency-v1"
    assert p_entry["family"] == "MACRO_SCALPER"
    assert p_entry["scope"] == "SHARED_WALLET_PORTFOLIO"
    assert p_entry["symbols"] == ["AVAXUSDT", "ETHUSDT", "SOLUSDT"]
    assert p_entry["member_count"] == 6
    assert p_entry["decision"] == "QUALIFIED"
    assert p_entry["execution_authority"] is False
    assert p_entry["shared_context_consumed"] == [{"symbol": "BTCUSDT", "timeframe": "1h"}]

    sel_bytes = (repo / p_entry["selection_manifest_path"]).read_bytes()
    sel = json.loads(sel_bytes)
    assert p_entry["selection_manifest_sha256"] == hashlib.sha256(sel_bytes).hexdigest()
    assert p_entry["selection_hash"] == sel["selection_hash"]

    dev_bytes = (repo / p_entry["development_report_path"]).read_bytes()
    dev_rep = json.loads(dev_bytes)
    assert p_entry["development_report_sha256"] == hashlib.sha256(dev_bytes).hexdigest()
    assert p_entry["development_report_hash"] == dev_rep["report_hash"]

    holdout_bytes = (repo / p_entry["report_path"]).read_bytes()
    holdout_rep = json.loads(holdout_bytes)
    assert p_entry["report_sha256"] == hashlib.sha256(holdout_bytes).hexdigest()
    assert p_entry["report_hash"] == holdout_rep["report_hash"]
    assert holdout_rep["decision"] == "QUALIFIED"
    assert holdout_rep["execution_authority"] is False
    assert all(holdout_rep["gates"].values())

    assert index["consumption"]["uninspected_target_symbols"] == [
        "DOGEUSDT",
        "BNBUSDT",
        "NEARUSDT",
        "APTUSDT",
        "ADAUSDT",
    ]
    for consumed_sym in ("LINKUSDT", "XRPUSDT", "SUIUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT"):
        assert consumed_sym not in index["consumption"]["uninspected_target_symbols"]
