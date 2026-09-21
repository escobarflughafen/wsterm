"""MCP endpoint: composed answers about this portfolio, for other agents.

Seven read tools and the two simulation engines. Never fetch, rebuild or import: an agent that can
trigger a fetch can get the Yahoo account rate limited, and one that can import can corrupt the
activity master. Those stay with the owner.

The tools return answers, not payloads. `data.json` is well past half a megabyte -- handing that to a
caller costs it the context it needs to reason, and hands over every balance to answer one question.
Each tool here returns the slice that was asked for, already computed.

Off unless MCP_TOKEN is set. That token is deliberately separate from APP_PASSWORD, so revoking
agent access never locks the owner out of the browser, and every call is appended to mcp_log.jsonl.

Protocol: JSON-RPC 2.0 over POST, the subset of MCP a synchronous tool server needs --
initialize, tools/list, tools/call, resources/list, resources/read, prompts/list, prompts/get.
"""
import datetime as dt
import json
import re
import time

from settings import BUILD_DIR, MARKET_DIR

PROTOCOL = '2025-06-18'
SERVER = dict(name='portfolio-terminal', version='1.0.0')
RANGES = ('1M', '3M', '6M', 'YTD', '1Y', 'ALL')
SYMBOL = re.compile(r'^[A-Za-z0-9.\-]{1,24}$')
TRADE_ID = re.compile(r'^[0-9a-f]{12}$')


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- data access
def _read(name):
    path = BUILD_DIR / name
    if not path.exists():
        raise ToolError(f'{name} has not been built yet; the owner needs to run a rebuild')
    with open(path) as f:
        return json.load(f)


def _start(dates, rng):
    """Index of the first day in a named range, matching what the browser shows."""
    if rng == 'ALL' or not dates:
        return 0
    last = dt.date.fromisoformat(dates[-1])
    first = dt.date(last.year, 1, 1) if rng == 'YTD' else last - dt.timedelta(
        days={'1M': 31, '3M': 92, '6M': 183, '1Y': 365}[rng])
    iso = first.isoformat()
    return next((i for i, d in enumerate(dates) if d >= iso), 0)


def _thin(values, cap=120):
    """Downsample a series so a caller gets the shape without a thousand numbers."""
    if len(values) <= cap:
        return values
    step = len(values) / cap
    return [values[min(len(values) - 1, int(i * step))] for i in range(cap)]


def _pct(x, places=4):
    return None if x is None else round(x, places)


# ---------------------------------------------------------------- read tools
def portfolio_snapshot():
    d = _read('data.json')
    s, alloc = d['summary'], d['alloc']['now']
    total = s['total']
    top = sorted(d['holdings'], key=lambda r: -r['mv_cad'])[:8]
    return dict(
        as_of=d['asof'], priced=d['price_date'], usdcad=d['fx'],
        total_cad=s['total'], net_deposited=s['contrib'], gain_cad=s['gain'],
        realised_cad=s['realized'], unrealised_cad=s['unreal'], day_change_cad=s['day'],
        time_weighted_return=s['twr'],
        benchmarks={b: dict(value_cad=x['value'], time_weighted_return=x['twr'],
                            you_vs_it_cad=round(s['total'] - x['value'], 2))
                    for b, x in s['bench'].items()},
        allocation={k: dict(cad=round(v, 2), share=_pct(v / total, 3)) for k, v in alloc.items()},
        accounts=[dict(account=a['acct'], value_cad=a['value'], gain_cad=a['gain']) for a in d['accounts']],
        top_positions=[dict(symbol=r['sym'], account=r['acct'], bucket=r['cat'], value_cad=r['mv_cad'],
                            unrealised=r['upl'], unrealised_pct=r['upl_pct']) for r in top],
        reconciliation=d.get('reconcile') and dict(
            report_as_of=d['reconcile']['asof'], stale=d['reconcile']['stale'],
            lines_differing=len(d['reconcile']['differences'])),
    )


def position(symbol):
    if not SYMBOL.match(symbol or ''):
        raise ToolError('symbol must be a plain ticker')
    d = _read('data.json')
    sym = symbol.upper()
    held = [r for r in d['holdings'] if r['sym'].upper() == sym]
    booked = [p for p in d['positions'] if p['sym'].upper() == sym]
    trades = [t for t in d['trades'] if t['sym'].upper() == sym]
    if not held and not booked:
        raise ToolError(f'no position or trade history for {sym}')
    cmp_ = _read('compare.json')
    key = next((k for k in cmp_ if k.upper() == sym or k.upper().split('.')[0] == sym), None)
    market = None
    if key:
        tr = cmp_[key]['tr']
        market = dict(ticker=key, total_return_all_time=_pct(tr[-1] / tr[0] - 1) if tr and tr[0] else None,
                      peak_capital_cad=cmp_[key]['peak_cost'],
                      your_gain_cad=cmp_[key]['gain'][-1],
                      return_on_capital=_pct(cmp_[key]['gain'][-1] / cmp_[key]['peak_cost'])
                      if cmp_[key]['peak_cost'] else None)
    return dict(
        symbol=sym,
        holdings=[dict(account=r['acct'], quantity=r['qty'], average_cost=r['avg'], last_price=r['px'],
                       value_cad=r['mv_cad'], unrealised=r['upl'], unrealised_pct=r['upl_pct'],
                       currency=r['cur'], bucket=r['cat']) for r in held],
        realised=[dict(account=p['acct'], currency=p['cur'], realised_cad=p['realized_cad'],
                       buys=p['buys'], sells=p['sells'], open=p['open'],
                       first_trade=p['first'], last_trade=p['last']) for p in booked],
        trade_count=len(trades),
        recent_trades=[dict(executed=t['date'], ordered=t.get('time'), queued_overnight=bool(t.get('queued')),
                            account=t['acct'], side=t['side'], quantity=t['qty'], price=t['px'],
                            currency=t['cur'], hindsight_cad=t.get('edge_cad')) for t in trades[:12]],
        market=market,
    )


def performance(range='ALL', basis='ALL_MONEY', account='ALL'):
    if range not in RANGES:
        raise ToolError(f'range must be one of {", ".join(RANGES)}')
    d = _read('data.json')
    s = d['series']
    invested = basis.upper() == 'INVESTED'
    if invested and not s.get('invested'):
        raise ToolError('the invested-only basis is not available in this build')
    P = (dict(total=s['invested']['value'], contrib=s['invested']['capital'],
              twr=s['invested']['twr'], bench=s['invested']['bench']) if invested
         else dict(total=s['total'], contrib=s['contrib'], twr=s['twr'], bench=s['bench']))
    if account != 'ALL':
        if account not in s['accounts']:
            raise ToolError(f'unknown account; have {", ".join(s["accounts"])}')
        P = dict(total=s['accounts'][account], contrib=s['account_contrib'][account], twr=None, bench={})
    i0 = _start(s['dates'], range)
    v, c = P['total'], P['contrib']
    added = c[-1] - c[i0]
    change = v[-1] - v[i0]
    out = dict(range=range, basis='INVESTED' if invested else 'ALL_MONEY', account=account,
               start=s['dates'][i0], end=s['dates'][-1],
               value_start_cad=v[i0], value_end_cad=v[-1],
               money_added_cad=round(added, 2), investment_gain_cad=round(change - added, 2))
    if P['twr']:
        out['time_weighted_return'] = _pct(P['twr'][-1] / P['twr'][i0] - 1)
    out['benchmarks'] = {b: dict(time_weighted_return=_pct(x['twr'][-1] / x['twr'][i0] - 1),
                                 gain_with_the_same_money_cad=round((x['value'][-1] - x['value'][i0]) - added, 2))
                         for b, x in P['bench'].items()}
    return out


def rules():
    d = _read('data.json')
    return dict(
        as_of=d['price_date'],
        rules=[dict(id=r['id'], commitment=r['name'], threshold=r['spec'], holds=r['ok'],
                    detail=r['detail'], items=r['items'][:8]) for r in d['rules']],
        todo=[dict(id=t['id'], action=t['text'], done=t['done'], detail=t['detail'],
                   amount_cad=t.get('amount')) for t in d.get('todos', [])],
        deployment=d.get('dca'),
    )


def decisions(decision_class=None, horizon=20):
    d = _read('data.json')
    a = d['audit']
    if horizon not in a['horizons']:
        raise ToolError(f'horizon must be one of {a["horizons"]}')
    rows = a['summary']
    if decision_class:
        rows = [r for r in rows if r['cls'] == decision_class.upper()]
        if not rows:
            raise ToolError('unknown class; have ' + ', '.join(r['cls'] for r in a['summary']))
    h = horizon
    return dict(
        benchmark=a['benchmark'], horizon_trading_days=h, methodology=a['methodology'],
        coverage=a['coverage'],
        classes=[dict(decision_class=r['cls'], decisions=r['decisions'], campaigns=r['campaigns'],
                      scored=r[f'n_{h}d'], mean_excess=r[f'er_{h}d'], median_excess=r[f'median_{h}d'],
                      win_rate=r[f'win_{h}d'], band_10_90=[r[f'lo_{h}d'], r[f'hi_{h}d']]) for r in rows],
        concentration=dict(actual_return=a['concentration']['actual_return'],
                           benchmark_return=a['concentration']['benchmark_return'],
                           excess=a['concentration']['actual_excess'],
                           top_share_of_positive_pnl=a['concentration']['top_positive_share']),
        averaging_down=a['averaging_down'],
        reconciliation=a.get('reconciliation'),
    )


def compare(symbols, range='ALL'):
    if range not in RANGES:
        raise ToolError(f'range must be one of {", ".join(RANGES)}')
    if not symbols or len(symbols) > 12:
        raise ToolError('give between 1 and 12 symbols')
    d = _read('data.json')
    cmp_ = _read('compare.json')
    i0 = _start(d['series']['dates'], range)
    out = []
    for s in symbols:
        key = next((k for k in cmp_ if k.upper() == s.upper() or k.upper().split('.')[0] == s.upper()), None)
        if not key:
            out.append(dict(symbol=s, error='no history'))
            continue
        c = cmp_[key]
        tr = c['tr'][i0:] if c['tr'] else None
        g, v = c['gain'][i0:], c['value'][i0:]
        out.append(dict(
            symbol=key, held=c['held'],
            market_return_in_range=_pct(tr[-1] / tr[0] - 1) if tr and tr[0] else None,
            your_gain_in_range_cad=round(g[-1] - g[0], 2),
            your_gain_all_time_cad=c['gain'][-1],
            value_now_cad=c['value'][-1], peak_value_cad=round(max(v), 2),
            peak_capital_cad=c['peak_cost'],
            return_on_capital=_pct(c['gain'][-1] / c['peak_cost']) if c['peak_cost'] else None))
    return dict(range=range, start=d['series']['dates'][i0], end=d['series']['dates'][-1], tickers=out)


def series(symbol, field='value', range='6M'):
    if field not in ('value', 'gain', 'market'):
        raise ToolError("field must be value, gain or market")
    if range not in RANGES:
        raise ToolError(f'range must be one of {", ".join(RANGES)}')
    d = _read('data.json')
    cmp_ = _read('compare.json')
    key = next((k for k in cmp_ if k.upper() == symbol.upper() or k.upper().split('.')[0] == symbol.upper()), None)
    if not key:
        raise ToolError(f'no series for {symbol}')
    dates = d['series']['dates']
    i0 = _start(dates, range)
    src = cmp_[key]['tr'] if field == 'market' else cmp_[key][field]
    if not src:
        raise ToolError(f'{field} is not available for {key}')
    cut = src[i0:]
    if field == 'market':
        cut = [_pct(x / cut[0] - 1) for x in cut] if cut[0] else cut
    elif field == 'gain':
        cut = [round(x - cut[0], 2) for x in cut]
    return dict(symbol=key, field=field, range=range, unit='ratio' if field == 'market' else 'CAD',
                dates=_thin(dates[i0:]), values=_thin(cut),
                note='downsampled to at most 120 points' if len(cut) > 120 else None)


# ---------------------------------------------------------------- simulation
def what_if_without(trade_ids, redirect=None):
    import engine
    from ledger import load_activities
    ids = [i for i in (trade_ids or []) if TRADE_ID.fullmatch(i)]
    if not ids:
        raise ToolError('give trade ids as 12 hex characters; find them with position()')
    if len(ids) > 500:
        raise ToolError('at most 500 trades per call')
    dest = redirect if redirect in (*engine.CFG['benchmarks'], engine.CASH_ETF) else None
    r = engine.simulate(load_activities(), ids, dest)
    return dict(removed=ids, freed_cash_goes_to=dest or 'cash (idle)', **r['summary'])


def what_if_frozen(date=None, trade=None, deposits='cash'):
    import server
    if not date and not trade:
        raise ToolError('give a date (YYYY-MM-DD) or a trade id')
    if date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
        raise ToolError('date must be YYYY-MM-DD')
    if trade and not TRADE_ID.fullmatch(trade):
        raise ToolError('trade must be 12 hex characters')
    r = server._freeze_ctx()['ctx'].run(trade=trade, date=date, deposits=deposits)
    return {k: r[k] for k in ('label', 'date', 'summary', 'horizons') if k in r}


# ---------------------------------------------------------------- tool table
def _t(name, description, properties, required=(), handler=None):
    return dict(name=name, description=description, handler=handler,
                inputSchema=dict(type='object', properties=properties, required=list(required),
                                 additionalProperties=False))


_RANGE = dict(type='string', enum=list(RANGES), description='Window ending today.')
TOOLS = [
    _t('portfolio_snapshot',
       'Current value, gain, time-weighted return against each benchmark, allocation by bucket, the '
       'largest positions, and whether the broker snapshot still agrees with the ledger. Start here.',
       {}, (), portfolio_snapshot),
    _t('position', 'Everything about one ticker: holdings per account with average cost and unrealised '
       'P&L, realised P&L, recent trades with their execution dates, and how the security itself did '
       'against what you made on it.',
       dict(symbol=dict(type='string', description='Ticker, e.g. VOO or XEQT.')), ('symbol',), position),
    _t('performance', 'Return and dollar gain over a window, split into money added versus investment '
       'gain, against each benchmark replaying the same deposits.',
       dict(range=_RANGE,
            basis=dict(type='string', enum=['ALL_MONEY', 'INVESTED'],
                       description='INVESTED excludes cash and cash ETFs from both sides.'),
            account=dict(type='string', description='ALL, or one account name.')), (), performance),
    _t('rules', "The owner's own written commitments, which hold and which are broken, plus this "
       "month's to-do list with the amount still owed on each, and the scheduled deployment plan.",
       {}, (), rules),
    _t('decisions', 'Decision audit: fixed-horizon excess return against the benchmark by decision '
       'class (opening, adding above or below cost, trimming, exiting), with sample sizes and '
       'campaign-resampled ranges. Descriptive, never proof of skill.',
       dict(decision_class=dict(type='string', description='One class, or omit for all.'),
            horizon=dict(type='integer', description='Trading days: 1, 5, 20 or 60.')), (), decisions),
    _t('compare', 'Several tickers side by side: the security’s own total return in CAD versus what the '
       'position actually earned. The two rank differently and that is the point.',
       dict(symbols=dict(type='array', items=dict(type='string'), description='1 to 12 tickers.'),
            range=_RANGE), ('symbols',), compare),
    _t('series', 'A downsampled daily series for one ticker: position value, cumulative gain, or the '
       'security’s market return rebased to the range start.',
       dict(symbol=dict(type='string'), field=dict(type='string', enum=['value', 'gain', 'market']),
            range=_RANGE), ('symbol',), series),
    _t('what_if_without', 'Replay the whole history with specific trades removed. Later sells of shares '
       'that were never bought are clipped. Pure computation; nothing is written.',
       dict(trade_ids=dict(type='array', items=dict(type='string'),
                           description='12-hex trade ids from position().'),
            redirect=dict(type='string', description='Where freed cash goes; omit to leave it idle.')),
       ('trade_ids',), what_if_without),
    _t('what_if_frozen', 'Stop all trading at a date or right after a trade and let the portfolio ride, '
       'reporting what it would be worth over each horizon. Pure computation; nothing is written.',
       dict(date=dict(type='string', description='YYYY-MM-DD.'), trade=dict(type='string'),
            deposits=dict(type='string', description="What later deposits do: cash, none, or a ticker.")),
       (), what_if_frozen),
]
BY_NAME = {t['name']: t for t in TOOLS}

RESOURCES = [
    dict(uri='portfolio://methodology', name='How the numbers are computed', mimeType='text/markdown'),
    dict(uri='portfolio://rules', name='The owner’s rules and this month’s to-do', mimeType='application/json'),
]

PROMPTS = [
    dict(name='daily_review', description='Look at today: value, rules, what is still to do.'),
    dict(name='explain_position', description='Explain one holding and how it got here.',
         arguments=[dict(name='symbol', description='Ticker', required=True)]),
    dict(name='check_rules', description='Report which commitments are broken and what it would take to fix them.'),
]

METHODOLOGY = """# How these numbers are computed

- **Source of truth is the activity ledger**, not the broker's holdings snapshot. Positions, cash and
  NAV are replayed from every trade, so an import updates them immediately. The holdings report is
  kept only as an independent check; `portfolio_snapshot().reconciliation` says whether it still agrees.
- **Dates are execution dates.** Wealthsimple stamps an order when it is placed; the real date comes
  from the description. About a quarter of trades move by one day.
- **Cost basis is average cost (ACB)** per account, symbol and currency.
- **Returns are time-weighted** — deposits and withdrawals removed — so they are comparable with a
  benchmark. Benchmarks replay the same deposits into that ETF on the same day, dividends reinvested.
- **The INVESTED basis** excludes cash and cash ETFs from both sides, so the benchmark only receives
  money when a risk asset was actually bought.
- **Currency**: everything is reported in CAD. USD positions convert at the Bank of Canada rate for
  the day in question; today's values use today's rate.
- **The decision audit** scores each trade by close-to-close excess return over fixed horizons of 1, 5,
  20 and 60 trading days. Pre-trade state uses the previous completed close, so no score can see the
  future. For a sale the sign is reversed. Scores are descriptive, not evidence of skill, and the
  10–90% bands resample whole campaigns rather than individual fills.
- **Options** are carried at cost: there is no price history for a contract. They stay in P&L and are
  excluded from timing tests.
- **What-if tools compute, they do not write.** Nothing an agent calls here changes stored state.
"""


# ---------------------------------------------------------------- JSON-RPC
def _log(method, params, ok, ms):
    try:
        with open(MARKET_DIR / 'mcp_log.jsonl', 'a') as f:
            f.write(json.dumps(dict(at=dt.datetime.now().isoformat(timespec='seconds'), method=method,
                                    tool=(params or {}).get('name'), ok=ok, ms=ms)) + '\n')
    except OSError:
        pass


def _content(payload):
    return dict(content=[dict(type='text', text=json.dumps(payload, ensure_ascii=False, indent=1))])


def handle(message):
    """One JSON-RPC request in, one response out (or None for a notification)."""
    method, params, mid = message.get('method'), message.get('params') or {}, message.get('id')
    started = time.perf_counter()

    def done(result=None, error=None):
        _log(method, params, error is None, round((time.perf_counter() - started) * 1000))
        if mid is None:
            return None
        out = dict(jsonrpc='2.0', id=mid)
        out['error' if error else 'result'] = error or result
        return out

    if method == 'initialize':
        return done(dict(protocolVersion=PROTOCOL, serverInfo=SERVER,
                         capabilities=dict(tools={}, resources={}, prompts={}),
                         instructions='Read-only portfolio analysis plus two what-if engines. '
                                      'Call portfolio_snapshot first; read portfolio://methodology '
                                      'before drawing conclusions from the audit.'))
    if method in ('notifications/initialized', 'ping'):
        return done({})
    if method == 'tools/list':
        return done(dict(tools=[{k: v for k, v in t.items() if k != 'handler'} for t in TOOLS]))
    if method == 'resources/list':
        return done(dict(resources=RESOURCES))
    if method == 'prompts/list':
        return done(dict(prompts=PROMPTS))
    if method == 'resources/read':
        uri = params.get('uri')
        if uri == 'portfolio://methodology':
            return done(dict(contents=[dict(uri=uri, mimeType='text/markdown', text=METHODOLOGY)]))
        if uri == 'portfolio://rules':
            return done(dict(contents=[dict(uri=uri, mimeType='application/json',
                                            text=json.dumps(rules(), ensure_ascii=False, indent=1))]))
        return done(error=dict(code=-32602, message=f'unknown resource {uri}'))
    if method == 'prompts/get':
        name = params.get('name')
        text = {
            'daily_review': 'Call portfolio_snapshot and rules. Report what changed today, which '
                            'commitments are broken, and what is still on the to-do list. Be brief.',
            'explain_position': 'Call position for {symbol} and compare for it against the benchmarks. '
                                'Explain how the position got to where it is and what the audit says '
                                'about the decisions that built it.',
            'check_rules': 'Call rules. For each broken commitment, say what it would take to bring it '
                           'back inside, using the amounts already computed.',
        }.get(name)
        if not text:
            return done(error=dict(code=-32602, message=f'unknown prompt {name}'))
        for k, v in (params.get('arguments') or {}).items():
            text = text.replace('{' + k + '}', str(v))
        return done(dict(messages=[dict(role='user', content=dict(type='text', text=text))]))
    if method == 'tools/call':
        tool = BY_NAME.get(params.get('name'))
        if not tool:
            return done(error=dict(code=-32602, message=f'unknown tool {params.get("name")}'))
        try:
            return done(_content(tool['handler'](**(params.get('arguments') or {}))))
        except ToolError as e:
            return done(dict(isError=True, content=[dict(type='text', text=str(e))]))
        except TypeError as e:
            return done(dict(isError=True, content=[dict(type='text', text=f'bad arguments: {e}')]))
        except Exception as e:                                    # a broken tool is the agent's problem to see
            return done(dict(isError=True, content=[dict(type='text', text=f'{type(e).__name__}: {e}')]))
    return done(error=dict(code=-32601, message=f'unknown method {method}'))
