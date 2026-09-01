import math

def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function (N(x)) using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def normal_pdf(x: float) -> float:
    """Standard normal probability density function (N'(x))."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

def calculate_black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    rate: float,
    iv: float,
    option_type: str
) -> float:
    """
    Calculates Black-Scholes price for Call (CE) or Put (PE).
    iv is expressed as decimal (e.g. 0.15 for 15%).
    """
    if time_to_expiry_years <= 0 or iv <= 0:
        if option_type == "CE":
            return max(0.0, spot - strike)
        else:
            return max(0.0, strike - spot)

    d1 = (math.log(spot / strike) + (rate + 0.5 * iv ** 2) * time_to_expiry_years) / (iv * math.sqrt(time_to_expiry_years))
    d2 = d1 - iv * math.sqrt(time_to_expiry_years)

    if option_type == "CE":
        price = spot * normal_cdf(d1) - strike * math.exp(-rate * time_to_expiry_years) * normal_cdf(d2)
    else:
        price = strike * math.exp(-rate * time_to_expiry_years) * normal_cdf(-d2) - spot * normal_cdf(-d1)

    return max(0.0, price)

def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    rate: float,
    iv: float,
    option_type: str
) -> dict:
    """
    Calculates Delta, Gamma, Theta (per day), and Vega (per 1% volatility change).
    All greeks are standard option risk metrics.
    """
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    
    if time_to_expiry_years <= 0 or iv <= 0:
        if option_type == "CE":
            greeks["delta"] = 1.0 if spot >= strike else 0.0
        else:
            greeks["delta"] = -1.0 if spot <= strike else 0.0
        return greeks

    d1 = (math.log(spot / strike) + (rate + 0.5 * iv ** 2) * time_to_expiry_years) / (iv * math.sqrt(time_to_expiry_years))
    d2 = d1 - iv * math.sqrt(time_to_expiry_years)
    
    pdf_d1 = normal_pdf(d1)
    
    # Delta
    if option_type == "CE":
        greeks["delta"] = normal_cdf(d1)
    else:
        greeks["delta"] = normal_cdf(d1) - 1.0
        
    # Gamma (same for Call and Put)
    greeks["gamma"] = pdf_d1 / (spot * iv * math.sqrt(time_to_expiry_years))
    
    # Vega (same for Call and Put, divided by 100 to show sensitivity per 1% change in IV)
    greeks["vega"] = (spot * math.sqrt(time_to_expiry_years) * pdf_d1) / 100.0
    
    # Theta (divided by 365 to show daily decay rate)
    if option_type == "CE":
        term1 = -(spot * pdf_d1 * iv) / (2.0 * math.sqrt(time_to_expiry_years))
        term2 = -rate * strike * math.exp(-rate * time_to_expiry_years) * normal_cdf(d2)
        greeks["theta"] = (term1 + term2) / 365.0
    else:
        term1 = -(spot * pdf_d1 * iv) / (2.0 * math.sqrt(time_to_expiry_years))
        term2 = rate * strike * math.exp(-rate * time_to_expiry_years) * normal_cdf(-d2)
        greeks["theta"] = (term1 + term2) / 365.0
        
    return greeks

def find_implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    rate: float,
    option_type: str,
    max_iterations: int = 100,
    precision: float = 1e-4
) -> float:
    """
    Finds implied volatility using Bisection method.
    Returns IV as a decimal (e.g. 0.165 for 16.5%).
    """
    intrinsic_value = max(0.0, spot - strike if option_type == "CE" else strike - spot)
    if market_price <= intrinsic_value:
        return 0.01  # baseline minimum volatility

    low_iv = 0.001
    high_iv = 4.0
    
    for _ in range(max_iterations):
        mid_iv = (low_iv + high_iv) / 2.0
        price = calculate_black_scholes_price(spot, strike, time_to_expiry_years, rate, mid_iv, option_type)
        
        if abs(price - market_price) < precision:
            return mid_iv
            
        if price < market_price:
            low_iv = mid_iv
        else:
            high_iv = mid_iv
            
    return (low_iv + high_iv) / 2.0
