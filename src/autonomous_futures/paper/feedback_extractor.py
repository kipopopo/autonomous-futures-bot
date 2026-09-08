"""Extracts structured CreatorQualificationFailureFeedback from paper trading ledgers.

Connects real SQLite paper trading outcomes (paper-ledger.sqlite3 / paper-lifecycle.sqlite3)
to the bounded autonomous cycle pipeline, generating validated failure feedback
whenever an active candidate breaches paper qualification criteria.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from pydantic import Field, field_validator

from autonomous_futures.analytics.ledger_reader import ReadOnlyLedgerReader
from autonomous_futures.analytics.metrics import calculate_performance_metrics
from autonomous_futures.analytics.models import PerformanceMetrics, TradeRecord
from autonomous_futures.data.parquet import DataQualityError
from autonomous_futures.domain.contracts import DomainModel
from autonomous_futures.research.creator_artifacts import (
    CreatorCandidateArtifact,
    read_creator_candidate_artifact,
)
from autonomous_futures.research.creator_failure_feedback import (
    CreatorQualificationFailureFeedback,
)
from autonomous_futures.research.qualification_artifacts import (
    QualificationGateResult,
)

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_SEARCH_PATHS: tuple[Path, ...] = (
    Path("artifacts/research/phase252/candidates"),
    Path("artifacts/research/phase249/candidates"),
)


class PaperQualificationPolicy(DomainModel):
    """Evaluation thresholds for paper trading candidate performance."""

    policy_id: str = Field(default="paper-qualification-v1", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    paper_net_pnl_min: Decimal = Field(default=Decimal("0.00"))
    paper_profit_factor_min: Decimal = Field(default=Decimal("1.05"))
    paper_win_rate_min: Decimal = Field(default=Decimal("45.00"))
    paper_drawdown_max: Decimal = Field(default=Decimal("15.00"))
    paper_trades_min: int = Field(default=5, ge=0)

    @field_validator(
        "paper_net_pnl_min",
        "paper_profit_factor_min",
        "paper_win_rate_min",
        "paper_drawdown_max",
    )
    @classmethod
    def thresholds_are_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("paper qualification policy thresholds must be finite")
        return value

    @field_validator("paper_profit_factor_min")
    @classmethod
    def non_negative_profit_factor(cls, value: Decimal) -> Decimal:
        if value < Decimal("0.0"):
            raise ValueError("paper_profit_factor_min must be non-negative")
        return value

    @field_validator("paper_win_rate_min", "paper_drawdown_max")
    @classmethod
    def percentage_bounded(cls, value: Decimal) -> Decimal:
        if value < Decimal("0.0") or value > Decimal("100.0"):
            raise ValueError("percentage thresholds must be between 0.0 and 100.0")
        return value

    @property
    def min_trades(self) -> int:
        return self.paper_trades_min

    @property
    def min_net_pnl(self) -> Decimal:
        return self.paper_net_pnl_min

    @property
    def min_profit_factor(self) -> Decimal:
        return self.paper_profit_factor_min

    @property
    def min_win_rate_pct(self) -> Decimal:
        return self.paper_win_rate_min

    @property
    def max_drawdown_pct(self) -> Decimal:
        return self.paper_drawdown_max


def paper_qualification_policy_content_hash(policy: PaperQualificationPolicy) -> str:
    """Compute deterministic SHA-256 hash of policy content."""
    canonical = json.dumps(
        policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


class ResolvedCandidateMetadata(DomainModel):
    """Resolved candidate metadata required for constructing failure feedback."""

    candidate_id: str = Field(pattern=r"^cand-[a-z0-9][a-z0-9-]{0,63}$")
    candidate_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    qualification_policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    symbol: str | None = None


def compute_feedback_qualification_hash(
    *,
    candidate_id: str,
    candidate_artifact_hash: str,
    bundle_hash: str,
    dataset_registry_hash: str,
    qualification_policy_id: str,
    failed_gates: Sequence[QualificationGateResult],
) -> str:
    """Compute deterministic SHA-256 qualification hash for paper feedback."""
    ordered_gates = [
        gate.model_dump(mode="json") for gate in sorted(failed_gates, key=lambda g: g.gate_id)
    ]
    payload = {
        "bundle_hash": bundle_hash,
        "candidate_artifact_hash": candidate_artifact_hash,
        "candidate_id": candidate_id,
        "dataset_registry_hash": dataset_registry_hash,
        "failed_gates": ordered_gates,
        "qualification_policy_id": qualification_policy_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


class PaperFeedbackExtractor:
    """Extracts paper execution metrics and constructs failure feedback artifacts."""

    def __init__(
        self,
        storage_path: Path | str,
        lifecycle_path: Path | str | None = None,
        *,
        policy: PaperQualificationPolicy | None = None,
        candidates_dir: Path | str | None = None,
    ) -> None:
        raw_path = Path(storage_path)
        if raw_path.is_dir():
            self.storage_dir = raw_path
            self.ledger_db_path = raw_path / "paper-ledger.sqlite3"
            self.lifecycle_db_path = (
                Path(lifecycle_path) if lifecycle_path else (raw_path / "paper-lifecycle.sqlite3")
            )
        else:
            self.ledger_db_path = raw_path
            self.storage_dir = raw_path.parent
            self.lifecycle_db_path = (
                Path(lifecycle_path)
                if lifecycle_path
                else (self.storage_dir / "paper-lifecycle.sqlite3")
            )

        if not self.ledger_db_path.is_file():
            raise FileNotFoundError(
                f"Paper ledger database file not found at: {self.ledger_db_path}"
            )

        self.reader = ReadOnlyLedgerReader(self.storage_dir)
        self.reader.ledger_db_path = self.ledger_db_path
        if self.lifecycle_db_path.is_file():
            self.reader.lifecycle_db_path = self.lifecycle_db_path
        else:
            logger.debug("Paper lifecycle marks database not found at %s", self.lifecycle_db_path)

        self.default_policy = policy or PaperQualificationPolicy()
        self.candidates_dir = Path(candidates_dir) if candidates_dir else None

    def get_closed_trades(
        self,
        *,
        symbol: str | None = None,
        candidate_id: str | None = None,
    ) -> list[TradeRecord]:
        """Query closed trades from the paper ledger with optional filtering."""
        symbols_filter = [symbol] if symbol is not None else None
        trades = self.reader.read_closed_trades(symbols=symbols_filter)
        if candidate_id is not None:
            trades = [t for t in trades if t.candidate_id == candidate_id]
        return trades

    def resolve_candidate_metadata(
        self,
        *,
        candidate_id: str | None = None,
        symbol: str | None = None,
        candidate_artifact: CreatorCandidateArtifact | None = None,
        candidate_artifact_path: Path | str | None = None,
        candidate_artifact_hash: str | None = None,
        bundle_hash: str | None = None,
        dataset_registry_hash: str | None = None,
        policy: PaperQualificationPolicy | None = None,
        trades: Sequence[TradeRecord] | None = None,
    ) -> ResolvedCandidateMetadata:
        """Resolve candidate metadata using a 4-tier resolution hierarchy."""
        resolved_policy = policy or self.default_policy
        resolved_cand_id = candidate_id
        resolved_art_hash = candidate_artifact_hash
        resolved_bundle_hash = bundle_hash
        resolved_dataset_hash = dataset_registry_hash
        resolved_symbol = symbol

        # Tier 1: Directly provided CreatorCandidateArtifact
        if candidate_artifact is not None:
            resolved_cand_id = candidate_artifact.candidate_id
            resolved_art_hash = candidate_artifact.artifact_hash
            resolved_bundle_hash = candidate_artifact.bundle_hash
            resolved_dataset_hash = candidate_artifact.dataset_registry_hash
            if not resolved_symbol and candidate_artifact.strategy.universe.symbols:
                resolved_symbol = candidate_artifact.strategy.universe.symbols[0]

        # Tier 2: Candidate artifact file path
        elif candidate_artifact_path is not None:
            cand_path = Path(candidate_artifact_path)
            if not cand_path.is_file():
                raise FileNotFoundError(f"Candidate artifact file not found: {cand_path}")
            loaded_cand = read_creator_candidate_artifact(cand_path)
            resolved_cand_id = loaded_cand.candidate_id
            resolved_art_hash = loaded_cand.artifact_hash
            resolved_bundle_hash = loaded_cand.bundle_hash
            resolved_dataset_hash = loaded_cand.dataset_registry_hash
            if not resolved_symbol and loaded_cand.strategy.universe.symbols:
                resolved_symbol = loaded_cand.strategy.universe.symbols[0]

        # Fallback: Infer candidate_id and candidate_artifact_hash from trade records
        if (resolved_cand_id is None or resolved_art_hash is None) and trades:
            matching_trades = (
                [t for t in trades if t.candidate_id == resolved_cand_id]
                if resolved_cand_id
                else list(trades)
            )
            if matching_trades:
                latest_trade = matching_trades[-1]
                resolved_cand_id = resolved_cand_id or latest_trade.candidate_id
                resolved_art_hash = resolved_art_hash or latest_trade.candidate_artifact_hash
                resolved_symbol = resolved_symbol or latest_trade.symbol

        if resolved_cand_id is None:
            raise ValueError("candidate_id could not be resolved from inputs or trade records")

        # Caller overrides
        if bundle_hash is not None:
            resolved_bundle_hash = bundle_hash
        if dataset_registry_hash is not None:
            resolved_dataset_hash = dataset_registry_hash
        if candidate_artifact_hash is not None:
            resolved_art_hash = candidate_artifact_hash

        # Tier 3: Search candidate JSONs if hashes are missing
        missing_hashes = (
            resolved_bundle_hash is None
            or resolved_dataset_hash is None
            or resolved_art_hash is None
        )
        if missing_hashes:
            search_dirs: list[Path] = []
            if self.candidates_dir:
                search_dirs.append(self.candidates_dir)
            search_dirs.extend(DEFAULT_CANDIDATE_SEARCH_PATHS)

            found_json: Path | None = None
            for sdir in search_dirs:
                candidate_file = sdir / f"{resolved_cand_id}.json"
                if candidate_file.is_file():
                    found_json = candidate_file
                    break

            if found_json is None:
                # Fallback glob across artifacts/research/*/candidates/
                for p in Path("artifacts/research").glob(f"*/candidates/{resolved_cand_id}.json"):
                    found_json = p
                    break

            if found_json is not None:
                raw_json = json.loads(found_json.read_text(encoding="utf-8"))
                resolved_art_hash = resolved_art_hash or raw_json.get("artifact_hash")
                resolved_bundle_hash = resolved_bundle_hash or raw_json.get("bundle_hash")
                resolved_dataset_hash = resolved_dataset_hash or raw_json.get(
                    "dataset_registry_hash"
                )
                if resolved_symbol is None:
                    strategy_dict = raw_json.get("strategy") or {}
                    universe_dict = strategy_dict.get("universe") or {}
                    symbols_list = universe_dict.get("symbols") or []
                    if symbols_list:
                        resolved_symbol = symbols_list[0]

        # Tier 4: Validation against required schema contracts
        if resolved_art_hash is None:
            raise DataQualityError(
                f"candidate_artifact_hash could not be resolved for candidate '{resolved_cand_id}'"
            )
        if resolved_bundle_hash is None:
            raise DataQualityError(
                f"bundle_hash could not be resolved for candidate '{resolved_cand_id}'"
            )
        if resolved_dataset_hash is None:
            raise DataQualityError(
                f"dataset_registry_hash could not be resolved for candidate '{resolved_cand_id}'"
            )

        return ResolvedCandidateMetadata(
            candidate_id=resolved_cand_id,
            candidate_artifact_hash=resolved_art_hash,
            bundle_hash=resolved_bundle_hash,
            dataset_registry_hash=resolved_dataset_hash,
            qualification_policy_id=resolved_policy.policy_id,
            symbol=resolved_symbol,
        )

    def evaluate_gates(
        self,
        metrics: PerformanceMetrics,
        *,
        policy: PaperQualificationPolicy | None = None,
    ) -> list[QualificationGateResult]:
        """Evaluate performance metrics against qualification policy gates."""
        active_policy = policy or self.default_policy
        gates: list[QualificationGateResult] = []

        # Gate 1: paper_trades_min
        trades_observed = Decimal(metrics.total_trades)
        trades_threshold = Decimal(active_policy.paper_trades_min)
        trades_passed = trades_observed >= trades_threshold
        gates.append(
            QualificationGateResult(
                gate_id="paper_trades_min",
                passed=trades_passed,
                observed=trades_observed,
                threshold=trades_threshold,
                comparator="gte",
                reason_code=(
                    "paper_trades_passed" if trades_passed else "paper_trades_below_threshold"
                ),
            )
        )

        # Only evaluate trade-level performance gates if trades exist
        if metrics.total_trades > 0:
            # Gate 2: paper_net_pnl_min
            net_pnl_observed = metrics.net_pnl
            net_pnl_threshold = active_policy.paper_net_pnl_min
            net_pnl_passed = net_pnl_observed >= net_pnl_threshold
            gates.append(
                QualificationGateResult(
                    gate_id="paper_net_pnl_min",
                    passed=net_pnl_passed,
                    observed=net_pnl_observed,
                    threshold=net_pnl_threshold,
                    comparator="gte",
                    reason_code=(
                        "paper_net_pnl_passed"
                        if net_pnl_passed
                        else "paper_net_pnl_below_threshold"
                    ),
                )
            )

            # Gate 3: paper_profit_factor_min
            pf_threshold = active_policy.paper_profit_factor_min
            if metrics.gross_loss == Decimal("0.00") and metrics.gross_profit > Decimal("0.00"):
                # Infinite profit factor (all winning trades)
                pf_passed = True
                pf_observed = None
                pf_reason = "paper_profit_factor_passed"
            elif metrics.profit_factor is not None:
                pf_observed = Decimal(str(round(metrics.profit_factor, 4)))
                pf_passed = pf_observed >= pf_threshold
                pf_reason = (
                    "paper_profit_factor_passed"
                    if pf_passed
                    else "paper_profit_factor_below_threshold"
                )
            else:
                pf_observed = Decimal("0.00")
                pf_passed = pf_observed >= pf_threshold
                pf_reason = (
                    "paper_profit_factor_passed" if pf_passed else "paper_profit_factor_missing"
                )

            gates.append(
                QualificationGateResult(
                    gate_id="paper_profit_factor_min",
                    passed=pf_passed,
                    observed=pf_observed,
                    threshold=pf_threshold,
                    comparator="gte",
                    reason_code=pf_reason,
                )
            )

            # Gate 4: paper_win_rate_min
            wr_observed = Decimal(str(round(metrics.win_rate_pct, 4)))
            wr_threshold = active_policy.paper_win_rate_min
            wr_passed = wr_observed >= wr_threshold
            gates.append(
                QualificationGateResult(
                    gate_id="paper_win_rate_min",
                    passed=wr_passed,
                    observed=wr_observed,
                    threshold=wr_threshold,
                    comparator="gte",
                    reason_code=(
                        "paper_win_rate_passed" if wr_passed else "paper_win_rate_below_threshold"
                    ),
                )
            )

            # Gate 5: paper_drawdown_max
            dd_observed = Decimal(str(round(metrics.max_drawdown_pct, 4)))
            dd_threshold = active_policy.paper_drawdown_max
            dd_passed = dd_observed <= dd_threshold
            gates.append(
                QualificationGateResult(
                    gate_id="paper_drawdown_max",
                    passed=dd_passed,
                    observed=dd_observed,
                    threshold=dd_threshold,
                    comparator="lte",
                    reason_code=(
                        "paper_drawdown_passed" if dd_passed else "paper_drawdown_above_threshold"
                    ),
                )
            )

        return gates

    def extract(
        self,
        *,
        symbol: str | None = None,
        candidate_id: str | None = None,
        candidate_artifact: CreatorCandidateArtifact | None = None,
        candidate_artifact_path: Path | str | None = None,
        candidate_artifact_hash: str | None = None,
        bundle_hash: str | None = None,
        dataset_registry_hash: str | None = None,
        policy: PaperQualificationPolicy | None = None,
    ) -> CreatorQualificationFailureFeedback | None:
        """Extract closed trades, calculate metrics, and build failure feedback if breached."""
        active_policy = policy or self.default_policy

        target_cand_id = candidate_id
        target_symbol = symbol
        loaded_art: CreatorCandidateArtifact | None = candidate_artifact
        if loaded_art is None and candidate_artifact_path is not None:
            cand_path = Path(candidate_artifact_path)
            if not cand_path.is_file():
                raise FileNotFoundError(f"Candidate artifact file not found: {cand_path}")
            loaded_art = read_creator_candidate_artifact(cand_path)
        if loaded_art is not None:
            target_cand_id = target_cand_id or loaded_art.candidate_id
            if target_symbol is None and loaded_art.strategy.universe.symbols:
                target_symbol = loaded_art.strategy.universe.symbols[0]

        trades = self.get_closed_trades(symbol=target_symbol, candidate_id=target_cand_id)

        meta = self.resolve_candidate_metadata(
            candidate_id=target_cand_id,
            symbol=target_symbol,
            candidate_artifact=loaded_art,
            candidate_artifact_hash=candidate_artifact_hash,
            bundle_hash=bundle_hash,
            dataset_registry_hash=dataset_registry_hash,
            policy=active_policy,
            trades=trades,
        )

        candidate_trades = [t for t in trades if t.candidate_id == meta.candidate_id]
        logger.debug(
            "Extracted %d trades for candidate %s on symbol %s (total trades in ledger: %d)",
            len(candidate_trades),
            meta.candidate_id,
            meta.symbol,
            len(trades),
        )
        metrics = calculate_performance_metrics(candidate_trades)
        all_gates = self.evaluate_gates(metrics, policy=active_policy)
        failed_gates = tuple(
            sorted((g for g in all_gates if not g.passed), key=lambda g: g.gate_id)
        )

        if not failed_gates:
            logger.info(
                "Candidate %s meets all paper qualification criteria; zero breaches.",
                meta.candidate_id,
            )
            return None

        failure_reason_codes = tuple(sorted({gate.reason_code for gate in failed_gates}))
        qualification_hash = compute_feedback_qualification_hash(
            candidate_id=meta.candidate_id,
            candidate_artifact_hash=meta.candidate_artifact_hash,
            bundle_hash=meta.bundle_hash,
            dataset_registry_hash=meta.dataset_registry_hash,
            qualification_policy_id=meta.qualification_policy_id,
            failed_gates=failed_gates,
        )

        feedback = CreatorQualificationFailureFeedback(
            candidate_id=meta.candidate_id,
            candidate_artifact_hash=meta.candidate_artifact_hash,
            bundle_hash=meta.bundle_hash,
            dataset_registry_hash=meta.dataset_registry_hash,
            qualification_hash=qualification_hash,
            qualification_policy_id=meta.qualification_policy_id,
            failed_gates=failed_gates,
            failure_reason_codes=failure_reason_codes,
            data_source="cached_only",
            exchange_access=False,
            promotion_state="unpromoted",
            paper_activation=False,
            execution_authority=False,
        )
        return feedback


def extract_paper_feedback(
    *,
    ledger_path: Path | str,
    lifecycle_path: Path | str | None = None,
    symbol: str | None = None,
    candidate_id: str | None = None,
    candidate_artifact: CreatorCandidateArtifact | None = None,
    candidate_artifact_path: Path | str | None = None,
    candidate_artifact_hash: str | None = None,
    policy: PaperQualificationPolicy | None = None,
    bundle_hash: str | None = None,
    dataset_registry_hash: str | None = None,
    candidates_dir: Path | str | None = None,
) -> CreatorQualificationFailureFeedback | None:
    """Convenience functional API to extract failure feedback from a paper ledger."""
    extractor = PaperFeedbackExtractor(
        storage_path=ledger_path,
        lifecycle_path=lifecycle_path,
        policy=policy,
        candidates_dir=candidates_dir,
    )
    return extractor.extract(
        symbol=symbol,
        candidate_id=candidate_id,
        candidate_artifact=candidate_artifact,
        candidate_artifact_path=candidate_artifact_path,
        candidate_artifact_hash=candidate_artifact_hash,
        bundle_hash=bundle_hash,
        dataset_registry_hash=dataset_registry_hash,
        policy=policy,
    )


__all__ = [
    "DEFAULT_CANDIDATE_SEARCH_PATHS",
    "PaperFeedbackExtractor",
    "PaperQualificationPolicy",
    "ResolvedCandidateMetadata",
    "compute_feedback_qualification_hash",
    "extract_paper_feedback",
    "paper_qualification_policy_content_hash",
]
