"""Local interactive dashboard for the options market-making simulator.

Run ``python dashboard.py`` and open http://127.0.0.1:5001.
The single-run replay uses a completed simulation. The comparison streams
completed seed runs; neither view streams a live market.
"""

from __future__ import annotations

from dataclasses import asdict, fields, replace
import json
import math
import secrets

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
import numpy as np
from scipy.stats import poisson

from market_making_simulation import Configuration, path_model_pricer, simulation


app = Flask(__name__)

MODELS = {
    "price_path_model": {"geometric_brownian_motion", "merton_jump_diffusion"},
    "option_pricing_model": {"black_scholes_merton", "merton_jump_diffusion"},
    "option_type": {"call", "put"},
}

# These bounds keep a browser request finite and avoid invalid log/Poisson inputs.
NUMBERS = {
    "S0": (1.0, 10_000.0),
    "K": (1.0, 10_000.0),
    "T": (0.01, 3.0),
    "simulation_horizon": (0.01, 3.0),
    "mean_drift": (-0.5, 0.5),
    "volatility": (0.001, 1.0),
    "lambda_": (0.0, 5.0),
    "jump_mean": (-1.0, 1.0),
    "jump_volatility": (0.0, 0.7),
    "r": (-0.1, 0.3),
    "q": (-0.1, 0.3),
    "half_spread": (0.0, 50.0),
    "fill_probability": (0.0, 1.0),
}
INTEGERS = {"quote_size": (1, 20), "nr_of_hedge_steps": (1, 40), "ticks": (10, 300)}
ALLOWED_FIELDS = {field.name for field in fields(Configuration)}


def _finite_number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}.")
    return number


def _integer(value, name: str, low: int, high: int) -> int:
    number = _finite_number(value, name, low, high)
    if not number.is_integer():
        raise ValueError(f"{name} must be a whole number.")
    return int(number)


def config_from_payload(data: dict) -> Configuration:
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with simulation settings.")
    unknown = set(data) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"Unknown setting: {sorted(unknown)[0]}.")

    values = asdict(Configuration())
    for name, choices in MODELS.items():
        value = data.get(name, values[name])
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}.")
        values[name] = value
    for name, (low, high) in NUMBERS.items():
        values[name] = _finite_number(data.get(name, values[name]), name, low, high)
    for name, (low, high) in INTEGERS.items():
        values[name] = _integer(data.get(name, values[name]), name, low, high)

    pricing_volatility = data.get("pricing_volatility", values["pricing_volatility"])
    values["pricing_volatility"] = None if pricing_volatility in (None, "") else _finite_number(
        pricing_volatility, "pricing_volatility", 0.001, 1.0
    )
    seed = data.get("seed", values["seed"])
    values["seed"] = None if seed in (None, "") else _integer(seed, "seed", 0, 2**32 - 1)

    # This field is retained for API compatibility. The simulator does not use it.
    values["risk_aversion"] = _finite_number(
        data.get("risk_aversion", values["risk_aversion"]), "risk_aversion", 0.0, 10.0
    )
    return Configuration(**values)


def validate_simulation_workload(config: Configuration) -> None:
    if config.option_pricing_model != "merton_jump_diffusion" or config.lambda_ == 0:
        return
    transformed_intensity = config.lambda_ * math.exp(
        config.jump_mean + 0.5 * config.jump_volatility**2
    )
    series_terms = int(poisson.ppf(1 - 1e-12, transformed_intensity * config.T)) + 1
    if config.ticks * config.nr_of_hedge_steps * series_terms > 150_000:
        raise ValueError("This Merton run is too large for the interactive dashboard. Reduce quote ticks, hedge steps, jump intensity, or option life.")


def add_reference_delta_exposure(config: Configuration, result) -> None:
    """Annotate captured hedge steps with reference-model delta diagnostics."""
    reference_pricer = path_model_pricer(config)
    hedge_interval = config.T / config.nr_of_hedge_steps
    for trade in result.trade_examples:
        signed_quantity = trade["quantity"] if trade["side"] == "buy" else -trade["quantity"]
        for index, row in enumerate(trade["trace"]["rows"]):
            time_remaining = config.T - index * hedge_interval
            reference_delta = reference_pricer.delta(
                row["spot_start"], config.K, config.volatility, time_remaining, config.option_type
            )
            row["reference_delta"] = float(reference_delta)
            row["reference_residual_shares"] = float(
                signed_quantity * reference_delta + row["hedge_shares"]
            )


@app.get("/")
def index():
    return render_template("index.html", defaults=asdict(Configuration()))


@app.post("/api/simulate")
def simulate_api():
    try:
        config = config_from_payload(request.get_json(silent=True))
        validate_simulation_workload(config)
        result = simulation(config, capture_trade_examples=8)
        add_reference_delta_exposure(config, result)
        return jsonify({"config": asdict(config), "result": result.to_dict()})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (OverflowError, FloatingPointError) as exc:
        return jsonify({"error": f"The selected parameters produced a numerical error: {exc}"}), 400


def multi_run_settings(data: dict) -> tuple[Configuration, list[int]]:
    if not isinstance(data, dict):
        raise ValueError("Send a JSON object with simulation settings.")
    config = config_from_payload({key: value for key, value in data.items() if key != "seeds"})
    validate_simulation_workload(config)
    config = replace(config, seed=None)
    if "seeds" in data:
        provided = data["seeds"]
        if not isinstance(provided, list) or len(provided) != 40:
            raise ValueError("Reused seeds must be a list of 40 distinct integers.")
        seeds = [_integer(seed, "seed", 0, 2**32 - 1) for seed in provided]
        if len(set(seeds)) != 40:
            raise ValueError("Reused seeds must be distinct.")
    else:
        seeds = []
        while len(seeds) < 40:
            candidate = secrets.randbits(32)
            if candidate not in seeds:
                seeds.append(candidate)
    return config, seeds


def multi_run_record(config: Configuration, seed: int) -> dict:
    run = simulation(replace(config, seed=seed))
    return {
        "seed": seed,
        "pnl": run.realized_pnl,
        "contracts": run.summary["total_contracts_traded"],
        "buy_contracts": run.summary["total_contracts_bought"],
        "sell_contracts": run.summary["total_contracts_sold"],
        "buy_pnl": run.summary["buy_realized_pnl"],
        "sell_pnl": run.summary["sell_realized_pnl"],
    }


def multi_run_summary(config: Configuration, seeds: list[int], records: list[dict]) -> dict:
    average_pnl = np.mean([record["pnl"] for record in records], axis=0).tolist()
    total_contracts = sum(record["contracts"] for record in records)
    buy_contracts = sum(record["buy_contracts"] for record in records)
    sell_contracts = sum(record["sell_contracts"] for record in records)
    return {
        "seeds": seeds,
        "paths": [{"seed": record["seed"], "pnl": record["pnl"]} for record in records],
        "average_pnl": average_pnl,
        "mean_final_pnl": average_pnl[-1],
        "average_pnl_per_contract": sum(record["pnl"][-1] for record in records) / total_contracts if total_contracts else None,
        "average_buy_pnl_per_contract": sum(record["buy_pnl"] for record in records) / buy_contracts if buy_contracts else None,
        "average_sell_pnl_per_contract": sum(record["sell_pnl"] for record in records) / sell_contracts if sell_contracts else None,
        "total_contracts": total_contracts,
        "loss_runs": sum(record["pnl"][-1] < 0 for record in records),
        "half_spread": config.half_spread,
    }


@app.post("/api/multi-run")
def multi_run_api():
    try:
        config, seeds = multi_run_settings(request.get_json(silent=True))
        records = [multi_run_record(config, seed) for seed in seeds]
        return jsonify({"config": asdict(config), "result": multi_run_summary(config, seeds, records)})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (OverflowError, FloatingPointError) as exc:
        return jsonify({"error": f"The selected parameters produced a numerical error: {exc}"}), 400


@app.post("/api/multi-run/stream")
def multi_run_stream_api():
    try:
        config, seeds = multi_run_settings(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except (OverflowError, FloatingPointError) as exc:
        return jsonify({"error": f"The selected parameters produced a numerical error: {exc}"}), 400

    def events():
        yield json.dumps({"type": "start", "config": asdict(config), "seeds": seeds}) + "\n"
        for index, seed in enumerate(seeds, 1):
            try:
                record = multi_run_record(config, seed)
                yield json.dumps({"type": "run", "index": index, "record": record}, allow_nan=False) + "\n"
            except (ValueError, OverflowError, FloatingPointError) as exc:
                yield json.dumps({"type": "error", "error": f"Seed {seed} failed: {exc}"}) + "\n"
                return
        yield json.dumps({"type": "done"}) + "\n"

    return Response(stream_with_context(events()), mimetype="application/x-ndjson", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no"
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
