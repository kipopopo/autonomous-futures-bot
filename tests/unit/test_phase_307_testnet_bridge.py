"""Unit tests for Phase 307: Binance Futures Testnet Live API Integration
& Order Dispatch Bridge.
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

from autonomous_futures.feed.testnet_bridge import (
    UPSTREAM_PHASE306_ROOT_HASH,
    BinanceTestnetCredentials,
    BinanceTestnetSigner,
    BridgeConnectionState,
    CentralizedSolvencyLedger,
    ExchangeFilterValidator,
    OrderDispatchLifecycle,
    OrderSide,
    TestnetOrderDispatchBridge,
    UserDataEventType,
    UserDataStreamManager,
    run_phase_307_simulation,
    verify_phase_307_merkle_dag,
)


def test_binance_testnet_credentials_and_masking() -> None:
    """Test credentials initialization and masked key protection."""
    creds = BinanceTestnetCredentials(
        api_key="1234567890abcdef1234567890abcdef",
        api_secret="abcdef1234567890abcdef1234567890",
        is_mock=False,
    )
    assert not creds.is_mock
    assert creds.masked_key == "1234****cdef"

    short_creds = BinanceTestnetCredentials(api_key="short", api_secret="sec")
    assert short_creds.masked_key == "****"

    env_creds = BinanceTestnetCredentials.from_env()
    assert env_creds.api_key
    assert env_creds.api_secret


def test_binance_testnet_signer_and_time_sync() -> None:
    """Test HMAC-SHA256 signature generation and clock drift synchronization."""
    creds = BinanceTestnetCredentials(
        api_key="test-api-key",
        api_secret="test-secret-key-12345",
        is_mock=True,
    )
    signer = BinanceTestnetSigner(credentials=creds)

    # Clock synchronization
    server_time = 1790233200000
    local_time = 1790233200015
    offset = signer.sync_server_time(server_time, local_time)
    assert offset == 15
    assert signer.clock_offset_ms == 15

    # Parameter signing
    params = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.001"}
    signed_params, signature = signer.sign_params(params, current_time_ms=local_time)

    assert "signature" in signed_params
    assert "timestamp" in signed_params
    assert signed_params["timestamp"] == server_time
    assert len(signature) == 64  # SHA-256 hex string

    # Signature verification
    params_copy = {k: v for k, v in signed_params.items() if k != "signature"}
    assert signer.verify_signature(params_copy, signature)


def test_exchange_filter_validator_clamping_and_rejections() -> None:
    """Test exchange filter validation for lot size, price filter, min notional and micro cap."""
    validator = ExchangeFilterValidator()

    # 1. Valid order within micro cap
    q_price, q_qty, notional, is_valid, err = validator.validate_and_clamp_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        target_price=Decimal("95000.00"),
        requested_notional=Decimal("5.00"),
    )
    assert is_valid
    assert err is None
    assert notional >= Decimal("5.00")
    assert notional <= Decimal("6.00")
    # Must adhere to BTC stepSize 0.00001
    assert q_qty % Decimal("0.00001") == Decimal("0")

    # 2. Reject out of bounds price
    _, _, _, is_valid_low, err_low = validator.validate_and_clamp_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        target_price=Decimal("500.00"),  # min is 1000.0
        requested_notional=Decimal("5.00"),
    )
    assert not is_valid_low
    assert "out of bounds" in str(err_low)

    # 3. Reject excessive price deviation (> 1.0%)
    _, _, _, is_valid_dev, err_dev = validator.validate_and_clamp_order(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        target_price=Decimal("2800.00"),
        requested_notional=Decimal("5.00"),
        mark_price=Decimal("2750.00"),  # > 1.8% deviation
    )
    assert not is_valid_dev
    assert "deviation" in str(err_dev).lower()

    # 4. Micro child cap clamping: requested $20.00 clamped to <= $5.00
    _, _, notional_clamped, is_valid_clamp, _ = validator.validate_and_clamp_order(
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        target_price=Decimal("185.00"),
        requested_notional=Decimal("20.00"),
    )
    assert is_valid_clamp
    assert notional_clamped <= Decimal("6.00")


def test_user_data_stream_manager() -> None:
    """Test listenKey lifecycle management and event logging."""
    manager = UserDataStreamManager()
    assert not manager.is_active

    key = manager.create_listen_key(current_time_ms=1000)
    assert manager.is_active
    assert key.startswith("lk-")
    assert manager.last_keepalive_ms == 1000

    success = manager.keepalive(current_time_ms=2000)
    assert success
    assert manager.last_keepalive_ms == 2000

    manager.teardown()
    assert not manager.is_active
    assert not manager.keepalive()


def test_testnet_order_dispatch_bridge_and_lifecycle() -> None:
    """Test order dispatch lifecycle from staging to simulated fill."""
    bridge = TestnetOrderDispatchBridge()
    server_time = 1790233200000
    local_time = 1790233200010
    connected = bridge.initialize_connection(server_time, local_time)
    assert connected
    assert bridge.connection_state == BridgeConnectionState.CONNECTED

    order = bridge.stage_and_dispatch_order(
        candidate_id="cand-btcusdt-dcb-002",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=Decimal("95100.0"),
        target_notional=Decimal("5.00"),
        timestamp_ms=local_time,
    )
    assert order.lifecycle == OrderDispatchLifecycle.FILLED.value
    assert order.notional_usdt <= 6.00
    assert order.tau_rtt_ms > 0.0
    assert order.fill_price is not None

    # Check that user data event was emitted
    assert len(bridge.stream_manager.events) == 1
    evt = bridge.stream_manager.events[0]
    assert evt.event_type == UserDataEventType.ORDER_TRADE_UPDATE.value
    assert evt.order_id == order.order_id


def test_centralized_solvency_ledger_zero_drift() -> None:
    """Test continuous double-entry zero-drift balance invariant."""
    ledger = CentralizedSolvencyLedger(starting_equity=Decimal("100.00"))
    assert ledger.is_zero_drift
    assert ledger.drift == Decimal("0.00")

    # Allocate margin
    margin_req = Decimal("5.00")
    allocated = ledger.allocate_order_margin(margin_req)
    assert allocated
    assert ledger.cash == Decimal("95.00")
    assert ledger.allocated_margin == Decimal("5.00")
    assert ledger.is_zero_drift

    # Reconcile fill with PnL and fee
    fee = Decimal("0.001")
    pnl = Decimal("0.05")
    ledger.reconcile_fill(margin_released=margin_req, realized_pnl_delta=pnl, fee_cost=fee)
    assert ledger.allocated_margin == Decimal("0.00")
    assert ledger.cash == Decimal("100.00") + pnl - fee
    assert ledger.is_zero_drift
    assert ledger.drift < Decimal("1e-15")


def test_phase_307_simulation_and_merkle_dag_verification() -> None:
    """Test full Phase 307 simulation runner and cryptographic Merkle verification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir)
        results = run_phase_307_simulation(
            output_dir=output_path,
            starting_equity=100.0,
            parent_merkle_root=UPSTREAM_PHASE306_ROOT_HASH,
        )

        assert results["verified"]
        assert results["status"] == "TESTNET_BRIDGE_VERIFIED"
        assert results["performance"]["total_orders_dispatched"] == 12
        assert results["upstream_hash"] == UPSTREAM_PHASE306_ROOT_HASH

        # Self-verify Merkle DAG
        is_valid = verify_phase_307_merkle_dag(
            output_dir=output_path,
            parent_merkle_root=UPSTREAM_PHASE306_ROOT_HASH,
        )
        assert is_valid
