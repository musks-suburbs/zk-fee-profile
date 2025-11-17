## Overview
zk-fee-profile is a small command-line tool that connects to an EVM-compatible network via web3.py, samples recent blocks, and computes percentiles for:
- Base fee (Gwei)
- Effective gas price (Gwei)
- Priority tip (approximate, Gwei)

The output is returned as a compact JSON object that is intentionally simple and deterministic so that it can be used as a public input to zero-knowledge or soundness-oriented systems, such as:
- Aztec-style L2 rollups or privacy layers
- Zama-style research prototypes using homomorphic or ZK techniques
- Custom soundness verifiers or gas-cost bounds embedded in ZK circuits
- Monitoring tools that need a reproducible gas profile snapshot

## Files
This repository contains exactly two files:
1. app.py — the main script implementing zk-fee-profile.
2. README.md — this documentation.

## Requirements
- Python 3.10 or newer
- A working RPC endpoint for an EVM-compatible network (Ethereum, Polygon, etc.)
- Internet connectivity to reach the RPC node

## Installation
1. Install Python 3.10+ on your system.
2. Install the required Python dependency web3:
   pip install web3
3. Set the RPC_URL environment variable to point to your node or provider, for example an Infura, Alchemy, or self-hosted Ethereum JSON-RPC endpoint.
4. Optionally, adjust the defaults via environment variables:
   - ZK_FEE_BLOCKS: number of recent blocks to consider (default 256)
   - ZK_FEE_STEP: sample every Nth block (default 4)

If RPC_URL is not set, the script uses a placeholder Infura URL with your_api_key. You must replace this with a real key or your own node, otherwise the connection will fail.

## Usage
The script is executed as a standard Python CLI tool. From the root of the repository:

Basic run with defaults:
   python app.py

Specify a custom RPC endpoint:
   python app.py --rpc https://your-rpc-endpoint

Limit block scan range and sampling step:
   python app.py --blocks 512 --step 8

Pin the head block (useful for reproducible ZK proof inputs):
   python app.py --head 19000000

JSON-only output (no human summary, minified JSON):
   python app.py --json

Pretty JSON output for debugging or inspection:
   python app.py --pretty

You can combine flags, for example:
   python app.py --rpc https://your-rpc --blocks 512 --step 4 --pretty

## Output and ZK / Soundness Context
The tool produces three kinds of information:

1. Logging to stderr:
   - Connection status and latency.
   - Sampling progress.
   - Final timing information.

2. Human-readable summary (when neither --json nor --pretty is used):
   - Network name and chainId.
   - Head block and span of blocks scanned.
   - Average block time estimate.
   - Percentiles (p50, p95, min, max, count) for base fee, effective price, and tip in Gwei.

3. Machine-readable JSON payload:
   - mode: always "zk_fee_profile".
   - generatedAtUtc: timestamp in UTC.
   - data: structured object with:
     - chainId and network.
     - headBlock, oldestBlock, blockSpan, sampledBlocks, step.
     - avgBlockTimeSec and timingSec.
     - baseFeeGwei: p50, p95, min, max, count.
     - effectivePriceGwei: same statistics as baseFeeGwei.
     - tipGweiApprox: same statistics as baseFeeGwei.

This JSON block is designed to be:
- Stable: only depends on the blocks actually scanned and the parameters (blocks, step, head).
- Compact: easy to embed as a single public input into a ZK circuit or soundness checker.
- Agnostic: can be used by any ZK proving stack (Plonkish, STARKs, Aztec-like setups, Zama experiments, etc.).

## How It Works Internally
1. The script connects to the RPC endpoint using web3.py with a small timeout and logs the connection latency and current chain tip.
2. It determines the head block (either the latest or a user-specified --head).
3. It scans backwards over the specified number of blocks, stepping by --step to reduce RPC load.
4. For each sampled block:
   - Reads the baseFeePerGas (where available).
   - Reads full transactions (full_transactions=True).
   - For EIP-1559 transactions (type 2):
     - Approximates effective gas price as min(maxFeePerGas, baseFee + maxPriorityFeePerGas).
     - Uses maxPriorityFeePerGas as the priority tip.
   - For legacy or other types:
     - Uses gasPrice as effective gas price.
     - Approximates tip as max(0, gasPrice - baseFee).
5. It collects all base fees, effective gas prices, and tip values in Gwei.
6. It computes median (p50), p95, min, max, and sample count for each metric.
7. It estimates average block time from the timestamps between the oldest and newest sampled blocks.
8. Finally, it returns and prints a deterministic JSON object.

## Expected Result
A typical human-readable run might show something like:
- Network and chainId.
- Sampling window, number of sampled blocks, and step used.
- Average block time estimate over the sampled period.
- Base fee percentiles and ranges in Gwei.
- Effective gas price percentiles and ranges in Gwei.
- Priority tip percentiles and ranges in Gwei.
- A JSON blob containing the same statistics, suitable for being embedded into:
  - An Aztec-style rollup proving system.
  - A Zama-based experiment for gas-cost distributions.
  - A custom soundness check that enforces gas-cost bounds inside a ZK circuit.

In JSON or pretty JSON mode, only the JSON payload is printed to stdout, making it easy to pipe into other tools or file storage.

## Notes and Limitations
- Accuracy vs speed: Sampling every Nth block with --step trades detail for reduced RPC calls. For high-precision analysis, use a small step such as 1 or 2. For quick overviews, a larger step is fine.
- EIP-1559 approximation: The effective gas price and tip estimation follows common conventions but may not perfectly match every client’s exact accounting. This is usually sufficient for fee profiling or as a high-level ZK input.
- Legacy and non-EIP-1559 networks: On chains without baseFeePerGas, the base fee will be reported as zero and tip approximations will be based on gasPrice alone.
- RPC trust: For soundness or ZK usage, the RPC is treated as a data source. In serious systems, you should either:
  - Use your own trusted node, or
  - Combine this script’s output with additional commitments or Merkle proofs that bind the gas profile to an L1 state root.
- Extensibility: You can adapt this script to:
  - Emit commitments (e.g. hash of the JSON payload) for on-chain soundness tracking.
  - Integrate directly into Aztec-like or Zama-like pipelines where gas distributions constrain proof or circuit behavior.

## Safety and Best Practices
- Do not hard-code private RPC keys into version control. Use environment variables for RPC_URL.
- When using this in a proof system, document the exact parameters (blocks, step, head) so the gas profile can be recomputed or verified independently.
- Consider archiving the JSON output alongside block numbers used, especially when pairing fee profiles with on-chain events or ZK proofs.

