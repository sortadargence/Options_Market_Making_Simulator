# Options Market-Making Simulator

This project simulates a market maker quoting a bid-ask spread on **European call or put options** and delta-hedging each fill. It compares two stock processes (Geometric Brownian Motion and Merton jump diffusion) with their corresponding option pricing models (Black-Scholes-Merton and Merton jump diffusion).

The dashboard shows how buying, selling, and hedging options affect each trade's P&L. It also compares the market maker's pricing and hedge deltas with a theoretical reference based on the simulated stock process, so you can inspect the exposure that remains when the pricing model and the price path models differ. That reference is a model calculation, not an observed market price.

## Project files

- `market.py` Calculates Black–Scholes–Merton prices and Greeks, and Merton jump-diffusion prices and deltas.
- `market_making_simulation.py` Generates quotes, simulates fills, hedges each filled option through expiry, and reports results (including P&L). It also samples terminal-return distributions for GBM and jump diffusion.
- `dashboard.py`, `templates/index.html`, and `static/` provide a local Flask dashboard for running and replaying experiments. Takes all the calculations from `market.py` and `market_making_simulation.py`.

## Simulation Settings

**Contract & market**
Option type: Call or Put: default = call
Stock Process (`price_path_model`): GBM or Merton Jumps -> Determines the true price path that the stock will follow
Initial stock price (`S0`): default = 100
Strike (`K`): default = 100
Option life (`T`) (in years): default = 0.25 -> Establishes the maturity of each freshly priced and posted option
Quote horizon (`simulation_horizon`)in years: default = 1 -> Establishes the time period of the simulation (will be divided by `Quote ticks` when determining each step of the simulation)
Stock drift (`mean_drift`): default = 0.05 -> drift term in both GBM and Merton-Jump price paths
Path volatility (`volatility`): default = 0.2 -> stock/diffusion volatility used in the GBM and Merton-Jump price paths 

**Jump process**
Jump intensity (`lambda_`): default = 1 -> expected number of jumps per year (expected number of jumps throughout the life of the option would be `lambda_*T`)
Mean log jump (`jump_mean`): default = -0.05 -> mean effect of the jump (used in the normal distribution to calculate the effect of the jump)
Jump (`jump_volatility`): default = 0.1 -> volatility of the jump (used in the normal distribution to calculate the effect of the jump)

**Maker model & quotes**
Pricing model (`option_pricing_model`): Black-Scholes-Merton or Merton jump diffusion -> the option pricing model used by the market maker
Use path volatility for maker pricing: toggle on or off -> when toggled on matches the pricing volatility to the path volatility to eliminate the effect of volatility misestimation
Pricing volatility (`pricing_volatility`): default: 0.2 -> volatility used by the market maker to price the option
Half Spread (`half_spread`): default: 0.1 -> half of the difference between the maker's bid and ask. Quoted edge relative to the market maker's model is this amount per filled contract. Realized average P&L can differ because of hedging error, model mismatch, and random variation.
Interest rate: default = 0.05 
Dividend yield (`q`): default = 0 -> continuous dividend yield supported by both BSM and Merton jump diffusion models.

**Execution & run**
Quote size (`quote_size`): default = 1 -> number of contracts of the selected option type quoted on each side per tick. A filled side executes the entire quote size and quote size also scales the side's fill probability.
Fill probability (`fill_probability`): default = 0.5 -> base probability for each quoted side. The bid and ask fill independently, each with probability `clip(fill_probability * quote_size, 0, 1)`. Can have scenarios where none fill, one fills and the other doesnt, or both fill.
Quote ticks (`ticks`): default = 250 -> number of quote opportunities in the simulation (one bid and one ask for the selected option type per tick)
Hedge steps (`nr_of_hedge_steps`): default = 30 -> the amount of times the hedge position for each contract will be rebalanced (also used for calculating per trade P&L)
Random seed: for reproducibility



## How a simulation works

1. A stock price path is simulated over `simulation_horizon` to set the spot price at each of `ticks` quote opportunities. `price_path_model` selects GBM or Merton jump diffusion (this represents the "true" price path the stock will follow)
2. Price a fresh option at every tick with `option_pricing_model`. Market maker posts `bid = model_price - half_spread` and `ask = model_price + half_spread`. 
3. Determine independently whether each bid and ask gets filled. Each side has probability `clip(fill_probability * quote_size, 0, 1)`. A fill executes the entire `quote_size`. This probability is fixed by the inputs and is not affected by the spread, quoted prices, or market conditions. The simplified fill model makes buys and sells equally likely, so pricing errors can offset in the aggregate. Realized average P&L still depends on hedging and the simulated paths.
4. For each fill, generate a **separate** stock path from the current spot through the option's life `T` (maturity). Hedge the signed option position with the model delta at `nr_of_hedge_steps` intervals. The P&L calculation finances stock holdings at rate `r`, approximates dividends on the holdings, and pays the discounted option payoff. All cash flows are accumulated and discounted at trade initiation so they can be recorded immediately.
5. Add the completed trade's discounted outcome to cumulative P&L.

The output's `true_price` is a theoretical reference price using the stock-path model and `volatility`. It is not an observed market price.

## Run it

The code requires Python, Flask, NumPy, SciPy, and pandas. 

```bash
python -m pip install -r requirements.txt
```

To open the interactive dashboard:

```bash
python dashboard.py
```

Open `http://127.0.0.1:5001` in a browser. The dashboard lets you set the contract, market process, pricing model and execution inputs, replay quotes, fills and cumulative outcomes, inspect hedge steps and reference-model delta exposure for the first eight filled trades and compare 40 seeded runs. The dashboard restricts input ranges and run sizes to keep requests responsive, but it does not remove the model limitations below.

To configure a simulation in Python and print its summary:

```python
from market_making_simulation import Configuration, simulation

config = Configuration(
    price_path_model="merton_jump_diffusion",
    option_pricing_model="black_scholes_merton",
    half_spread=0.1,
    seed=None,
)
results = simulation(config)
print(results.summary)
```

Running `python market_making_simulation.py` will print a simulation summary with a random seed. One possible summary for a random seed is shown below. With `seed=None`, values vary between runs. 

```text
{'final_realized_pnl': 24.752854828495124, 'final_expected_model': 24.600000000000065, 'final_expected_truth': 15.696712049618064, 'model_vs_truth': 8.903287950382001, 'realized_vs_truth': 9.05614277887706, 'total_contracts_traded': 246.0, 'total_fills': 246, 'average_pnl_per_fill': 0.1006213610914436, 'total_contracts_bought': 113.0, 'total_contracts_sold': 133.0, 'buy_realized_pnl': 51.34602786849734, 'sell_realized_pnl': -26.59317304000224, 'expected_spread_captured': 24.6, 'average_realized_edge': 0.1006213610914436, 'half_spread': 0.1, 'pnl_step_volatilty': 1.2904604108466826, 'realized_max_drawdown': 19.525756587288594, 'models_match': False, 'option_pricing_model': 'black_scholes_merton', 'price_path_model': 'merton_jump_diffusion'}
```


`Configuration` controls the initial spot `S0`, strike `K`, option life `T`, option type, quote horizon and ticks, stock drift and volatility, jump parameters, interest rate `r`, dividend yield `q`, quote size, fill probability, hedge frequency, and random seed. `pricing_volatility` controls the maker's pricing volatility. Set it to `None` to follow `volatility`. Its current default is `0.2`, so changing `volatility` alone does not change the maker's pricing volatility.

## Interpreting results

- `final_realized_pnl` sums completed trades' P&L, each discounted to its own initiation time. The sum is not discounted or compounded to one common portfolio date. `average_realized_edge` divides by contracts traded and is `None` when there are no fills.
- `final_expected_model` sums quoted edge relative to the maker's model price. With symmetric quotes it equals contracts traded times `half_spread`. `final_expected_truth` sums quoted edge relative to the reference model price. Neither is a forecast of realized hedging P&L.
- `average_trade_pnl` is cumulative banked P&L divided by `cumulative_volume` (the number of filled contracts). 
- `models_match` checks only the model families: GBM with BSM, or Merton jump diffusion with Merton jump diffusion. It does not check whether the path and maker pricing volatilities agree.

## 40-seed comparison

The dashboard runs the current configuration with 40 distinct random seeds, ignoring the single-run seed field. It adds each completed run's cumulative P&L curve to the chart and updates the mean curve as runs finish. Select **Reuse previous 40 seeds** to repeat a batch. The metrics include loss-making runs, mean final P&L, and total final P&L divided by all filled contracts across the completed runs. The mean curve averages the run curves at each tick. The per-contract metric pools contracts, so runs with more fills have more weight. Symmetric independent bid and ask fills can make aggregate average P&L per contract close to the half spread even with mismatched models. That outcome is not guaranteed: finite samples, volatility mismatch, and discrete hedging can move realized P&L away from it.

## Assumptions and limitations

1. **There is no live inventory.** Each fill has its own future path and is completed before its outcome is banked. Opposite-side fills at the same quote tick do not need to cancel.
2. **Pricing assumes a particular jump-risk treatment.** The stock path uses `mean_drift` as its stock-price drift, while option pricing uses `r` and `q`. The reference jump pricer uses the same jump frequency and size distribution as the simulated path, so it does not include a separate jump-risk premium. Dividend cash on hedging shares is approximated from the stock prices at the ends of each hedge interval.
3. **Trading frictions are omitted.** There is no order book, adverse-selection mechanism, hedge transaction cost, slippage, market impact, stock bid/ask spread, borrowing spread, capital constraint, or early exercise. Hedging is discrete and the options are European.

## Credits

This project is based on Roman Paolucci's work in the [Quant Guild Library](https://github.com/romanmichaelpaolucci/Quant-Guild-Library), which collects his projects, and his [video explaining the project](https://www.youtube.com/watch?v=swPOLhSIBHo). The core simulator files, `market.py` and `market_making_simulation.py`, were written by hand for this repository while using his project as a reference for the overall structure and simulation approach. This version adds dividend-aware pricing and hedging, changes some financial calculations, and provides additional metrics and visualizations.

The dashboard files, `dashboard.py`, `templates/index.html`, `static/app.js`, and `static/style.css`, were created with ChatGPT Codex. The dashboard uses the simulator's results and calculates additional display values, including reference-model delta exposure and 40-run comparison metrics.

The pricing models follow [Black and Scholes (1973)](https://www.journals.uchicago.edu/doi/abs/10.1086/260062) and [Merton (1976)](https://www.sciencedirect.com/science/article/pii/0304405X76900222).

Santiago Orta
