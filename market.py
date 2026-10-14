import math
from dataclasses import dataclass

from scipy.stats import norm, poisson


def _d1_d2(S: float, K: float, r: float, sigma: float, T: float, q:float = 0) -> tuple[float, float]:
    if T <= 0 or sigma <= 0:
        eps = 1e-10
        T = max(T, eps)
        sigma = max(sigma, eps)
     
    d1 = (math.log(S / K) + (r - q + sigma**2 / 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def black_scholes_merton_price(S: float, K: float, r: float, sigma: float, T: float, q: float = 0, option_type: str = "call") -> float:
    if T <= 0:
        intrinsic_value = max(S - K, 0) if option_type == "call" else max (0, K - S)
        return float(intrinsic_value)

    d1, d2 = _d1_d2(S, K, r, sigma, T, q)
    discount_factor = math.exp(-r * T)
    dividend_discount_factor = math.exp(-q * T)
    if option_type == "call":
        price = S * dividend_discount_factor * norm.cdf(d1) - K * discount_factor * norm.cdf(d2)
    elif option_type == "put":
        price = K * discount_factor * norm.cdf(-d2) - S * dividend_discount_factor * norm.cdf(-d1)
    else:
        raise ValueError("Invalid option type. Must be 'call' or 'put'.")
    return float(price)


# Delta calculated separately for delta hedging purposes (in order to avoid unnecessary calculations of other greeks)
def black_scholes_merton_delta(S: float, K: float, r: float, sigma: float, T: float, q: float = 0, option_type: str = "call") -> float:
    if T <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        elif option_type == "put":
            return -1.0 if S < K else 0.0
        else:
            raise ValueError("Invalid option type. Must be 'call' or 'put'.")

    if option_type == "call":
        d1, _ = _d1_d2(S, K, r, sigma, T, q)
        delta = math.exp(-q * T) * norm.cdf(d1)
    elif option_type == "put":
        d1, _ = _d1_d2(S, K, r, sigma, T, q)
        delta = math.exp(-q * T) * (norm.cdf(d1) - 1)
    else:
        raise ValueError("Invalid option type. Must be 'call' or 'put'.")
    return float(delta)



def black_scholes_merton_greeks(S: float, K: float, r: float, sigma: float, T: float, q: float = 0, option_type: str = "call") -> dict[str, float]:

    if S <= 0 or K <= 0:
        raise ValueError("Stock price (S) and strike price (K) must be positive.")

    if sigma <= 0:
        raise ValueError("Volatility (sigma) must be positive.")

    if T <= 0:
        return {
            "delta": black_scholes_merton_delta(S, K, r, sigma, T, q, option_type),
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "rho": 0.0
        }

    d1, d2 = _d1_d2(S, K, r, sigma, T, q)
    pdf_d1 = norm.pdf(d1)
    discount_factor = math.exp(-r * T)
    dividend_discount_factor = math.exp(-q * T)

    gamma = (dividend_discount_factor * pdf_d1) / (S * sigma * math.sqrt(T))
    vega = S * dividend_discount_factor * pdf_d1 * math.sqrt(T)

    if option_type == "call":
        theta = (
            - (S * dividend_discount_factor * pdf_d1 * sigma) / (2 * math.sqrt(T)) 
            - r * K * discount_factor * norm.cdf(d2) + q * S * dividend_discount_factor * norm.cdf(d1)
        )

        rho = K * T * discount_factor * norm.cdf(d2)

    elif option_type == "put":
        theta = (
            - (S * dividend_discount_factor * pdf_d1 * sigma) / (2 * math.sqrt(T)) 
            + r * K * discount_factor * norm.cdf(-d2) - q * S * dividend_discount_factor * norm.cdf(-d1)
        )

        rho = -K * T * discount_factor * norm.cdf(-d2)

    else:
        raise ValueError("Invalid option type. Must be 'call' or 'put'.")


    return {
        "delta": black_scholes_merton_delta(S, K, r, sigma, T, q, option_type),
        "gamma": float(gamma),
        "vega": float(vega),
        "theta": float(theta),
        "rho": float(rho),
    }


def merton_jump_price(S: float, K: float, r: float, sigma: float, T: float, lambda_: float, 
                      mean_jump: float, sigma_jump: float, q: float = 0, option_type: str = "call") -> float:
    if T <= 0:
        if option_type == "call":
            intrinsic_value = max(S - K, 0.0)
        elif option_type == "put":
            intrinsic_value = max(0.0, K - S)
        else:
            raise ValueError("Invalid option type. Must be 'call' or 'put'.")
        return float(intrinsic_value)

    if lambda_ <= 0:
        return black_scholes_merton_price(S, K, r, sigma, T, q, option_type)

    k = math.exp(mean_jump + 0.5 * sigma_jump**2) - 1
    lambda_prime = lambda_ * (1 + k)
    lambda_T = lambda_prime * T
    nt = int(poisson.ppf(1 - 1e-12, lambda_T)) + 1

    price = 0.0

    for n in range(nt):
        log_w = poisson.logpmf(n, lambda_T)
        weight = math.exp(log_w)
        if weight < 1e-15 and n > lambda_T + 10:
            break

        sigma_n = math.sqrt(sigma**2 + n * sigma_jump**2 /T)
        r_n = r - lambda_ * k + n * (mean_jump + 0.5 * sigma_jump**2) / T
        price += weight * black_scholes_merton_price(S, K, r_n, sigma_n, T, q, option_type)

    return float(price)


def merton_jump_delta(S: float, K: float, r: float, sigma: float, T: float, lambda_: float, 
                      mean_jump: float, sigma_jump: float, q: float = 0, option_type: str = "call") -> float:
    if T <= 0:
        if option_type == "call":
            if S > K:
                return 1.0
            else:
                return 0.0
        elif option_type == "put":
            if S < K:
                return -1.0
            else:
                return 0.0
        else:
            raise ValueError("Invalid option type. Must be 'call' or 'put'.")
        
    if lambda_ <= 0:
        return black_scholes_merton_delta(S, K, r, sigma, T, q, option_type)

    k = math.exp(mean_jump + 0.5 * sigma_jump**2) - 1
    lambda_prime = lambda_ * (1 + k)
    lambda_T = lambda_prime * T
    nt = int(poisson.ppf(1 - 1e-12, lambda_T)) + 1
    delta = 0.0

    for n in range(nt):
        log_w = poisson.logpmf(n, lambda_T)
        weight = math.exp(log_w)
        if weight < 1e-15 and n > lambda_T + 10:
            break

        sigma_n = math.sqrt(sigma**2 + n * sigma_jump**2 / T)
        r_n = r - lambda_ * k + n * (mean_jump + 0.5 * sigma_jump**2) / T
        delta += weight * black_scholes_merton_delta(S, K, r_n, sigma_n, T, q, option_type)

    return float(delta)


@dataclass
class OptionPricingModel:
    name: str
    r: float = 0.0
    q: float = 0.0
    lambda_: float = 0.0
    mean_jump: float = 0.0
    sigma_jump: float = 0.0

    def price(self, S: float, K: float, sigma: float, T: float, option_type: str = "call") -> float:
        if self.name == "merton_jump_diffusion":
            return merton_jump_price(S, K, self.r, sigma, T, self.lambda_, self.mean_jump, self.sigma_jump, self.q, option_type = option_type)
        elif self.name == "black_scholes_merton":
            return black_scholes_merton_price(S, K, self.r, sigma, T, self.q, option_type = option_type)
        else:
            raise ValueError(f"Unknown option pricing model: {self.name}")

    def delta(self, S: float, K: float, sigma: float, T: float, option_type: str = "call") -> float:
        if self.name == "merton_jump_diffusion":
            return merton_jump_delta(S, K, self.r, sigma, T, self.lambda_, self.mean_jump, self.sigma_jump, self.q, option_type = option_type)
        elif self.name == "black_scholes_merton":
            return black_scholes_merton_delta(S, K, self.r, sigma, T, self.q, option_type = option_type)
        else:
            raise ValueError(f"Unknown option pricing model: {self.name}")


if __name__ == "__main__":
    S, K, r, sigma, T, q = 100.0, 100.0, 0.05, 0.2, 1.0, 0.0
    call = black_scholes_merton_price(S, K, r, sigma, T, q=q, option_type="call")
    put = black_scholes_merton_price(S, K, r, sigma, T, q=q, option_type="put")
    pc_parity = call - put - (S * math.exp(-q * T) - K * math.exp(-r * T))
    print(f"Call Price: {call:.4f}, Put Price: {put:.4f}, Put-Call Parity Check: {pc_parity:.4e}")

    merton_call = merton_jump_price(S, K, r, sigma, T, lambda_=0.1, mean_jump=-0.1, sigma_jump=0.2, q=q, option_type="call")
    merton_put = merton_jump_price(S, K, r, sigma, T, lambda_=0.1, mean_jump=-0.1, sigma_jump=0.2, q=q, option_type="put")
    merton_pc_parity = merton_call - merton_put - (S * math.exp(-q * T) - K * math.exp(-r * T))
    print(f"Merton Call Price: {merton_call:.4f}, Merton Put Price: {merton_put:.4f}, Merton Put-Call Parity Check: {merton_pc_parity:.4e}")

    print(f"Merton Call = {merton_call:.4f}, BSM Call = {call:.4f}, Difference = {merton_call - call:.4e}")
    if merton_call > call:
        print("Merton jump diffusion model gives a higher call price than Black-Scholes-Merton model, which is expected due to the inclusion of jumps in the model.")
    elif merton_call < call:
        print("Merton jump diffusion model gives a lower call price than Black-Scholes-Merton model, indicating an error in the implementation.")
    
    


# SOD