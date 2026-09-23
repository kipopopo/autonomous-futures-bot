"""Phase 309 Adversarial Challenger 2 Test Suite.

Adversarially challenges:
1. Multi-Sig Governance (2-of-3 quorum, anti-replay nonces, TTL expiration, double-vote rejection)
2. Hardware/OS Kill Switch (3 tiers, signal trapping, emergency_kill.lock file tripwire)
3. Cryptographic Merkle DAG Chain (upstream parent 65c2e7d2..., 8-vector tamper injection)
"""

from __future__ import annotations

import json
import shutil
import signal
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from autonomous_futures.production.self_driving import (  # noqa: E402
    UPSTREAM_PHASE_308_MERKLE_ROOT,
    MicroCapitalConfig,
    SelfDrivingState,
    SelfDrivingTradingEngine,
)
from autonomous_futures.safety.kill_switch import (  # noqa: E402
    CentralizedSolvencyLedger,
    GovernanceActionType,
    HardwareOSKillSwitchEngine,
    KillSwitchState,
    KillSwitchTier,
    MultiSigGovernanceEngine,
    SignerIdentity,
)
from scripts.run_phase_309_autonomous_launch import (  # noqa: E402
    EXPECTED_UPSTREAM_MERKLE_ROOT,
    verify_phase_309_autonomous_launch,
)
from scripts.run_phase_309_production_launch import (  # noqa: E402
    verify_phase_309_artifacts,
)

# ==============================================================================
# SECTION 1: MULTI-SIG GOVERNANCE ADVERSARIAL CHALLENGES
# ==============================================================================


def test_adv_multisig_single_signature_quorum_denial() -> None:
    """Challenge 1.1: Verify single-signature can NEVER approve any action under 2-of-3 quorum."""
    signers = [
        SignerIdentity("signer-cro", "pub-cro", "CHIEF_RISK_OFFICER"),
        SignerIdentity("signer-sec", "pub-sec", "SECURITY_OFFICER"),
        SignerIdentity("signer-dev", "pub-dev", "LEAD_DEV"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)

    prop = gov.create_proposal(
        GovernanceActionType.CHANGE_RISK_LIMIT,
        target="max_aggregate_exposure_usdt",
        parameters={"new_cap": 25.0},
    )

    # 0 votes -> Quorum NOT satisfied
    assert not gov.is_quorum_satisfied(prop.proposal_id)

    # Vote 1: Only CRO votes
    p_json = json.dumps(prop.parameters, sort_keys=True)
    msg = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig_cro = gov.compute_signature("signer-cro", msg)
    voted = gov.cast_vote(prop.proposal_id, "signer-cro", 1, sig_cro)
    assert voted

    # 1 of 3 votes -> MUST NOT satisfy 2-of-3 quorum
    assert not gov.is_quorum_satisfied(prop.proposal_id)
    assert len(prop.votes) == 1
    assert not prop.is_executed


def test_adv_multisig_anti_replay_nonce_exhaustion() -> None:
    """Challenge 1.2: Adversarially challenge monotonic nonce enforcement and replay rejection."""
    signers = [SignerIdentity("signer-cro", "pub-cro", "CHIEF_RISK_OFFICER")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)

    prop1 = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "target", {})
    p1_json = json.dumps(prop1.parameters, sort_keys=True)

    # Initial valid vote with nonce 10
    msg1 = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:10:{p1_json}"
    sig1 = gov.compute_signature("signer-cro", msg1)
    assert gov.cast_vote(prop1.proposal_id, "signer-cro", 10, sig1)

    # Attack 1: Exact replay with identical nonce 10 -> REJECTED
    assert not gov.cast_vote(prop1.proposal_id, "signer-cro", 10, sig1)

    # Attack 2: Decreased nonce 9 -> REJECTED
    msg_stale = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:9:{p1_json}"
    sig_stale = gov.compute_signature("signer-cro", msg_stale)
    assert not gov.cast_vote(prop1.proposal_id, "signer-cro", 9, sig_stale)

    # Attack 3: Decreased nonce 0 -> REJECTED
    msg_zero = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:0:{p1_json}"
    sig_zero = gov.compute_signature("signer-cro", msg_zero)
    assert not gov.cast_vote(prop1.proposal_id, "signer-cro", 0, sig_zero)

    # Attack 4: Decreased negative nonce -5 -> REJECTED
    msg_neg = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:-5:{p1_json}"
    sig_neg = gov.compute_signature("signer-cro", msg_neg)
    assert not gov.cast_vote(prop1.proposal_id, "signer-cro", -5, sig_neg)

    # Attack 5: New proposal with stale nonce 5 (less than last_nonce 10) -> REJECTED
    prop2 = gov.create_proposal(GovernanceActionType.RESET_LOCKOUT, "target", {})
    p2_json = json.dumps(prop2.parameters, sort_keys=True)
    msg_p2_stale = f"{prop2.proposal_id}:{prop2.action_type.value}:{prop2.target}:5:{p2_json}"
    sig_p2_stale = gov.compute_signature("signer-cro", msg_p2_stale)
    assert not gov.cast_vote(prop2.proposal_id, "signer-cro", 5, sig_p2_stale)

    # Legitimate next vote with strictly increasing nonce 11 -> ACCEPTED
    msg_p2_valid = f"{prop2.proposal_id}:{prop2.action_type.value}:{prop2.target}:11:{p2_json}"
    sig_p2_valid = gov.compute_signature("signer-cro", msg_p2_valid)
    assert gov.cast_vote(prop2.proposal_id, "signer-cro", 11, sig_p2_valid)


def test_adv_multisig_double_voting_rejection() -> None:
    """Challenge 1.3: Verify single signer cannot vote multiple times on same proposal."""
    signers = [
        SignerIdentity("signer-cro", "pub-cro", "CHIEF_RISK_OFFICER"),
        SignerIdentity("signer-sec", "pub-sec", "SECURITY_OFFICER"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)

    prop = gov.create_proposal(GovernanceActionType.RESET_LOCKOUT, "kill_switch", {})
    p_json = json.dumps(prop.parameters, sort_keys=True)

    # CRO casts Vote 1 with nonce 1 -> Valid
    msg1 = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig1 = gov.compute_signature("signer-cro", msg1)
    assert gov.cast_vote(prop.proposal_id, "signer-cro", 1, sig1)
    assert len(prop.votes) == 1
    assert not gov.is_quorum_satisfied(prop.proposal_id)

    # Attack: CRO attempts to cast a second vote with higher nonce 2 -> MUST BE REJECTED
    msg2 = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:2:{p_json}"
    sig2 = gov.compute_signature("signer-cro", msg2)
    assert not gov.cast_vote(prop.proposal_id, "signer-cro", 2, sig2)

    # Ensure vote count did not increment and quorum remains unsatisfied
    assert len(prop.votes) == 1
    assert not gov.is_quorum_satisfied(prop.proposal_id)


def test_adv_multisig_proposal_ttl_expiration_adversarial() -> None:
    """Challenge 1.4: Verify expired proposals cannot be approved even by valid signers."""
    signers = [
        SignerIdentity("signer-cro", "pub-cro", "CRO"),
        SignerIdentity("signer-sec", "pub-sec", "SEC"),
    ]
    ttl = 10_000  # 10s TTL
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2, proposal_ttl_ms=ttl)

    t0 = 1_000_000
    prop = gov.create_proposal(GovernanceActionType.RESET_LOCKOUT, "kill_switch", {}, now_ms=t0)
    assert prop.expires_at_ms == t0 + ttl

    p_json = json.dumps(prop.parameters, sort_keys=True)

    # CRO votes within TTL (at t0 + 1000ms) -> Valid
    msg_cro = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig_cro = gov.compute_signature("signer-cro", msg_cro)
    assert gov.cast_vote(prop.proposal_id, "signer-cro", 1, sig_cro, now_ms=t0 + 1000)

    # SEC attempts to vote after TTL expires (at t0 + ttl + 1ms) -> REJECTED
    msg_sec = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig_sec = gov.compute_signature("signer-sec", msg_sec)
    assert not gov.cast_vote(prop.proposal_id, "signer-sec", 1, sig_sec, now_ms=t0 + ttl + 1)

    # Proposal remains unapproved
    assert not gov.is_quorum_satisfied(prop.proposal_id)


def test_adv_multisig_payload_tampering_and_forgery() -> None:
    """Challenge 1.5: Verify parameter tampering, action tampering, and forged keys fail."""
    signers = [
        SignerIdentity("signer-cro", "pub-cro", "CRO"),
        SignerIdentity("signer-inactive", "pub-inactive", "SEC", is_active=False),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)

    prop = gov.create_proposal(
        GovernanceActionType.CHANGE_RISK_LIMIT,
        target="max_aggregate_exposure_usdt",
        parameters={"new_cap": 25.0},
    )

    # Attack 1: Parameter tampering (Signer signed new_cap=25.0, attacker submits new_cap=100.0)
    tampered_params = json.dumps({"new_cap": 100.0}, sort_keys=True)
    msg_tampered = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{tampered_params}"
    sig_tampered = gov.compute_signature("signer-cro", msg_tampered)
    # When cast_vote executes, it canonicalizes proposal.parameters (new_cap=25.0), mismatching sig
    assert not gov.cast_vote(prop.proposal_id, "signer-cro", 1, sig_tampered)

    # Attack 2: Forged signature using a bogus key
    bogus_sig = "deadbeef" * 8
    assert not gov.cast_vote(prop.proposal_id, "signer-cro", 1, bogus_sig)

    # Attack 3: Inactive signer vote attempt
    p_json = json.dumps(prop.parameters, sort_keys=True)
    msg_valid = f"{prop.proposal_id}:{prop.action_type.value}:{prop.target}:1:{p_json}"
    sig_inactive = gov.compute_signature("signer-inactive", msg_valid)
    assert not gov.cast_vote(prop.proposal_id, "signer-inactive", 1, sig_inactive)

    # Attack 4: Non-existent signer ID
    assert not gov.cast_vote(prop.proposal_id, "signer-rogue", 1, "sig")


# ==============================================================================
# SECTION 2: HARDWARE/OS KILL SWITCH & TRIPWIRE ADVERSARIAL CHALLENGES
# ==============================================================================


def test_adv_kill_switch_three_tier_containment() -> None:
    """Challenge 2.1: Verify strict operational boundaries across all 3 tiers."""
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger(starting_equity=100.0)
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)

    assert len(ks.open_orders) == 3
    assert len(ks.open_positions) == 2
    assert not ks.is_memory_wiped

    # Tier 1: Soft Pause -> Orders and positions preserved, state is LEVEL_1_SOFT_PAUSE
    e1 = ks.trigger_level_1_soft_pause("Hawkes runaway", "HAWKES")
    assert str(ks.state) == str(KillSwitchState.LEVEL_1_SOFT_PAUSE)
    assert e1.tier == KillSwitchTier.LEVEL_1_SOFT
    assert len(ks.open_orders) == 3
    assert len(ks.open_positions) == 2
    assert not ks.is_memory_wiped

    # Tier 2: Lockout -> Orders cancelled (0 remaining), positions preserved
    e2 = ks.trigger_level_2_lockout("Latency surge", "LATENCY")
    assert str(ks.state) == str(KillSwitchState.LEVEL_2_LOCKOUT)
    assert e2.tier == KillSwitchTier.LEVEL_2_LOCKOUT
    assert len(ks.open_orders) == 0
    assert e2.orders_cancelled_count == 3
    assert len(ks.open_positions) == 2
    assert not ks.is_memory_wiped

    # Tier 3: Panic -> Positions flattened (0 remaining), memory wiped
    e3 = ks.trigger_level_3_hardware_panic("Crash shock", "CRASH")
    assert str(ks.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)
    assert e3.tier == KillSwitchTier.LEVEL_3_PANIC
    assert len(ks.open_positions) == 0
    assert e3.positions_flattened_count == 2
    assert ks.is_memory_wiped
    assert len(ks._secure_memory_store) == 0


def test_adv_kill_switch_emergency_file_tripwire(tmp_path: Path) -> None:
    """Challenge 2.2: Verify emergency_kill.lock trips Level 3 Panic and sanitizes memory."""
    token_file = tmp_path / "emergency_kill.lock"
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(
        governance=gov, solvency_ledger=ledger, token_file_path=str(token_file)
    )

    # Initial check: no tripwire file -> returns False
    assert not ks.check_file_tripwire()
    assert str(ks.state) == str(KillSwitchState.ARMED_NORMAL)
    assert not ks.is_memory_wiped

    # Tripwire file created externally by watchdog / ops
    token_file.write_text("IMMEDIATE_HALT")

    # Tripwire check detects file -> returns True, trips panic
    tripped = ks.check_file_tripwire()
    assert tripped
    assert str(ks.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)
    assert ks.is_memory_wiped
    assert len(ks.open_orders) == 0
    assert len(ks.open_positions) == 0
    assert ks.events[-1].trigger_source == "FILE_TOKEN"

    # Engine coupling: SelfDrivingTradingEngine must fail closed immediately
    engine = SelfDrivingTradingEngine(
        config=MicroCapitalConfig(), solvency_ledger=ledger, kill_switch=ks, output_dir=tmp_path
    )
    # Pre-flight check fails
    assert not engine.run_pre_flight_check()
    assert str(engine.state) == str(SelfDrivingState.KILL_SWITCH_HALTED)

    # Order tick blocked
    ord_res = engine.process_microstructure_tick("BTCUSDT", Decimal("95000.0"), 0.3, 10.0, "LONG")
    assert ord_res is None


def test_adv_kill_switch_os_signal_trapping() -> None:
    """Challenge 2.3: Verify SIGINT and SIGTERM OS signals trigger immediate panic shutdown."""
    signers = [SignerIdentity("s1", "p1", "CRO")]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=1)
    ledger = CentralizedSolvencyLedger()

    # Test SIGINT
    ks1 = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)
    ks1.handle_os_signal(signal.SIGINT if hasattr(signal, "SIGINT") else 2)
    assert str(ks1.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)
    assert ks1.is_memory_wiped
    assert ks1.events[-1].trigger_source == "OS_SIGNAL"
    assert "SIGINT" in ks1.events[-1].reason or "SIG_2" in ks1.events[-1].reason

    # Test SIGTERM
    ks2 = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)
    ks2.handle_os_signal(signal.SIGTERM if hasattr(signal, "SIGTERM") else 15)
    assert str(ks2.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)
    assert ks2.is_memory_wiped
    assert ks2.events[-1].trigger_source == "OS_SIGNAL"
    assert "SIGTERM" in ks2.events[-1].reason or "SIG_15" in ks2.events[-1].reason


def test_adv_kill_switch_unauthorized_downgrade_prevention() -> None:
    """Challenge 2.4: Verify kill switch cannot be reset to ARMED_NORMAL without valid multi-sig."""
    signers = [
        SignerIdentity("s1", "p1", "CRO"),
        SignerIdentity("s2", "p2", "DEV"),
    ]
    gov = MultiSigGovernanceEngine(signers=signers, required_quorum=2)
    ledger = CentralizedSolvencyLedger()
    ks = HardwareOSKillSwitchEngine(governance=gov, solvency_ledger=ledger)

    # Trip Level 3 Panic
    ks.trigger_level_3_hardware_panic("Adversarial attack test", "TEST")
    assert str(ks.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)

    # Attack 1: Direct reset attempt with invalid/non-existent proposal ID -> REJECTED
    assert not ks.reset_to_normal("fake-proposal-id")
    assert str(ks.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)

    # Attack 2: Reset with proposal having only 1 vote (insufficient quorum) -> REJECTED
    prop1 = gov.create_proposal(GovernanceActionType.RESET_LOCKOUT, "kill_switch", {})
    p1_json = json.dumps(prop1.parameters, sort_keys=True)
    msg1 = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:1:{p1_json}"
    sig1 = gov.compute_signature("s1", msg1)
    gov.cast_vote(prop1.proposal_id, "s1", 1, sig1)
    assert not ks.reset_to_normal(prop1.proposal_id)
    assert str(ks.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)

    # Attack 3: Reset with proposal of WRONG action type (e.g. CHANGE_RISK_LIMIT) -> REJECTED
    prop2 = gov.create_proposal(GovernanceActionType.CHANGE_RISK_LIMIT, "exposure", {})
    p2_json = json.dumps(prop2.parameters, sort_keys=True)
    msg2_s1 = f"{prop2.proposal_id}:{prop2.action_type.value}:{prop2.target}:2:{p2_json}"
    msg2_s2 = f"{prop2.proposal_id}:{prop2.action_type.value}:{prop2.target}:1:{p2_json}"
    gov.cast_vote(prop2.proposal_id, "s1", 2, gov.compute_signature("s1", msg2_s1))
    gov.cast_vote(prop2.proposal_id, "s2", 1, gov.compute_signature("s2", msg2_s2))
    assert gov.is_quorum_satisfied(prop2.proposal_id)
    assert not ks.reset_to_normal(prop2.proposal_id)
    assert str(ks.state) == str(KillSwitchState.LEVEL_3_HARDWARE_PANIC)

    # Legitimate reset: Quorum of 2 votes on RESET_LOCKOUT action -> SUCCESS
    prop3 = gov.create_proposal(GovernanceActionType.RESET_LOCKOUT, "kill_switch", {})
    p3_json = json.dumps(prop3.parameters, sort_keys=True)
    msg3_s1 = f"{prop3.proposal_id}:{prop3.action_type.value}:{prop3.target}:3:{p3_json}"
    msg3_s2 = f"{prop3.proposal_id}:{prop3.action_type.value}:{prop3.target}:2:{p3_json}"
    gov.cast_vote(prop3.proposal_id, "s1", 3, gov.compute_signature("s1", msg3_s1))
    gov.cast_vote(prop3.proposal_id, "s2", 2, gov.compute_signature("s2", msg3_s2))
    assert gov.is_quorum_satisfied(prop3.proposal_id)
    assert ks.reset_to_normal(prop3.proposal_id)
    assert str(ks.state) == str(KillSwitchState.ARMED_NORMAL)


# ==============================================================================
# SECTION 3: CRYPTOGRAPHIC MERKLE DAG & TAMPER-RESISTANCE CHALLENGES
# ==============================================================================


def test_adv_merkle_dag_upstream_parent_hash_verification() -> None:
    """Challenge 3.1: Verify Phase 309 upstream parent hash strictly equals Phase 308
    Merkle Root.
    """
    expected_root = "65c2e7d2b3dc5d0f63773ef531c700a0fa2f6e73bdc094c7fad1105fc675e31e"
    assert UPSTREAM_PHASE_308_MERKLE_ROOT == expected_root
    assert EXPECTED_UPSTREAM_MERKLE_ROOT == expected_root

    # Cross-verify with Phase 308 artifact on disk
    phase_308_summary_path = Path("artifacts/research/phase308/kill-switch-summary.json")
    assert phase_308_summary_path.is_file()
    summary_308 = json.loads(phase_308_summary_path.read_text(encoding="utf-8"))
    assert summary_308.get("merkle_root") == expected_root

    # Cross-verify Phase 309 artifact on disk
    phase_309_summary_path = Path("artifacts/research/phase309/production-summary.json")
    assert phase_309_summary_path.is_file()
    summary_309 = json.loads(phase_309_summary_path.read_text(encoding="utf-8"))
    assert summary_309.get("upstream_hash") == expected_root


def test_adv_merkle_dag_bit_flip_tampering_fails_closed(tmp_path: Path) -> None:
    """Challenge 3.2: 8-Vector Tamper Injection Drill.

    Proves that modifying ANY byte or field in Phase 309 artifacts causes immediate,
    fail-closed verification failure.
    """
    src_dir = Path("artifacts/research/phase309")
    assert src_dir.is_dir()

    # Helper to set up a clean copy of artifacts in a sandbox directory
    def setup_sandbox(sandbox_name: str) -> Path:
        s_dir = tmp_path / sandbox_name
        s_dir.mkdir(parents=True, exist_ok=True)
        for f in src_dir.glob("*"):
            shutil.copy2(f, s_dir / f.name)
        # Verify clean copy passes
        assert verify_phase_309_artifacts(s_dir)
        assert verify_phase_309_autonomous_launch(s_dir)
        return s_dir

    # Attack Vector 1: Bit-flip in SQLite3 database
    d1 = setup_sandbox("attack_1_sqlite_bitflip")
    db_file = d1 / "canary-production-telemetry.sqlite3"
    raw_db = bytearray(db_file.read_bytes())
    raw_db[100] ^= 0xFF  # Flip byte at offset 100
    db_file.write_bytes(raw_db)
    assert not verify_phase_309_artifacts(d1)
    assert not verify_phase_309_autonomous_launch(d1)

    # Attack Vector 2: Rogue event appended to events JSONL
    d2 = setup_sandbox("attack_2_events_tamper")
    ev_file = d2 / "canary-production-events.jsonl"
    with open(ev_file, "a", encoding="utf-8") as f:
        f.write('{"rogue_event": "INJECTED_UNAUTHORIZED_ACTIVITY"}\n')
    assert not verify_phase_309_artifacts(d2)
    assert not verify_phase_309_autonomous_launch(d2)

    # Attack Vector 3: Altered state in report JSON
    d3 = setup_sandbox("attack_3_report_tamper")
    rep_file = d3 / "canary-production-report.json"
    rep_data = json.loads(rep_file.read_text(encoding="utf-8"))
    rep_data["state"] = "UNAUTHORIZED_FORGED_STATE"
    rep_file.write_text(json.dumps(rep_data, indent=2), encoding="utf-8")
    assert not verify_phase_309_artifacts(d3)
    assert not verify_phase_309_autonomous_launch(d3)

    # Attack Vector 4: Altered order count in execution JSON
    d4 = setup_sandbox("attack_4_exec_tamper")
    ex_file = d4 / "canary-production-execution.json"
    ex_data = json.loads(ex_file.read_text(encoding="utf-8"))
    ex_data["orders_count"] = 999
    ex_file.write_text(json.dumps(ex_data, indent=2), encoding="utf-8")
    assert not verify_phase_309_artifacts(d4)
    assert not verify_phase_309_autonomous_launch(d4)

    # Attack Vector 5: Forged upstream_hash in production-summary.json
    d5 = setup_sandbox("attack_5_upstream_hash_tamper")
    sum_file = d5 / "production-summary.json"
    sum_data = json.loads(sum_file.read_text(encoding="utf-8"))
    sum_data["upstream_hash"] = "0000000000000000000000000000000000000000000000000000000000000000"
    sum_file.write_text(json.dumps(sum_data, indent=2), encoding="utf-8")
    assert not verify_phase_309_artifacts(d5)
    assert not verify_phase_309_autonomous_launch(d5)

    # Attack Vector 6: Forged merkle_root in production-summary.json
    d6 = setup_sandbox("attack_6_merkle_root_tamper")
    sum_file6 = d6 / "production-summary.json"
    sum_data6 = json.loads(sum_file6.read_text(encoding="utf-8"))
    sum_data6["merkle_root"] = "badc0ffee" * 7 + "bad"
    sum_file6.write_text(json.dumps(sum_data6, indent=2), encoding="utf-8")
    assert not verify_phase_309_artifacts(d6)
    assert not verify_phase_309_autonomous_launch(d6)

    # Attack Vector 7: Missing artifact file
    d7 = setup_sandbox("attack_7_missing_file")
    (d7 / "canary-production-execution.json").unlink()
    assert not verify_phase_309_artifacts(d7)
    assert not verify_phase_309_autonomous_launch(d7)

    # Attack Vector 8: Injected solvency drift violation (>= 1e-15 USDT)
    d8 = setup_sandbox("attack_8_solvency_drift_injection")
    sum_file8 = d8 / "production-summary.json"
    sum_data8 = json.loads(sum_file8.read_text(encoding="utf-8"))
    sum_data8["solvency"]["drift"] = 1e-14
    sum_file8.write_text(json.dumps(sum_data8, indent=2), encoding="utf-8")
    assert not verify_phase_309_artifacts(d8)
    assert not verify_phase_309_autonomous_launch(d8)
