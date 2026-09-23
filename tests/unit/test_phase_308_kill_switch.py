"""Unit tests for Phase 308: Multi-Sig Governance & Hardware/OS Kill-Switch Engine."""

from __future__ import annotations

import json
import signal
from pathlib import Path

from autonomous_futures.safety.kill_switch import (
    CentralizedSolvencyLedger,
    GovernanceActionType,
    HardwareOSKillSwitchEngine,
    KillSwitchState,
    MultiSigGovernanceEngine,
    Phase308KillSwitchSimulator,
    SignerIdentity,
    verify_phase_308_merkle_dag,
)


def test_multisig_governance_voting_and_quorum() -> None:
    signers = [
        SignerIdentity("signer-1", "pub1", "ROLE_CRO"),
        SignerIdentity("signer-2", "pub2", "ROLE_DEV"),
        SignerIdentity("signer-3", "pub3", "ROLE_SEC"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2, proposal_ttl_ms=60_000)

    proposal = gov.create_proposal(
        action_type=GovernanceActionType.CHANGE_RISK_LIMIT,
        target="max_exposure_cap",
        parameters={"cap_usdt": 50.0},
    )
    assert not gov.is_quorum_satisfied(proposal.proposal_id)

    # Signer 1 votes
    msg1 = (
        f"{proposal.proposal_id}:{proposal.action_type.value}:"
        f"{proposal.target}:1:{json.dumps(proposal.parameters, sort_keys=True)}"
    )
    sig1 = gov.compute_signature("signer-1", msg1)
    ok1 = gov.cast_vote(proposal.proposal_id, "signer-1", 1, sig1)
    assert ok1
    assert not gov.is_quorum_satisfied(proposal.proposal_id)

    # Replay nonce 1 should fail
    fail_replay = gov.cast_vote(proposal.proposal_id, "signer-1", 1, sig1)
    assert not fail_replay

    # Signer 2 votes with valid nonce 1
    msg2 = (
        f"{proposal.proposal_id}:{proposal.action_type.value}:"
        f"{proposal.target}:1:{json.dumps(proposal.parameters, sort_keys=True)}"
    )
    sig2 = gov.compute_signature("signer-2", msg2)
    ok2 = gov.cast_vote(proposal.proposal_id, "signer-2", 1, sig2)
    assert ok2

    # Quorum (2 of 3) reached
    assert gov.is_quorum_satisfied(proposal.proposal_id)


def test_solvency_ledger_exact_zero_drift() -> None:
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    snap0 = ledger.get_snapshot()
    assert snap0.zero_balance_drift
    assert abs(snap0.drift) < 1e-15

    # Record multiple fills and flattenings
    ledger.record_fill("BTCUSDT", "BUY", 0.00006, 95000.0, fee=0.001, realized_pnl=0.05)
    ledger.record_fill("ETHUSDT", "SELL", 0.002, 2750.0, fee=0.002, realized_pnl=-0.02)
    ledger.flatten_position("BTCUSDT", 5.70, fee=0.001)

    snap1 = ledger.get_snapshot()
    assert snap1.zero_balance_drift
    assert abs(snap1.drift) < 1e-15
    assert snap1.unencumbered_cash_verified


def test_kill_switch_three_tiers_and_memory_wipe(tmp_path: Path) -> None:
    signers = [
        SignerIdentity("signer-1", "pub1", "ROLE_CRO"),
        SignerIdentity("signer-2", "pub2", "ROLE_DEV"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    token_file = str(tmp_path / "test_kill.lock")

    engine = HardwareOSKillSwitchEngine(
        governance=gov,
        solvency_ledger=ledger,
        token_file_path=token_file,
    )

    assert engine.state == KillSwitchState.ARMED_NORMAL
    assert not engine.is_memory_wiped
    assert len(engine.open_orders) == 3

    # Level 1: Soft pause
    engine.trigger_level_1_soft_pause("Hawkes runaway test", "HAWKES_BREACH")
    assert engine.state == KillSwitchState.LEVEL_1_SOFT_PAUSE
    assert len(engine.open_orders) == 3  # not mass cancelled yet

    # Level 2: Lockout
    engine.trigger_level_2_lockout("Latency surge test", "LATENCY_SPIKE")
    assert engine.state == KillSwitchState.LEVEL_2_LOCKOUT
    assert len(engine.open_orders) == 0  # all orders cancelled

    # Reset via multi-sig proposal
    prop = gov.create_proposal(GovernanceActionType.RESET_LOCKOUT, "kill_switch", {})
    prop_params = json.dumps(prop.parameters, sort_keys=True)
    msg_s1 = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{prop_params}"
    msg_s2 = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{prop_params}"
    gov.cast_vote(prop.proposal_id, "signer-1", 1, gov.compute_signature("signer-1", msg_s1))
    gov.cast_vote(prop.proposal_id, "signer-2", 1, gov.compute_signature("signer-2", msg_s2))
    assert engine.reset_to_normal(prop.proposal_id)
    assert engine.state == KillSwitchState.ARMED_NORMAL

    # Level 3: Hardware panic & memory wipe
    engine.handle_os_signal(signal.SIGINT if hasattr(signal, "SIGINT") else 2)
    assert engine.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert engine.is_memory_wiped
    assert len(engine.open_positions) == 0
    assert len(engine._secure_memory_store) == 0


def test_file_tripwire_activation(tmp_path: Path) -> None:
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()
    token_file = tmp_path / "emergency.lock"

    engine = HardwareOSKillSwitchEngine(
        governance=gov,
        solvency_ledger=ledger,
        token_file_path=str(token_file),
    )

    # Tripwire not triggered when file does not exist
    assert not engine.check_file_tripwire()
    assert engine.state == KillSwitchState.ARMED_NORMAL

    # Create file token
    token_file.write_text("PANIC")
    assert engine.check_file_tripwire()
    assert engine.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
    assert engine.is_memory_wiped


def test_phase_308_simulation_and_merkle_dag(tmp_path: Path) -> None:
    sim = Phase308KillSwitchSimulator(output_dir=tmp_path)
    res = sim.run_simulation()

    assert res["verified"]
    assert res["status"] == "KILL_SWITCH_VERIFIED"
    assert res["memory_wiped"]
    assert "merkle_root" in res

    # Verify cryptographic Merkle chain
    is_valid = verify_phase_308_merkle_dag(output_dir=tmp_path)
    assert is_valid
