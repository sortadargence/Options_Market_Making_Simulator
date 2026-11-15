import numpy as np

def calculate_fill_probability(base_probability: float, sensitivity: float, attractiveness: float) -> float:

    logit = np.log(base_probability / (1 - base_probability))
    probability = (1 / (1 + np.exp(-(logit + sensitivity * attractiveness))))

    return probability

    