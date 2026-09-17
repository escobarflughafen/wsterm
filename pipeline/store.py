"""Exports store: validates Wealthsimple CSVs, merges them into master files, archives every upload.

Layout under EXPORTS_DIR:
  activities.csv     merged, de-duplicated activity history (source of truth)
  holdings.csv       latest holdings report (as uploaded)
  uploads/           every committed file, timestamped, never modified
  staging/<id>/      previews waiting for commit (auto-expire)
  inbox/             drop files here (scp, sync); the next rebuild or scheduler tick imports them

Activity exports can overlap or cover partial ranges, so merging is multiset-aware: a row that appears
m times on file and k_i times in uploaded file i ends up max(m, k_1, k_2, ...) times. Identical legitimate
rows (two same-second fills) survive, and overlapping files uploaded together are not double counted.
"""
import collections, csv, datetime as dt, io, json, re, shutil, time, uuid
from pathlib import Path

from settings import EXPORTS_DIR

ACTIVITIES = EXPORTS_DIR / 'activities.csv'
HOLDINGS = EXPORTS_DIR / 'holdings.csv'
UPLOADS = EXPORTS_DIR / 'uploads'
STAGING = EXPORTS_DIR / 'staging'
INBOX = EXPORTS_DIR / 'inbox'
STAGING_TTL_S = 3600

ACTIVITY_COLUMNS = ['effective_date', 'effective_time', 'settlement_date', 'account_id', 'account_type', 'activity_type',
                    'activity_sub_type', 'description', 'direction', 'symbol', 'underlying symbol', 'name', 'currency',
                    'quantity', 'unit_price', 'commission', 'net_cash_amount']
HOLDINGS_COLUMNS = ['Account Name', 'Account Type', 'Account Classification', 'Account Number', 'Symbol', 'Exchange', 'MIC',
                    'Name', 'Security Type', 'Quantity', 'Position Direction', 'Market Price', 'Market Price Currency',
                    'Book Value (CAD)', 'Book Value Currency (CAD)', 'Book Value (Market)', 'Book Value Currency (Market)',
                    'Market Value', 'Market Value Currency', 'Market Unrealized Returns', 'Market Unrealized Returns Currency']
KNOWN_ACTIVITY_TYPES = {'Trade', 'MoneyMovement', 'Dividend', 'Interest', 'Tax', 'Fee', 'FxExchange',
                        'InternalSecurityTransfer', 'BonusPayment'}
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
ASOF = re.compile(r'As of (\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?')


class ImportError_(ValueError):
    pass


def safe_name(name, fallback):
    """Uploads name files; we only ever keep a basename of [A-Za-z0-9._-]. '../../etc/passwd' becomes 'passwd'."""
    base = Path(str(name or '')).name
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', base).lstrip('.')[:80]
    return cleaned or fallback


def inside(base: Path, path: Path) -> Path:
    """Defence in depth: every write must resolve inside the exports store."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(base).resolve()):
        raise ImportError_(f'Refusing to write outside the exports directory: {path}')
    return resolved


def _text(raw: bytes) -> str:
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportError_('File is not UTF-8 or Windows-1252 text')


def detect(text):
    header = next(csv.reader(io.StringIO(text)), [])
    header = [h.strip() for h in header]
    if header == ACTIVITY_COLUMNS:
        return 'activities'
    if header == HOLDINGS_COLUMNS:
        return 'holdings'
    if set(ACTIVITY_COLUMNS) <= set(header):
        return 'activities'
    if set(HOLDINGS_COLUMNS) <= set(header):
        return 'holdings'
    return None


def _num(v):
    if v in ('', None):
        return True
    try:
        float(v)
        return True
    except ValueError:
        return False


def parse_activities(text):
    rows, errors, warnings = [], [], []
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    for i, r in enumerate(reader, start=2):
        if not any((v or '').strip() for v in r.values()):
            continue
        row = {c: (r.get(c) or '').strip() for c in ACTIVITY_COLUMNS}
        problems = []
        if not DATE.match(row['effective_date']):
            problems.append(f"effective_date '{row['effective_date']}'")
        for c in ('quantity', 'unit_price', 'commission', 'net_cash_amount'):
            if not _num(row[c]):
                problems.append(f"{c} '{row[c]}'")
        if not row['account_type'] or not row['activity_type']:
            problems.append('missing account_type/activity_type')
        if problems:
            errors.append(f'line {i}: ' + ', '.join(problems))
            continue
        if row['activity_type'] not in KNOWN_ACTIVITY_TYPES:
            warnings.append(f"line {i}: unfamiliar activity_type '{row['activity_type']}' (kept)")
        rows.append(row)
    return rows, errors, warnings


def parse_holdings(text, filename=''):
    rows, errors, asof = [], [], None
    lines = text.splitlines()
    for line in lines[-3:]:
        m = ASOF.search(line)
        if m:
            asof = f'{m.group(1)}T{m.group(2) or "00:00"}'
    if not asof:
        m = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
        asof = f'{m.group(1)}T00:00' if m else None
    for i, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        if not r.get('Quantity'):
            continue  # footer line
        problems = [c for c in ('Quantity', 'Market Price', 'Book Value (Market)', 'Market Value') if not _num(r.get(c))]
        if problems:
            errors.append(f'line {i}: non-numeric ' + ', '.join(problems))
            continue
        rows.append(r)
    return rows, asof, errors


def row_key(row):
    return tuple(row[c] for c in ACTIVITY_COLUMNS)


def merge_activities(existing, incoming_files):
    """incoming_files: list of row lists, one per uploaded file."""
    have = collections.Counter(map(row_key, existing))
    target, by_key = collections.Counter(have), {}
    for rows in incoming_files:
        for key, n in collections.Counter(map(row_key, rows)).items():
            target[key] = max(target[key], n)
        by_key.update((row_key(r), r) for r in rows)
    merged = list(existing)
    added = 0
    for key, n in target.items():
        for _ in range(n - have.get(key, 0)):
            merged.append(by_key[key])
            added += 1
    merged.sort(key=lambda r: (r['effective_date'], r['effective_time']))
    return merged, added, sum(len(rows) for rows in incoming_files) - added


def _write_csv_atomic(path: Path, rows, columns):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def load_activity_rows():
    if not ACTIVITIES.exists():
        return []
    rows, _, _ = parse_activities(ACTIVITIES.read_text())
    return rows


def holdings_asof():
    if not HOLDINGS.exists():
        return None
    return parse_holdings(HOLDINGS.read_text())[1]


def has_data():
    return ACTIVITIES.exists() and HOLDINGS.exists()


def summarize_activities(rows):
    if not rows:
        return dict(rows=0)
    dates = [r['effective_date'] for r in rows]
    return dict(rows=len(rows), first=min(dates), last=max(dates),
                accounts=sorted({r['account_type'] for r in rows}),
                trades=sum(r['activity_type'] == 'Trade' for r in rows))


def status():
    acts = load_activity_rows()
    return dict(activities=summarize_activities(acts), holdings_asof=holdings_asof(),
                uploads=len(list(UPLOADS.glob('*'))) if UPLOADS.exists() else 0,
                inbox=len(list(INBOX.glob('*.csv'))) if INBOX.exists() else 0)


# ------------------------------------------------------------------ preview / commit
def _reconcile(activity_rows, holdings_rows):
    """Compare ledger quantities with a holdings report; mismatches usually mean exports from different days."""
    from ledger import build_positions, holdings_from_rows
    pos = build_positions(activity_rows)
    hold = holdings_from_rows(holdings_rows)
    issues = []
    for key, h in hold.items():
        q = pos[key]['q'] if key in pos else 0.0
        if abs(q - h['q']) > 1e-6:
            issues.append(f'{key[0]} {key[1]} {key[2]}: activities give {q:g}, holdings say {h["q"]:g}')
    for key, p in pos.items():
        if key not in hold and abs(p['q']) > 1e-6 and key[0] != 'Crypto':
            issues.append(f'{key[0]} {key[1]} {key[2]}: activities give {p["q"]:g}, not in holdings')
    return issues


def cleanup_staging():
    if not STAGING.exists():
        return
    for d in STAGING.iterdir():
        if d.is_dir() and time.time() - d.stat().st_mtime > STAGING_TTL_S:
            shutil.rmtree(d, ignore_errors=True)


def preview(files):
    """files: [(filename, bytes)]. Validates and stages; nothing on file changes until commit()."""
    cleanup_staging()
    pid = uuid.uuid4().hex[:16]
    stage = STAGING / pid
    stage.mkdir(parents=True)
    existing = load_activity_rows()
    current_asof = holdings_asof()
    report, incoming_acts, holdings_pick = [], [], None
    for i, (name, raw) in enumerate(files):
        safe = safe_name(name, f'upload{i}.csv')
        entry = dict(file=safe, kind=None, ok=False, errors=[], warnings=[])
        try:
            text = _text(raw)
            kind = detect(text)
            entry['kind'] = kind
            if kind == 'activities':
                rows, errors, warnings = parse_activities(text)
                entry.update(errors=errors[:20], warnings=warnings[:20], rows=len(rows), **{
                    k: v for k, v in summarize_activities(rows).items() if k != 'rows'})
                if not errors and rows:
                    known = {r['account_id'] for r in existing}
                    ids = {r['account_id'] for r in rows}
                    if known and not ids & known:
                        entry['warnings'].append('None of these account IDs match your existing data. Different person?')
                    incoming_acts.append(rows)
            elif kind == 'holdings':
                rows, asof, errors = parse_holdings(text, safe)
                entry.update(errors=errors[:20], rows=len(rows), asof=asof)
                if not asof:
                    entry['warnings'].append('No "As of" date found; treated as newest')
                if current_asof and asof and asof < current_asof:
                    entry['warnings'].append(f'Older than current holdings ({current_asof}); will be skipped unless forced')
                if not errors and (holdings_pick is None or (asof or '9') > (holdings_pick[1] or '')):
                    holdings_pick = (rows, asof, safe)
            else:
                entry['errors'].append('Not a Wealthsimple activities export or holdings report (header does not match)')
            entry['ok'] = kind is not None and not entry['errors']
            if entry['ok']:
                inside(EXPORTS_DIR, stage / f'{i:02d}-{safe}').write_bytes(raw)
        except ImportError_ as e:
            entry['errors'].append(str(e))
        report.append(entry)

    merged, added, dupes = merge_activities(existing, incoming_acts)
    hold_rows = holdings_pick[0] if holdings_pick else None
    if hold_rows is None and HOLDINGS.exists():
        hold_rows = parse_holdings(HOLDINGS.read_text())[0]
    recon = _reconcile(merged, hold_rows) if merged and hold_rows else []
    before = summarize_activities(existing)
    after = summarize_activities(merged)
    new_symbols = sorted({(r['symbol'], r['currency']) for rows in incoming_acts for r in rows if r['symbol']} -
                         {(r['symbol'], r['currency']) for r in existing if r['symbol']})
    summary = dict(id=pid, files=report, added=added, duplicates=dupes, before=before, after=after,
                   holdings_asof=holdings_pick[1] if holdings_pick else None, current_holdings_asof=current_asof,
                   new_symbols=[f'{s} {c}' for s, c in new_symbols], reconciliation=recon[:30],
                   reconciliation_total=len(recon), committable=any(f['ok'] for f in report))
    (stage / 'preview.json').write_text(json.dumps(summary))
    return summary


def commit(pid, force_holdings=False):
    if not re.fullmatch(r'[0-9a-f]{16}', pid or ''):
        raise ImportError_('Bad preview id')
    stage = STAGING / pid
    if not (stage / 'preview.json').exists():
        raise ImportError_('Preview expired or not found; upload again')
    UPLOADS.mkdir(parents=True, exist_ok=True)
    existing = load_activity_rows()
    current_asof = holdings_asof()
    incoming, holdings_pick, archived = [], None, []
    stamp = dt.datetime.now().strftime('%Y%m%dT%H%M%S')
    for f in sorted(stage.glob('[0-9][0-9]-*')):
        text = _text(f.read_bytes())
        kind = detect(text)
        if kind == 'activities':
            rows, errors, _ = parse_activities(text)
            if not errors:
                incoming.append(rows)
        elif kind == 'holdings':
            rows, asof, errors = parse_holdings(text, f.name)
            if not errors and (holdings_pick is None or (asof or '9') > (holdings_pick[1] or '')):
                holdings_pick = (text, asof)
        dest = inside(EXPORTS_DIR, UPLOADS / f'{stamp}-{safe_name(f.name[3:], "upload.csv")}')
        shutil.copy2(f, dest)
        archived.append(dest.name)
    merged, added, dupes = merge_activities(existing, incoming)
    if incoming:
        _write_csv_atomic(ACTIVITIES, merged, ACTIVITY_COLUMNS)
    holdings_updated = False
    if holdings_pick:
        text, asof = holdings_pick
        if force_holdings or not current_asof or not asof or asof >= current_asof:
            tmp = HOLDINGS.with_suffix('.tmp')
            tmp.write_text(text)
            tmp.replace(HOLDINGS)
            holdings_updated = True
    new_symbols = {(r['symbol'], r['currency']) for rows in incoming for r in rows if r['symbol']} - \
                  {(r['symbol'], r['currency']) for r in existing if r['symbol']}
    shutil.rmtree(stage, ignore_errors=True)
    return dict(added=added, duplicates=dupes, holdings_updated=holdings_updated, archived=archived,
                new_symbols=len(new_symbols), activities=summarize_activities(merged), holdings_asof=holdings_asof())


def process_inbox():
    """Import every CSV dropped into inbox/. Returns commit results, or None when the inbox is empty."""
    if not INBOX.exists():
        INBOX.mkdir(parents=True, exist_ok=True)
        return None
    files = sorted(f for f in INBOX.glob('*.csv') if f.is_file() and not f.is_symlink())  # never follow links
    if not files:
        return None
    summary = preview([(f.name, f.read_bytes()) for f in files])
    result = commit(summary['id']) if summary['committable'] else dict(added=0, holdings_updated=False)
    result['files'] = summary['files']
    rejected = INBOX / 'rejected'
    for f, entry in zip(files, summary['files']):
        if entry['ok']:
            f.unlink()
        else:
            rejected.mkdir(exist_ok=True)
            f.replace(inside(EXPORTS_DIR, rejected / safe_name(f.name, 'rejected.csv')))
    return result


if __name__ == '__main__':
    import sys
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print('usage: python pipeline/store.py <export.csv> [...]   (validates, merges and archives)')
        sys.exit(1)
    s = preview([(p.name, p.read_bytes()) for p in paths])
    for f in s['files']:
        print(f"{'OK ' if f['ok'] else 'ERR'} {f['file']} [{f['kind']}] rows={f.get('rows')} {f['errors'][:3]} {f['warnings'][:3]}")
    print(f"new activity rows: {s['added']} · duplicates skipped: {s['duplicates']} · reconciliation issues: {s['reconciliation_total']}")
    for r in s['reconciliation'][:10]:
        print('  ', r)
    if s['committable']:
        print(json.dumps(commit(s['id']), indent=1))
    sys.exit(0 if s['committable'] else 2)
