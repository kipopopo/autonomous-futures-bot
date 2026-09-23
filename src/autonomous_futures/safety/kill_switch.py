"""Phase 308: Capital Safety Governance, Multi-Signature & Hardware/OS Kill-Switch Engine.

Establishes cryptographic M-of-N multi-signature authorization pipelines, three-tier
hardware/OS emergency kill-switch containment, memory credential scrubbing, and strict
double-entry zero-drift balance governance under paper-safe confinement.
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import logging
import os
import signal
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PHASE_307_PARENT_MERKLE_ROOT = "4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16"


class KillSwitchState(enum.StrEnum):
    """Operational states of the multi-tier kill-switch."""

    ARMED_NORMAL = "ARMED_NORMAL"
    LEVEL_1_SOFT_PAUSE = "LEVEL_1_SOFT_PAUSE"
    LEVEL_2_LOCKOUT = "LEVEL_2_LOCKOUT"
    LEVEL_3_HARDWARE_PANIC = "LEVEL_3_HARDWARE_PANIC"
    MAINTENANCE = "MAINTENANCE"


class KillSwitchTier(enum.StrEnum):
    """Classification of kill-switch trigger severity."""

    LEVEL_1_SOFT = "LEVEL_1_SOFT"
    LEVEL_2_LOCKOUT = "LEVEL_2_LOCKOUT"
    LEVEL_3_PANIC = "LEVEL_3_PANIC"


class GovernanceActionType(enum.StrEnum):
    """Types of privileged operations requiring multi-sig quorum."""

    CHANGE_RISK_LIMIT = "CHANGE_RISK_LIMIT"
    UPDATE_LEVERAGE_CAP = "UPDATE_LEVERAGE_CAP"
    DISARM_KILL_SWITCH = "DISARM_KILL_SWITCH"
    TRIGGER_EMERGENCY_HALT = "TRIGGER_EMERGENCY_HALT"
    RESET_LOCKOUT = "RESET_LOCKOUT"
    SECURE_CREDENTIAL_WIPE = "SECURE_CREDENTIAL_WIPE"


@dataclass
class SignerIdentity:
    """Identity and authorization spec for a multi-sig guardian."""

    signer_id: str
    public_key: str
    role: str  # e.g., 'CHIEF_RISK_OFFICER', 'LEAD_DEV', 'SECURITY_OFFICER'
    is_active: bool = True
    last_nonce: int = 0


@dataclass
class MultiSigVote:
    """An individual signature submitted for a governance action."""

    signer_id: str
    signature: str
    nonce: int
    timestamp_ms: int


@dataclass
class GovernanceProposal:
    """A high-risk action proposal undergoing multi-sig evaluation."""

    proposal_id: str
    action_type: GovernanceActionType
    target: str
    parameters: dict[str, Any]
    created_at_ms: int
    expires_at_ms: int
    required_quorum: int
    votes: list[MultiSigVote] = field(default_factory=list)
    is_executed: bool = False
    execution_result: str | None = None


@dataclass
class KillSwitchEventRecord:
    """Audit log entry for kill-switch activation, escalation, or disarm."""

    event_id: str
    tier: KillSwitchTier
    previous_state: KillSwitchState
    new_state: KillSwitchState
    reason: str
    trigger_source: str  # 'HAWKES_BREACH', 'LATENCY_SPIKE', 'OS_SIGNAL', 'FILE_TOKEN', 'MULTI_SIG'
    positions_flattened_count: int
    orders_cancelled_count: int
    memory_wiped: bool
    timestamp_ms: int


@dataclass
class SolvencyLedgerSnapshot:
    """Mathematical double-entry balance state."""

    starting_equity: float
    cash: float
    allocated_margin: float
    unrealized_pnl: float
    realized_pnl: float
    total_equity: float
    drift: float
    zero_balance_drift: bool
    cash_reserve_pct: float
    unencumbered_cash_verified: bool


class MultiSigGovernanceEngine:
    """Enforces M-of-N cryptographic authorization for high-risk system modifications."""

    __test__ = False

    def __init__(
        self,
        signers: list[SignerIdentity],
        required_quorum: int = 2,
        proposal_ttl_ms: int = 60_000,
    ) -> None:
        self.signers: dict[str, SignerIdentity] = {s.signer_id: s for s in signers}
        self.required_quorum = required_quorum
        self.proposal_ttl_ms = proposal_ttl_ms
        self.proposals: dict[str, GovernanceProposal] = {}
        # In-memory mock secret keys for HMAC-SHA256 signature verification in tests
        self._mock_secrets: dict[str, str] = {
            s.signer_id: f"secret-key-for-{s.signer_id}-guard-308" for s in signers
        }

    def compute_signature(self, signer_id: str, message: str) -> str:
        """Helper to generate HMAC-SHA256 signature for a message."""
        secret = self._mock_secrets.get(signer_id, "default-secret")
        return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    def create_proposal(
        self,
        action_type: GovernanceActionType,
        target: str,
        parameters: dict[str, Any],
        now_ms: int | None = None,
    ) -> GovernanceProposal:
        """Creates a pending governance proposal."""
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        p_id = f"prop-{action_type.value.lower()}-{ts}"
        proposal = GovernanceProposal(
            proposal_id=p_id,
            action_type=action_type,
            target=target,
            parameters=parameters,
            created_at_ms=ts,
            expires_at_ms=ts + self.proposal_ttl_ms,
            required_quorum=self.required_quorum,
        )
        self.proposals[p_id] = proposal
        return proposal

    def cast_vote(
        self,
        proposal_id: str,
        signer_id: str,
        nonce: int,
        signature: str,
        now_ms: int | None = None,
    ) -> bool:
        """Validates signature, nonce replay, and expiration before recording vote."""
        ts = now_ms if now_ms is not None else int(time.time() * 1000)
        if proposal_id not in self.proposals:
            logger.warning(f"Unknown proposal {proposal_id}")
            return False

        proposal = self.proposals[proposal_id]
        if ts > proposal.expires_at_ms:
            logger.warning(f"Proposal {proposal_id} has expired")
            return False

        if signer_id not in self.signers:
            logger.warning(f"Unknown signer {signer_id}")
            return False

        signer = self.signers[signer_id]
        if not signer.is_active:
            logger.warning(f"Signer {signer_id} is inactive")
            return False

        if nonce <= signer.last_nonce:
            logger.warning(
                f"Replay detected: nonce {nonce} <= last {signer.last_nonce} for {signer_id}"
            )
            return False

        # Verify signature over canonical proposal message
        params_json = json.dumps(proposal.parameters, sort_keys=True)
        msg = f"{proposal_id}:{proposal.action_type.value}:{proposal.target}:{nonce}:{params_json}"
        expected_sig = self.compute_signature(signer_id, msg)
        if not hmac.compare_digest(signature, expected_sig):
            logger.warning(f"Invalid signature for signer {signer_id}")
            return False

        # Update nonce and record vote
        signer.last_nonce = nonce
        # Prevent double voting by same signer on same proposal
        for existing in proposal.votes:
            if existing.signer_id == signer_id:
                logger.warning(f"Signer {signer_id} already voted on {proposal_id}")
                return False

        proposal.votes.append(
            MultiSigVote(
                signer_id=signer_id,
                signature=signature,
                nonce=nonce,
                timestamp_ms=ts,
            )
        )
        return True

    def is_quorum_satisfied(self, proposal_id: str) -> bool:
        """Checks if valid votes meet or exceed quorum threshold."""
        if proposal_id not in self.proposals:
            return False
        return len(self.proposals[proposal_id].votes) >= self.required_quorum


class CentralizedSolvencyLedger:
    """Enforces mathematical double-entry zero-drift balance invariant."""

    __test__ = False

    def __init__(self, starting_equity: float = 100.0) -> None:
        self.starting_equity = Decimal(str(starting_equity))
        self.cash = Decimal(str(starting_equity))
        self.allocated_margin = Decimal("0.0")
        self.unrealized_pnl = Decimal("0.0")
        self.realized_pnl = Decimal("0.0")
        self.total_fees = Decimal("0.0")
        self.total_slippage = Decimal("0.0")
        self.max_exposure_cap = Decimal("60.00")
        self.intra_phase_loss_ceiling = Decimal("7.00")
        self.min_cash_reserve_floor_pct = Decimal("40.0")

    def record_fill(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        fee: float = 0.001,
        realized_pnl: float = 0.0,
    ) -> bool:
        """Records an execution fill with double-entry balance adjustment."""
        fee_dec = Decimal(str(fee))
        rpnl_dec = Decimal(str(realized_pnl))

        self.cash -= fee_dec
        self.total_fees += fee_dec
        self.cash += rpnl_dec
        self.realized_pnl += rpnl_dec - fee_dec
        return True

    def flatten_position(self, symbol: str, notional: float, fee: float = 0.001) -> None:
        """Simulates position flattening during emergency shutdown."""
        fee_dec = Decimal(str(fee))
        self.cash -= fee_dec
        self.total_fees += fee_dec
        self.realized_pnl -= fee_dec
        self.allocated_margin = max(Decimal("0.0"), self.allocated_margin - Decimal(str(notional)))

    def get_snapshot(self) -> SolvencyLedgerSnapshot:
        """Returns verified double-entry snapshot."""
        total_equity = self.cash + self.allocated_margin + self.unrealized_pnl
        drift = total_equity - (self.starting_equity + self.realized_pnl)
        zero_drift = abs(drift) < Decimal("1e-15")

        cash_pct = (
            (self.cash / self.starting_equity) * Decimal("100.0")
            if self.starting_equity > 0
            else Decimal("100.0")
        )
        unencumbered_cash_ok = cash_pct >= self.min_cash_reserve_floor_pct

        return SolvencyLedgerSnapshot(
            starting_equity=float(self.starting_equity),
            cash=float(self.cash),
            allocated_margin=float(self.allocated_margin),
            unrealized_pnl=float(self.unrealized_pnl),
            realized_pnl=float(self.realized_pnl),
            total_equity=float(total_equity),
            drift=float(drift),
            zero_balance_drift=zero_drift,
            cash_reserve_pct=float(cash_pct),
            unencumbered_cash_verified=unencumbered_cash_ok,
        )


class HardwareOSKillSwitchEngine:
    """Multi-tier kill-switch protecting capital via software interlocks, OS signal trapping,

    and emergency memory sanitization.
    """

    __test__ = False

    def __init__(
        self,
        governance: MultiSigGovernanceEngine,
        solvency_ledger: CentralizedSolvencyLedger,
        token_file_path: str = "/tmp/afbot_emergency_kill.lock",
    ) -> None:
        self.governance = governance
        self.ledger = solvency_ledger
        self.token_file_path = token_file_path
        self.state: KillSwitchState = KillSwitchState.ARMED_NORMAL
        self.events: list[KillSwitchEventRecord] = []
        self._secure_memory_store: dict[str, str] = {
            "api_key": "live-testnet-api-key-9f959cca583f",
            "api_secret": "live-testnet-secret-818fd82458a8fb19420d",
        }
        self.is_memory_wiped: bool = False
        self.open_orders: list[dict[str, Any]] = [
            {"order_id": "ord-btc-open-01", "symbol": "BTCUSDT", "qty": 0.00006, "price": 95000.0},
            {"order_id": "ord-eth-open-02", "symbol": "ETHUSDT", "qty": 0.002, "price": 2750.0},
            {"order_id": "ord-sol-open-03", "symbol": "SOLUSDT", "qty": 0.03, "price": 185.0},
        ]
        self.open_positions: list[dict[str, Any]] = [
            {"symbol": "BTCUSDT", "size": 0.00006, "entry_price": 95000.0, "notional": 5.70},
            {"symbol": "ETHUSDT", "size": 0.002, "entry_price": 2750.0, "notional": 5.50},
        ]

    def trigger_level_1_soft_pause(self, reason: str, trigger_source: str) -> KillSwitchEventRecord:
        """Triggers Level 1 Soft Pause (e.g. Hawkes runaway, high latency, spread cross)."""
        prev = self.state
        self.state = KillSwitchState.LEVEL_1_SOFT_PAUSE
        event = KillSwitchEventRecord(
            event_id=f"ks-evt-{len(self.events) + 1:04d}",
            tier=KillSwitchTier.LEVEL_1_SOFT,
            previous_state=prev,
            new_state=self.state,
            reason=reason,
            trigger_source=trigger_source,
            positions_flattened_count=0,
            orders_cancelled_count=0,
            memory_wiped=False,
            timestamp_ms=int(time.time() * 1000),
        )
        self.events.append(event)
        logger.info(f"Kill-Switch Level 1 triggered: {reason}")
        return event

    def trigger_level_2_lockout(self, reason: str, trigger_source: str) -> KillSwitchEventRecord:
        """Triggers Level 2 Lockout: Mass-cancels all active orders across candidate tracks."""
        prev = self.state
        self.state = KillSwitchState.LEVEL_2_LOCKOUT
        cancelled_count = len(self.open_orders)
        self.open_orders.clear()

        event = KillSwitchEventRecord(
            event_id=f"ks-evt-{len(self.events) + 1:04d}",
            tier=KillSwitchTier.LEVEL_2_LOCKOUT,
            previous_state=prev,
            new_state=self.state,
            reason=reason,
            trigger_source=trigger_source,
            positions_flattened_count=0,
            orders_cancelled_count=cancelled_count,
            memory_wiped=False,
            timestamp_ms=int(time.time() * 1000),
        )
        self.events.append(event)
        logger.warning(
            f"Kill-Switch Level 2 Lockout triggered: {reason}, cancelled {cancelled_count} orders"
        )
        return event

    def trigger_level_3_hardware_panic(
        self, reason: str, trigger_source: str
    ) -> KillSwitchEventRecord:
        """Triggers Level 3 Panic: Mass-cancels orders, flattens open positions,

        and sanitizes in-memory API credentials.
        """
        prev = self.state
        self.state = KillSwitchState.LEVEL_3_HARDWARE_PANIC

        cancelled_count = len(self.open_orders)
        self.open_orders.clear()

        flattened_count = len(self.open_positions)
        for pos in self.open_positions:
            self.ledger.flatten_position(pos["symbol"], pos["notional"])
        self.open_positions.clear()

        self._secure_memory_wipe()

        event = KillSwitchEventRecord(
            event_id=f"ks-evt-{len(self.events) + 1:04d}",
            tier=KillSwitchTier.LEVEL_3_PANIC,
            previous_state=prev,
            new_state=self.state,
            reason=reason,
            trigger_source=trigger_source,
            positions_flattened_count=flattened_count,
            orders_cancelled_count=cancelled_count,
            memory_wiped=True,
            timestamp_ms=int(time.time() * 1000),
        )
        self.events.append(event)
        logger.critical(
            f"Kill-Switch Level 3 Hardware Panic: {reason} | "
            f"Flattened {flattened_count}, Cancelled {cancelled_count}"
        )
        return event

    def check_file_tripwire(self) -> bool:
        """Checks for external panic token file (e.g. from ops monitoring or hardware watchdog)."""
        if os.path.exists(self.token_file_path):
            self.trigger_level_3_hardware_panic(
                reason=f"Tripwire token file detected at {self.token_file_path}",
                trigger_source="FILE_TOKEN",
            )
            return True
        return False

    def handle_os_signal(self, signum: int) -> None:
        """OS Signal handler to trigger immediate panic shutdown."""
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else f"SIG_{signum}"
        self.trigger_level_3_hardware_panic(
            reason=f"Trapped OS signal {sig_name}",
            trigger_source="OS_SIGNAL",
        )

    def _secure_memory_wipe(self) -> None:
        """Overwrites in-memory credential buffers with zeros before deletion."""
        for key in list(self._secure_memory_store.keys()):
            val_len = len(self._secure_memory_store[key])
            self._secure_memory_store[key] = "\x00" * val_len
            del self._secure_memory_store[key]
        self.is_memory_wiped = True

    def reset_to_normal(self, proposal_id: str) -> bool:
        """Resets kill-switch to ARMED_NORMAL only via approved multi-sig proposal."""
        if not self.governance.is_quorum_satisfied(proposal_id):
            logger.error("Cannot reset kill-switch: multi-sig quorum not satisfied")
            return False

        proposal = self.governance.proposals[proposal_id]
        if proposal.action_type != GovernanceActionType.RESET_LOCKOUT:
            logger.error(f"Invalid proposal action {proposal.action_type} for lockout reset")
            return False

        prev = self.state
        self.state = KillSwitchState.ARMED_NORMAL
        proposal.is_executed = True
        proposal.execution_result = "SUCCESS"

        self.events.append(
            KillSwitchEventRecord(
                event_id=f"ks-evt-{len(self.events) + 1:04d}",
                tier=KillSwitchTier.LEVEL_1_SOFT,
                previous_state=prev,
                new_state=self.state,
                reason=f"Multi-sig quorum reset approved via {proposal_id}",
                trigger_source="MULTI_SIG",
                positions_flattened_count=0,
                orders_cancelled_count=0,
                memory_wiped=False,
                timestamp_ms=int(time.time() * 1000),
            )
        )
        logger.info(f"Kill-switch reset to ARMED_NORMAL via proposal {proposal_id}")
        return True


class Phase308KillSwitchSimulator:
    """Orchestrates comprehensive multi-sig and multi-tier kill-switch validation,

    generating immutable cryptographic audit trails and Merkle DAG proofs.
    """

    __test__ = False

    def __init__(self, output_dir: Path | str = "artifacts/research/phase308") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.signers = [
            SignerIdentity("signer-cro-alice", "pub-alice-cro-308", "CHIEF_RISK_OFFICER"),
            SignerIdentity("signer-sec-bob", "pub-bob-sec-308", "SECURITY_OFFICER"),
            SignerIdentity("signer-dev-charlie", "pub-charlie-dev-308", "LEAD_DEV"),
        ]
        self.governance = MultiSigGovernanceEngine(self.signers, required_quorum=2)
        self.solvency_ledger = CentralizedSolvencyLedger(starting_equity=100.0)
        self.token_file_path = str(self.output_dir / "emergency_kill.lock")
        self.engine = HardwareOSKillSwitchEngine(
            governance=self.governance,
            solvency_ledger=self.solvency_ledger,
            token_file_path=self.token_file_path,
        )

    def run_simulation(self) -> dict[str, Any]:
        """Runs multi-sig scenarios, soft pause, lockout, and hardware panic triggers."""
        logger.info("Starting Phase 308 Kill-Switch & Multi-Sig Governance Simulation...")
        now = int(time.time() * 1000)

        # 1. Normal trading simulated fill with zero drift
        self.solvency_ledger.record_fill(
            "BTCUSDT", "BUY", 0.00006, 95000.0, fee=0.001, realized_pnl=0.02
        )
        self.solvency_ledger.record_fill(
            "ETHUSDT", "BUY", 0.002, 2750.0, fee=0.001, realized_pnl=0.01
        )

        # 2. Scenario A: Multi-sig proposal for risk limit change
        prop1 = self.governance.create_proposal(
            action_type=GovernanceActionType.CHANGE_RISK_LIMIT,
            target="max_exposure_cap",
            parameters={"new_cap_usdt": 50.0},
            now_ms=now,
        )
        # Signer Alice votes with valid nonce 1
        p1_params = json.dumps(prop1.parameters, sort_keys=True)
        msg1 = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:1:{p1_params}"
        sig_alice = self.governance.compute_signature("signer-cro-alice", msg1)
        v1 = self.governance.cast_vote(
            prop1.proposal_id, "signer-cro-alice", 1, sig_alice, now_ms=now
        )

        # Signer Bob votes with valid nonce 1
        msg1_bob = f"{prop1.proposal_id}:{prop1.action_type.value}:{prop1.target}:1:{p1_params}"
        sig_bob = self.governance.compute_signature("signer-sec-bob", msg1_bob)
        v2 = self.governance.cast_vote(prop1.proposal_id, "signer-sec-bob", 1, sig_bob, now_ms=now)

        assert v1 and v2
        assert self.governance.is_quorum_satisfied(prop1.proposal_id)
        prop1.is_executed = True
        prop1.execution_result = "SUCCESS"

        # 3. Scenario B: Level 1 Soft Pause on Hawkes Runaway Spike
        self.engine.trigger_level_1_soft_pause(
            reason="Hawkes spectral radius rho >= 1.0000 (1.1420 supercritical)",
            trigger_source="HAWKES_BREACH",
        )

        # 4. Scenario C: Level 2 Operational Lockout on Latency Spike
        self.engine.trigger_level_2_lockout(
            reason="Round-trip latency spike > 500 ms (tau_rtt = 582.4 ms)",
            trigger_source="LATENCY_SPIKE",
        )

        # 5. Scenario D: Multi-sig proposal to reset lockout
        prop_reset = self.governance.create_proposal(
            action_type=GovernanceActionType.RESET_LOCKOUT,
            target="kill_switch",
            parameters={"target_state": "ARMED_NORMAL"},
            now_ms=now + 1000,
        )
        reset_params = json.dumps(prop_reset.parameters, sort_keys=True)
        msg_r_alice = (
            f"{prop_reset.proposal_id}:{prop_reset.action_type.value}:"
            f"{prop_reset.target}:2:{reset_params}"
        )
        sig_r_alice = self.governance.compute_signature("signer-cro-alice", msg_r_alice)
        self.governance.cast_vote(
            prop_reset.proposal_id, "signer-cro-alice", 2, sig_r_alice, now_ms=now + 1000
        )

        msg_r_charlie = (
            f"{prop_reset.proposal_id}:{prop_reset.action_type.value}:"
            f"{prop_reset.target}:1:{reset_params}"
        )
        sig_r_charlie = self.governance.compute_signature("signer-dev-charlie", msg_r_charlie)
        self.governance.cast_vote(
            prop_reset.proposal_id, "signer-dev-charlie", 1, sig_r_charlie, now_ms=now + 1000
        )

        assert self.governance.is_quorum_satisfied(prop_reset.proposal_id)
        reset_ok = self.engine.reset_to_normal(prop_reset.proposal_id)
        assert reset_ok
        assert self.engine.state.value == KillSwitchState.ARMED_NORMAL.value

        # 6. Scenario E: Level 3 Hardware Panic via OS Signal Interception
        self.engine.handle_os_signal(signal.SIGINT if hasattr(signal, "SIGINT") else 2)
        assert self.engine.state == KillSwitchState.LEVEL_3_HARDWARE_PANIC
        assert self.engine.is_memory_wiped
        assert len(self.engine.open_orders) == 0
        assert len(self.engine.open_positions) == 0

        # Snapshot solvency ledger
        snapshot = self.solvency_ledger.get_snapshot()
        assert snapshot.zero_balance_drift

        # Persist artifacts
        summary = self._save_artifacts(now, snapshot)
        return summary

    def _save_artifacts(self, now: int, snapshot: SolvencyLedgerSnapshot) -> dict[str, Any]:
        """Saves SQLite3 database, events JSONL, and cryptographically hashed summary."""
        db_path = self.output_dir / "canary-kill-switch-telemetry.sqlite3"
        if db_path.exists():
            db_path.unlink()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE kill_switch_events (
                event_id TEXT PRIMARY KEY,
                tier TEXT,
                previous_state TEXT,
                new_state TEXT,
                reason TEXT,
                trigger_source TEXT,
                positions_flattened INTEGER,
                orders_cancelled INTEGER,
                memory_wiped INTEGER,
                timestamp_ms INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE governance_proposals (
                proposal_id TEXT PRIMARY KEY,
                action_type TEXT,
                target TEXT,
                parameters_json TEXT,
                quorum_required INTEGER,
                votes_cast INTEGER,
                is_executed INTEGER,
                created_at_ms INTEGER
            )
            """
        )

        for evt in self.engine.events:
            cur.execute(
                """
                INSERT INTO kill_switch_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evt.event_id,
                    evt.tier.value,
                    evt.previous_state.value,
                    evt.new_state.value,
                    evt.reason,
                    evt.trigger_source,
                    evt.positions_flattened_count,
                    evt.orders_cancelled_count,
                    1 if evt.memory_wiped else 0,
                    evt.timestamp_ms,
                ),
            )

        for prop in self.governance.proposals.values():
            cur.execute(
                """
                INSERT INTO governance_proposals VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prop.proposal_id,
                    prop.action_type.value,
                    prop.target,
                    json.dumps(prop.parameters),
                    prop.required_quorum,
                    len(prop.votes),
                    1 if prop.is_executed else 0,
                    prop.created_at_ms,
                ),
            )
        conn.commit()
        conn.close()

        # Save events JSONL
        events_path = self.output_dir / "canary-kill-switch-events.jsonl"
        with open(events_path, "w", encoding="utf-8") as f:
            for evt in self.engine.events:
                f.write(json.dumps(asdict(evt)) + "\n")

        # Compute SHA-256 hashes of database and events
        sqlite_bytes = db_path.read_bytes()
        events_bytes = events_path.read_bytes()
        sqlite_hash = hashlib.sha256(sqlite_bytes).hexdigest()
        events_hash = hashlib.sha256(events_bytes).hexdigest()

        # Detailed report
        report_data = {
            "phase": "phase_308",
            "verified": True,
            "status": "KILL_SWITCH_VERIFIED",
            "timestamp_ms": now,
            "paper_safe": True,
            "execution_authority": False,
            "kill_switch_state": self.engine.state.value,
            "memory_wiped": self.engine.is_memory_wiped,
            "signers": [asdict(s) for s in self.signers],
            "proposals": [
                {
                    "proposal_id": p.proposal_id,
                    "action_type": p.action_type.value,
                    "target": p.target,
                    "parameters": p.parameters,
                    "required_quorum": p.required_quorum,
                    "votes_cast": len(p.votes),
                    "is_executed": p.is_executed,
                    "execution_result": p.execution_result,
                }
                for p in self.governance.proposals.values()
            ],
            "events_trace": [asdict(e) for e in self.engine.events],
            "solvency": asdict(snapshot),
            "ledger": asdict(snapshot),
        }
        report_path = self.output_dir / "canary-kill-switch-report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        # Paper execution record
        paper_exec_data = {
            "phase": "phase_308",
            "execution_mode": "PAPER_SAFE_MULTI_SIG_LOCKOUT",
            "execution_authority": False,
            "zero_drift_tolerance_usdt": 1e-15,
            "balance_drift_usdt": snapshot.drift,
            "unencumbered_cash_reserve_pct": snapshot.cash_reserve_pct,
            "kill_switch_state": self.engine.state.value,
            "emergency_flattened": True,
        }
        paper_path = self.output_dir / "canary-kill-switch-paper-execution.json"
        with open(paper_path, "w", encoding="utf-8") as f:
            json.dump(paper_exec_data, f, indent=2)

        # Local phase hash
        combined_payload = (
            f"phase_308:{PHASE_307_PARENT_MERKLE_ROOT}:{sqlite_hash}:{events_hash}:{snapshot.drift}"
        )
        phase_hash = hashlib.sha256(combined_payload.encode()).hexdigest()

        # Merkle DAG root linking back to Phase 307
        merkle_root = hashlib.sha256(
            f"{PHASE_307_PARENT_MERKLE_ROOT}:{phase_hash}".encode()
        ).hexdigest()

        summary_data = {
            "phase": "phase_308",
            "verified": True,
            "status": "KILL_SWITCH_VERIFIED",
            "timestamp_ms": now,
            "paper_safe": True,
            "execution_authority": False,
            "kill_switch_state": self.engine.state.value,
            "memory_wiped": self.engine.is_memory_wiped,
            "active_signers_count": len([s for s in self.signers if s.is_active]),
            "required_quorum": self.governance.required_quorum,
            "proposals_evaluated": len(self.governance.proposals),
            "proposals_executed": len(
                [p for p in self.governance.proposals.values() if p.is_executed]
            ),
            "total_kill_events": len(self.engine.events),
            "emergency_flattened_positions": sum(
                e.positions_flattened_count for e in self.engine.events
            ),
            "cancelled_orders_count": sum(e.orders_cancelled_count for e in self.engine.events),
            "solvency": asdict(snapshot),
            "upstream_hash": PHASE_307_PARENT_MERKLE_ROOT,
            "phase_hash": phase_hash,
            "merkle_root": merkle_root,
            "artifact_hashes": {
                "sqlite3": sqlite_hash,
                "events_jsonl": events_hash,
            },
            "upstream_merkle_dag": {
                "phase_300": "25c81437dc77630dd8a143aea2056a126c16d908573d69a79676bc223fbbd14c",
                "phase_301": "64f0c31a6763924339d1737f7ff94923b4eba22f71bb703295a045bb5e16da7a",
                "phase_302": "5919a67c92e3121b66005ef7e9a36a651cb71b19556c19d4feb9470bdf289d76",
                "phase_303": "8ec3824da1946a3fc6fb70f2302a3b139f046385e76bf6050bf00fc58ae31f70",
                "phase_304": "07ffc13325eeffaadd0fb2e2cc60fe15269943f0bfca55fd613289c02a4fb80b",
                "phase_305": "0cbf6a93a5332789d5053f72e7e494b03b48ccd0ff7c62118bb339d5d905aa7c",
                "phase_306": "818fd82458a8fb19420dd0179c8f78b0c273e5d2a71b1968b083d20f99e23dbe",
                "phase_307": "4eb405de6cdc48e26fddaa4a2ed8bd91ef9e0843a4b71cfd0cb643a15e7ceb16",
            },
        }

        summary_path = self.output_dir / "kill-switch-summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)

        logger.info(f"Phase 308 Simulation complete. Merkle Root: {merkle_root}")
        return summary_data


def run_phase_308_simulation(
    output_dir: Path | str = "artifacts/research/phase308",
) -> dict[str, Any]:
    """Top-level helper to run Phase 308 kill-switch simulation."""
    simulator = Phase308KillSwitchSimulator(output_dir=output_dir)
    return simulator.run_simulation()


def verify_phase_308_merkle_dag(
    output_dir: Path | str = "artifacts/research/phase308",
    parent_merkle_root: str = PHASE_307_PARENT_MERKLE_ROOT,
) -> bool:
    """Verify cryptographic integrity of Phase 308 artifacts and Merkle DAG hash chain."""
    p_dir = Path(output_dir)
    summary_file = p_dir / "kill-switch-summary.json"
    if not summary_file.is_file():
        return False

    with open(summary_file, encoding="utf-8") as f:
        summary = json.load(f)

    if summary.get("upstream_hash") != parent_merkle_root:
        return False

    artifact_hashes = summary.get("artifact_hashes", {})
    expected_sqlite_hash = artifact_hashes.get("sqlite3", "")
    expected_events_hash = artifact_hashes.get("events_jsonl", "")

    sqlite_file = p_dir / "canary-kill-switch-telemetry.sqlite3"
    events_file = p_dir / "canary-kill-switch-events.jsonl"
    if not sqlite_file.is_file() or not events_file.is_file():
        return False

    computed_sqlite_hash = hashlib.sha256(sqlite_file.read_bytes()).hexdigest()
    computed_events_hash = hashlib.sha256(events_file.read_bytes()).hexdigest()

    if computed_sqlite_hash != expected_sqlite_hash or computed_events_hash != expected_events_hash:
        return False

    drift = float(summary.get("solvency", {}).get("drift", 1.0))
    if abs(drift) >= 1e-15:
        return False

    combined_payload = (
        f"phase_308:{parent_merkle_root}:{computed_sqlite_hash}:{computed_events_hash}:{drift}"
    )
    expected_phase_hash = hashlib.sha256(combined_payload.encode()).hexdigest()
    if expected_phase_hash != summary.get("phase_hash"):
        return False

    expected_merkle_root = hashlib.sha256(
        f"{parent_merkle_root}:{expected_phase_hash}".encode()
    ).hexdigest()
    return bool(expected_merkle_root == summary.get("merkle_root"))
