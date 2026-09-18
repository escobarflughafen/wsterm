"""Option contracts: parse the OCC symbol and project what the position is worth at expiry.

Yahoo keeps no history for individual contracts, so an open position is carried at cost and everything
interesting is derived from the underlying: moneyness today, break-even, and the payoff at expiry.
"""
import datetime as dt
import re

OCC = re.compile(r'^(?P<root>[A-Z][A-Z0-9.]{0,5})\s+(?P<exp>\d{6})(?P<right>[CP])(?P<strike>\d{8})$')
SHARES_PER_CONTRACT = 100


def parse(symbol):
    """'OPEN  261002C00002500' -> root OPEN, expiry 2026-10-02, CALL, strike 2.50."""
    m = OCC.match((symbol or '').strip().upper().replace(' ', ' '))
    if not m:
        return None
    exp = m.group('exp')
    try:
        expiry = dt.date(2000 + int(exp[:2]), int(exp[2:4]), int(exp[4:6]))
    except ValueError:
        return None
    return dict(root=m.group('root'), expiry=expiry.isoformat(), right='CALL' if m.group('right') == 'C' else 'PUT',
                strike=int(m.group('strike')) / 1000)


def intrinsic(right, strike, spot):
    return max(0.0, spot - strike) if right == 'CALL' else max(0.0, strike - spot)


def position(symbol, contracts, cost, spot=None, today=None):
    """cost: what the open contracts cost in their own currency (positive). spot: underlying last close."""
    spec = parse(symbol)
    if not spec or contracts <= 0:
        return None
    per_contract = cost / contracts
    per_share = per_contract / SHARES_PER_CONTRACT
    strike, right = spec['strike'], spec['right']
    breakeven = strike + per_share if right == 'CALL' else strike - per_share
    today = today or dt.date.today()
    days = (dt.date.fromisoformat(spec['expiry']) - today).days
    out = dict(**spec, symbol=symbol.strip(), contracts=contracts, cost=round(cost, 2),
               premium_per_contract=round(per_contract, 2), premium_per_share=round(per_share, 4),
               breakeven=round(breakeven, 4), days_to_expiry=days, expired=days < 0)
    if spot:
        value = intrinsic(right, strike, spot) * SHARES_PER_CONTRACT * contracts
        out.update(spot=round(spot, 4), moneyness=round((spot - strike) / strike if right == 'CALL'
                                                        else (strike - spot) / strike, 4),
                   intrinsic_now=round(value, 2), intrinsic_pl=round(value - cost, 2),
                   to_breakeven=round(breakeven / spot - 1, 4) if right == 'CALL' else round(1 - breakeven / spot, 4))
    return out


def payoff(pos, points=41, span=0.6):
    """P&L at expiry across a range of underlying prices, centred on the strike (and today's spot if known)."""
    strike, spot = pos['strike'], pos.get('spot') or pos['strike']
    lo, hi = min(strike, spot) * (1 - span), max(strike, spot) * (1 + span)
    step = (hi - lo) / (points - 1)
    grid = []
    for i in range(points):
        s = lo + step * i
        value = intrinsic(pos['right'], strike, s) * SHARES_PER_CONTRACT * pos['contracts']
        grid.append(dict(spot=round(s, 4), pl=round(value - pos['cost'], 2)))
    return grid
