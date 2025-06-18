"""Risk module – trivial fixed sizing + leverage params."""
from __future__ import annotations

FIXED_PCT_PER_TRADE = 0.10  # 10 % wallet
MAX_CONCURRENT_POSITIONS = 7  # 70 % utilisation
LEVERAGE = 5
STOP_LOSS_PCT = 0.006  # 0.6 % (as decimal)
