from dataclasses import dataclass, field, asdict, replace
from typing import Optional
import numpy as np
import pandas as pd
from market import OptionPricingModel


@dataclass
class Configuration:
    S0: float = 100.0  
    K: float = 100.0
    T: float = 0.25
    option_type: str = "call"
    simulation_horizon: float = 1.0

    # Market parameters (gbm or jump diffusion)
    price_path_model: str = "geometric_brownian_motion"
    mean_drift: float = 0.05
    volatility: float = 0.2
    lambda_: float = 1.0
    jump_mean: float = -0.05
    jump_volatility: float = 0.1

    # Option pricing model parameters (BSM or Merton jump diffusion)
    option_pricing_model: str = "black_scholes_merton"
    r: float = 0.05
    q: float = 0.0
    # Can add a separate pricing volatility to determine the effect of misestimating volatility. Doing so will no longer make the pricing model accurate 
    # even when it matches the underlying price path model.
    pricing_volatility: Optional[float] = 0.2


    # Market Making parameters
    half_spread: float = 0.1
    quote_size: int = 1
    fill_probability: float = 0.5
    risk_aversion: float = 0.02

    # Delta Hedged life to expiry of the contract (in order to realize P&L as soon as the trade is made)
    nr_of_hedge_steps: int = 30

    # Simulation parameters
    ticks: int = 250
    seed: Optional[int] = None

    def get_pricing_volatility(self) -> float:
        if self.pricing_volatility is not None:
            return self.pricing_volatility
        else:
            return self.volatility


@dataclass
class SimulationResults:
    t: list = field(default_factory=list)        # creates a new list for each instance
    S: list = field(default_factory=list)
    bid: list = field(default_factory=list)
    ask: list = field(default_factory=list)
    model_price: list = field(default_factory=list)
    true_price: list = field(default_factory=list)
    cumulative_volume: list = field(default_factory=list)
    average_trade_pnl: list = field(default_factory=list)
    cumulative_fills: list = field(default_factory=list)
    average_fill_pnl: list = field(default_factory=list)
    realized_pnl: list = field(default_factory=list)
    model_marked_to_market: list = field(default_factory=list)
    true_marked_to_market: list = field(default_factory=list)
    buy_fills: list = field(default_factory=list)
    sell_fills: list = field(default_factory=list)
    trade_examples: list = field(default_factory=list)
    buy_realized_pnl: float = 0.0
    sell_realized_pnl: float = 0.0

    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# True model for the underlying price path
def true_price_path_simulation(config: Configuration, random_: np.random.Generator) -> np.ndarray:
    n = config.ticks
    dt = config.simulation_horizon / n
    S = np.empty(n + 1)
    S[0] = config.S0
    k = np.exp(config.jump_mean + 0.5 * config.jump_volatility**2) - 1
    for i in range(n):
        Z = random_.normal()
        drift = (config.mean_drift - 0.5 * config.volatility**2) * dt
        diffusion = config.volatility * np.sqrt(dt) * Z
        log_move = drift + diffusion
        if config.price_path_model == "merton_jump_diffusion":              # Adds the jump component to the price path if the model is Merton jump diffusion.)
            n_jumps = random_.poisson(config.lambda_ * dt)                  # For Poisson distribution, mu = lamdba and variance = lambda
            if n_jumps > 0:
                jump = random_.normal(config.jump_mean*n_jumps, config.jump_volatility*np.sqrt(n_jumps))        # If there is more than 1 jump at a single step, the aggregate log jump siuze is normally
            else:                                                                                               # distributed with mean = mean_jump * n_jumps and std = sigma_jump * sqrt(n_jumps), no need to simulate each jump individually.
                jump = 0.0
            log_move += jump - config.lambda_ * k * dt

        S[i + 1] = S[i] * np.exp(log_move)

    return S


def path_model_pricer(config: Configuration) -> OptionPricingModel:
    if config.price_path_model == "merton_jump_diffusion":
        return OptionPricingModel(name="merton_jump_diffusion", r = config.r,  lambda_ = config.lambda_, mean_jump = config.jump_mean, sigma_jump = config.jump_volatility, q = config.q)
    elif config.price_path_model == "geometric_brownian_motion":
        return OptionPricingModel(name = "black_scholes_merton", r = config.r, q = config.q)
    else:
        raise ValueError("Pricing model must be either 'merton_jump_diffusion' or 'black_scholes_merton'.")


#Identical to pricer above but prices according to the selected option pricing model (chosen by the market maker)
def market_maker_pricer(config: Configuration) -> OptionPricingModel:
    if config.option_pricing_model == "merton_jump_diffusion":
        return OptionPricingModel(name="merton_jump_diffusion", r = config.r,  lambda_ = config.lambda_, mean_jump = config.jump_mean, sigma_jump = config.jump_volatility, q = config.q)
    elif config.option_pricing_model == "black_scholes_merton":
        return OptionPricingModel(name = "black_scholes_merton", r = config.r, q = config.q)
    else:
        raise ValueError("Pricing model must be either 'merton_jump_diffusion' or 'black_scholes_merton'.")



def option_life_simulation(config: Configuration, Starting_spot: float, random_: np.random.Generator) -> np.ndarray:
    m = max(1, int(config.nr_of_hedge_steps))
    dt_hedging = config.T / m
    S = np.empty(m + 1)
    S[0] = Starting_spot
    k = np.exp(config.jump_mean + 0.5 * config.jump_volatility ** 2) -1.0

    for j in range(m):
        log_move = ((config.mean_drift - 0.5 * config.volatility ** 2) * dt_hedging + config.volatility * np.sqrt(dt_hedging) * random_.standard_normal())
        if config.price_path_model == "merton_jump_diffusion":
            n_jumps = random_.poisson(config.lambda_ * dt_hedging)
            if n_jumps > 0:
                log_move += random_.normal(config.jump_mean*n_jumps, config.jump_volatility*np.sqrt(n_jumps))
            log_move -= config.lambda_ * k * dt_hedging         # Jump Compensator to ensure that mean drift remains the instantaneous expected percentage growth rate, despite presence of jumps
        S[j + 1] = S[j] * np.exp(log_move)
    return S



def trade_profit_and_loss(config: Configuration, market_maker: OptionPricingModel, market_maker_sigma: float, Starting_spot: float, premium: float, side: str, quantity: float, random_: np.random.Generator, trace: Optional[dict] = None) -> float:
    m = max(1, int(config.nr_of_hedge_steps))
    dt_hedging = config.T / m
    r = config.r
    growth = np.exp(r * dt_hedging)

    path = option_life_simulation(config, Starting_spot, random_)

    if side =="buy":
        signed_trade_qty = quantity
    else:
        signed_trade_qty = -quantity

    if side == "buy":
        pnl = (-premium * quantity)
    else:
        pnl = (premium * quantity) 

    if trace is not None:
        trace["premium_pv"] = float(pnl)
        trace["rows"] = []

    for j in range(m):
        steps_remaining = config.T - j*dt_hedging
        delta = market_maker.delta(path[j], config.K, market_maker_sigma, steps_remaining, config.option_type)
        h = -signed_trade_qty * delta
        dividend_cash = (h * config.q * 0.5 * (path[j] + path [j + 1]) * dt_hedging)
        step_pnl = (h * (path[j + 1] - path[j] * growth) + dividend_cash)
        discount = np.exp(-r * ((j + 1) * dt_hedging))
        pnl += discount * step_pnl
        if trace is not None:
            trace["rows"].append({
                "time": float((j + 1) * dt_hedging),
                "spot_start": float(path[j]),
                "spot_end": float(path[j + 1]),
                "delta": float(delta),
                "hedge_shares": float(h),
                "stock_move_pv": float(discount * h * (path[j + 1] - path[j])),
                "funding_pv": float(-discount * h * path[j] * (growth - 1)),
                "dividend_pv": float(discount * dividend_cash),
                "step_pnl_pv": float(discount * step_pnl),
            })

    if config.option_type == "call":
        payoff = max(path[m] - config.K, 0.0)
    else:
        payoff = max(config.K - path[m], 0.0)
    payoff_pv = np.exp(-r * config.T) * signed_trade_qty * payoff
    pnl += payoff_pv

    if trace is not None:
        trace["payoff_pv"] = float(payoff_pv)
        trace["total_pnl"] = float(pnl)

    return float(pnl)


def simulation(config: Configuration, capture_trade_examples: int = 0) -> SimulationResults:
    random_ = np.random.default_rng(config.seed)
    S = true_price_path_simulation(config, random_)
    n = config.ticks
    dt = config.simulation_horizon / n
    market_maker = market_maker_pricer(config)  
    truth = path_model_pricer(config)
    market_maker_sigma = config.get_pricing_volatility()
    results = SimulationResults()

    realized = 0.0
    expected_model = 0.0
    expected_truth = 0.0
    cumulative_bought = 0.0
    cumulative_sold = 0.0
    fill_count = 0

    for i in range(n + 1):
        t = i * dt
        St = S[i]

        value_model = market_maker.price(St, config.K, market_maker_sigma, config.T, config.option_type)
        value_truth = truth.price(St, config.K, config.volatility, config.T, config.option_type)

        bid = max(0.0, value_model - config.half_spread)
        ask = value_model + config.half_spread

        total_contracts = cumulative_bought + cumulative_sold
        results.t.append(t)
        results.S.append(float(St))
        results.bid.append(float(bid))
        results.ask.append(float(ask))
        results.model_price.append(float(value_model))
        results.true_price.append(float(value_truth))
        results.cumulative_volume.append(float(total_contracts))
        results.average_trade_pnl.append(float(realized / total_contracts) if total_contracts else None)
        results.cumulative_fills.append(fill_count)
        results.average_fill_pnl.append(float(realized / fill_count) if fill_count else None)
        results.realized_pnl.append(float(realized))
        results.model_marked_to_market.append(float(expected_model))
        results.true_marked_to_market.append(float(expected_truth))
        results.buy_fills.append(float(cumulative_bought))
        results.sell_fills.append(float(cumulative_sold))

        if i == n:
            break

        p = float(np.clip(config.fill_probability * config.quote_size, 0.0, 1.0))
        ask_lifted = random_.random() < p 
        bid_hit = (random_.random() < p) if bid > 0 else False

        if ask_lifted:
            fill_count += 1
            cumulative_sold += config.quote_size
            expected_model += (ask - value_model) * config.quote_size
            expected_truth += (ask - value_truth) * config.quote_size
            trade_trace = {} if len(results.trade_examples) < capture_trade_examples else None
            trade_pnl = trade_profit_and_loss(config, market_maker, market_maker_sigma, St, ask, "sell", config.quote_size, random_, trade_trace)
            realized += trade_pnl
            results.sell_realized_pnl += trade_pnl
            if trade_trace is not None:
                results.trade_examples.append({"quote_index": i, "quote_time": float(t), "side": "sell", "quantity": config.quote_size, "premium": float(ask), "starting_spot": float(St), "pnl": trade_pnl, "trace": trade_trace})

        if bid_hit:
            fill_count += 1
            cumulative_bought += config.quote_size
            expected_model += (value_model - bid) * config.quote_size
            expected_truth += (value_truth - bid) * config.quote_size
            trade_trace = {} if len(results.trade_examples) < capture_trade_examples else None
            trade_pnl = trade_profit_and_loss(config, market_maker, market_maker_sigma, St, bid, "buy", config.quote_size, random_, trade_trace)
            realized += trade_pnl
            results.buy_realized_pnl += trade_pnl
            if trade_trace is not None:
                results.trade_examples.append({"quote_index": i, "quote_time": float(t), "side": "buy", "quantity": config.quote_size, "premium": float(bid), "starting_spot": float(St), "pnl": trade_pnl, "trace": trade_trace})

    finalize_summary(config, results)
    
    return results       


def finalize_summary(config: Configuration, results: SimulationResults) -> None:
    realized = np.asarray(results.realized_pnl)
    expected_model = np.asarray(results.model_marked_to_market)
    expected_truth = np.asarray(results.true_marked_to_market)
    total_fills = results.buy_fills[-1] + results.sell_fills[-1]        # Last value 
    expected_value = total_fills * config.half_spread
    change_pnl = np.diff(realized)
    pnl_step_vol = float(np.std(change_pnl))         # No fallback in case change_pnl doesnt exist
    average_edge = float(realized[-1] / total_fills) if total_fills > 0 else None

    results.summary = {
        "final_realized_pnl": float(realized[-1]),
        "final_expected_model": float(expected_model[-1]),
        "final_expected_truth": float(expected_truth[-1]),
        "model_vs_truth": float(expected_model[-1] - expected_truth[-1]),
        "realized_vs_truth": float(realized[-1] - expected_truth[-1]),
        "total_contracts_traded": float(total_fills),
        "total_fills": results.cumulative_fills[-1],
        "average_pnl_per_fill": results.average_fill_pnl[-1],
        "total_contracts_bought": float(results.buy_fills[-1]),
        "total_contracts_sold": float(results.sell_fills[-1]),
        "buy_realized_pnl": results.buy_realized_pnl,
        "sell_realized_pnl": results.sell_realized_pnl,
        "expected_spread_captured": float(expected_value),
        "average_realized_edge": average_edge,
        "half_spread": float(config.half_spread),
        "pnl_step_volatilty": pnl_step_vol,
        "realized_max_drawdown": float(max_drawdown(realized)),
        "models_match": config.option_pricing_model == ("merton_jump_diffusion" if config.price_path_model == "merton_jump_diffusion" else "black_scholes_merton"),
        "option_pricing_model": config.option_pricing_model,
        "price_path_model": config.price_path_model
    }


def max_drawdown(series: np.ndarray) -> float:
    if series.size == 0:
        return 0.0
    running_max = np.maximum.accumulate(series)
    drawdowns = running_max - series
    return float(np.max(drawdowns))


def simulate_paths(config: "Configuration", model: str, n_paths: int, random_: np.random.Generator) -> np.ndarray:
    n = config.ticks
    dt = config.T / n
    drift = (config.mean_drift - 0.5 * config.volatility ** 2) * dt
    diffusion = config.volatility * np.sqrt(dt) * random_.standard_normal((n_paths, n))
    log_increase = drift + diffusion
    
    if model == "merton_jump_diffusion":
        k = np.exp(config.jump_mean + 0.5 * config.jump_volatility ** 2) - 1.0
        n_jumps = random_.poisson(config.lambda_ * dt, size = (n_paths, n))
        jump = (n_jumps * config.jump_mean + np.sqrt(n_jumps) * config.jump_volatility * random_.standard_normal((n_paths, n)))
        log_increase += jump - config.lambda_ * k * dt

    log_paths = np.cumsum(log_increase, axis = 1)
    log_paths = np.hstack([np.zeros((n_paths, 1)), log_paths])

    return config.S0 * np.exp(log_paths)


def distribution(returns: np.ndarray) -> dict:
    returns = np.asarray(returns, dtype=float)
    mean = float(np.mean(returns))
    std = float(np.std(returns))
    if std > 1e-12:
        z = (returns - mean) / std
        skewness = float(np.mean(z ** 3))
        excess_kurtosis = float(np.mean(z ** 4) - 3.0)
    else:
        skewness = excess_kurtosis = 0.0
    return{
        "mean": mean,
        "std": std,
        "skewness": skewness,
        "excess_kurtosis": excess_kurtosis,
        "worst_return": float(np.min(returns)),
        "best_return": float(np.max(returns)),
        "VaR_1%": float(np.percentile(returns, 1.0))
    }


def return_destribution(config: "Configuration", n_paths: int = 10000, n_sample_paths: int = 8, n_bins: int =70) -> dict:
    random_ = np.random.default_rng(config.seed)
    n = config.ticks
    dt = config.T / n
    time_grid = [i * dt for i in range(n + 1)]

    out: dict = {"t": time_grid, "models": {}}
    all_returns = []

    for model in ("geometric_brownian_motion", "merton_jump_diffusion"):
        paths = simulate_paths(config, model, n_paths, random_)
        terminal_returns = paths[:, -1] / config.S0 - 1.0
        all_returns.append(terminal_returns)
        out["models"][model] = {
            "returns": terminal_returns.tolist(),
            "paths": paths[:n_sample_paths].tolist(),
            "stats": distribution(terminal_returns)
        }

    combined = np.concatenate(all_returns)
    low = float(np.percentile(combined, 0.3))
    high = float(np.percentile(combined, 99.7))
    pad = 0.05 * (high - low) if high > low else 0.01
    start, end = low - pad, high + pad
    out["bins"] = {"start": start, "end": end, "size": (end - start) / n_bins}
    out["n_paths"] = n_paths
    
    return out


if __name__ == "__main__":
    config = Configuration(
        price_path_model="merton_jump_diffusion",
        option_pricing_model="black_scholes_merton",
        half_spread=0.1,
        seed=None,
    )
    results = simulation(config)
    print(results.summary)




# SOD