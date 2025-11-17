# app.py
"""
zk_fee_profile: L1 gas statistics for ZK / soundness systems.

This script samples recent blocks from an EVM-compatible network via web3,
computes percentiles for base fee, effective gas price, and priority tip
(in Gwei), and prints a compact JSON object suitable as a public input
for ZK proofs (e.g. Aztec-style rollups, Zama research prototypes, or
other soundness-focused systems).
"""
import os
import sys
import json
import time
import argparse
import statistics
from typing import Dict, List, Tuple
from web3 import Web3

# ---------- Defaults ----------
DEFAULT_RPC = os.getenv("RPC_URL", "https://mainnet.infura.io/v3/your_api_key")
DEFAULT_BLOCKS = int(os.getenv("ZK_FEE_BLOCKS", "256"))
DEFAULT_STEP = int(os.getenv("ZK_FEE_STEP", "4"))

NETWORKS: Dict[int, str] = {
    1: "Ethereum Mainnet",
    11155111: "Sepolia Testnet",
    10: "Optimism",
    137: "Polygon",
    42161: "Arbitrum One",
    8453: "Base",
    43114: "Avalanche C-Chain",
}

# ---------- Small helpers ----------
def network_name(cid: int) -> str:
    return NETWORKS.get(cid, f"Unknown (chain ID {cid})")


def connect(rpc: str) -> Web3:
    """Connect to an RPC endpoint with a short latency log."""
    start = time.time()
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 25}))

    if not w3.is_connected():
        print(f"❌ Failed to connect to RPC endpoint: {rpc}", file=sys.stderr)
        sys.exit(1)

    latency = time.time() - start
    try:
        chain_id = int(w3.eth.chain_id)
        latest = int(w3.eth.block_number)
        print(
            f"🌐 Connected to {network_name(chain_id)} (chainId {chain_id}, tip={latest}) "
            f"in {latency:.2f}s",
            file=sys.stderr,
        )
    except Exception:
        print(f"🌐 Connected to RPC (chain info unavailable) in {latency:.2f}s", file=sys.stderr)

    return w3


def pct(values: List[float], q: float) -> float:
    """Return approximate percentile q (0..1) of a non-empty list of floats."""
    if not values:
        return 0.0
    q = max(0.0, min(1.0, q))
    sorted_vals = sorted(values)
    idx = int(round(q * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def sample_block_fees(block, base_fee_wei: int) -> Tuple[List[float], List[float]]:
    """
    Returns (effective_prices_gwei, tip_gwei_approx) for txs in the block.

    Approximation:
      - EIP-1559 tx (type 2):
          effective_gas_price = min(maxFeePerGas, baseFee + maxPriorityFeePerGas)
          tip ≈ maxPriorityFeePerGas
      - Legacy / other:
          effective_gas_price = gasPrice
          tip ≈ max(0, gasPrice - baseFee)
    """
    eff_gwei: List[float] = []
    tip_gwei: List[float] = []
    bf = base_fee_wei or 0

    for tx in block.transactions:
        # AttributeDict or dict
        if isinstance(tx, dict):
            ttype = tx.get("type", 0)
            gas_price = int(tx.get("gasPrice", 0) or 0)
            mpp = int(tx.get("maxPriorityFeePerGas", 0) or 0)
            mfp = int(tx.get("maxFeePerGas", 0) or 0)
        else:
            ttype = getattr(tx, "type", 0)
            gas_price = int(getattr(tx, "gasPrice", 0) or 0)
            mpp = int(getattr(tx, "maxPriorityFeePerGas", 0) or 0)
            mfp = int(getattr(tx, "maxFeePerGas", 0) or 0)

        if ttype == 2:
            effective_wei = min(mfp, bf + mpp)
            eff_gwei.append(float(Web3.from_wei(effective_wei, "gwei")))
            tip_gwei.append(float(Web3.from_wei(mpp, "gwei")))
        else:
            eff_gwei.append(float(Web3.from_wei(gas_price, "gwei")))
            tip_gwei.append(float(Web3.from_wei(max(0, gas_price - bf), "gwei")))

    return eff_gwei, tip_gwei


def analyze_fees(w3: Web3, blocks: int, step: int, head_override: int | None = None) -> Dict[str, object]:
    """
    Sample recent blocks backwards from 'head' and compute fee percentiles.
    This function is intentionally deterministic and compact so that its
    output can serve as a public input to ZK / soundness systems.
    """
    head = int(head_override) if head_override is not None else int(w3.eth.block_number)
    start_block = max(0, head - blocks + 1)
    basefees: List[float] = []
    eff_prices: List[float] = []
    tips: List[float] = []

    t0 = time.time()
    print(f"🔍 Sampling {blocks} recent blocks (every {step}th) from head={head}...", file=sys.stderr)

    sampled_blocks = 0
    for n in range(head, start_block - 1, -step):
        blk = w3.eth.get_block(n, full_transactions=True)
        bf_wei = int(getattr(blk, "baseFeePerGas", getattr(blk, "base_fee_per_gas", 0) or 0))
        basefees.append(float(Web3.from_wei(bf_wei, "gwei")))

        eff_gwei, tip_gwei = sample_block_fees(blk, bf_wei)
        eff_prices.extend(eff_gwei)
        tips.extend(tip_gwei)

        sampled_blocks += 1
        if sampled_blocks % 16 == 0:
            print(f"   ⏳ At block {n} (sampled {sampled_blocks})", file=sys.stderr)

    elapsed = time.time() - t0

    if sampled_blocks == 0:
        avg_block_time = 0.0
    else:
        try:
            newest = w3.eth.get_block(head)
            oldest = w3.eth.get_block(start_block)
            dt = int(newest.timestamp) - int(oldest.timestamp)
            span_blocks = max(1, head - start_block)
            avg_block_time = max(0.0, dt / span_blocks)
        except Exception:
            avg_block_time = 0.0

    def stats_bucket(values: List[float]) -> Dict[str, float | int]:
        if not values:
            return {"p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        return {
            "p50": round(statistics.median(values), 4),
            "p95": round(pct(values, 0.95), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "count": len(values),
        }

    chain_id = int(w3.eth.chain_id)
    return {
        "chainId": chain_id,
        "network": network_name(chain_id),
        "headBlock": head,
        "oldestBlock": start_block,
        "blockSpan": blocks,
        "sampledBlocks": sampled_blocks,
        "step": step,
        "avgBlockTimeSec": round(avg_block_time, 3),
        "timingSec": round(elapsed, 3),
        "baseFeeGwei": stats_bucket(basefees),
        "effectivePriceGwei": stats_bucket(eff_prices),
        "tipGweiApprox": stats_bucket(tips),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile recent gas behavior for ZK/soundness systems (base fee, effective price, tip).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--rpc", default=DEFAULT_RPC, help="RPC URL (default from RPC_URL env)")
    parser.add_argument("-b", "--blocks", type=int, default=DEFAULT_BLOCKS, help="How many recent blocks to scan")
    parser.add_argument("-s", "--step", type=int, default=DEFAULT_STEP, help="Sample every Nth block for speed")
    parser.add_argument("--head", type=int, help="Use this block number as head instead of latest")
    parser.add_argument("--json", action="store_true", help="JSON-only output (no human summary)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON with indentation")
    return parser.parse_args()


def main() -> None:
    if "your_api_key" in DEFAULT_RPC:
        print(
            "⚠️  RPC_URL is not set and DEFAULT_RPC still uses a placeholder Infura key. "
            "Set RPC_URL to a valid endpoint.",
            file=sys.stderr,
        )

    args = parse_args()
    if args.blocks <= 0 or args.step <= 0:
        print("❌ --blocks and --step must both be > 0", file=sys.stderr)
        sys.exit(1)

    print(f"📅 zk_fee_profile started at UTC {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}", file=sys.stderr)
    print(f"🔗 Using RPC endpoint: {args.rpc}", file=sys.stderr)

    w3 = connect(args.rpc)
    result = analyze_fees(w3, args.blocks, args.step, args.head)

    payload = {
        "mode": "zk_fee_profile",
        "generatedAtUtc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "data": result,
    }

    if args.pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    else:
        # Human summary + compact JSON (can be fed into ZK circuits / Aztec-style soundness verifiers)
        print(
            f"🌐 {result['network']} (chainId {result['chainId']}), "
            f"head={result['headBlock']} span={result['blockSpan']} "
            f"sampled={result['sampledBlocks']} step={result['step']}"
        )
        print(f"🕒 Avg block time: {result['avgBlockTimeSec']} s")
        bf = result["baseFeeGwei"]
        ep = result["effectivePriceGwei"]
        tp = result["tipGweiApprox"]
        print(
            f"⛽ Base fee (Gwei):    p50={bf['p50']}  p95={bf['p95']}  "
            f"min={bf['min']}  max={bf['max']}  n={bf['count']}"
        )
        print(
            f"💵 Effective price:    p50={ep['p50']}  p95={ep['p95']}  "
            f"min={ep['min']}  max={ep['max']}  n={ep['count']}"
        )
        print(
            f"🎁 Priority tip ~:     p50={tp['p50']}  p95={tp['p95']}  "
            f"min={tp['min']}  max={tp['max']}  n={tp['count']}"
        )
        print("ℹ️  Output JSON below can be embedded as public input in ZK/soundness circuits.\n")
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))

    print(f"✅ Done in {result['timingSec']}s", file=sys.stderr)


if __name__ == "__main__":
    main()
