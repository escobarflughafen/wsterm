"""Uploads and the inbox are untrusted input: names, paths and sizes must never escape the exports store."""
import pytest

import store
from settings import EXPORTS_DIR


def header():
    return ','.join(store.ACTIVITY_COLUMNS) + '\n'


@pytest.mark.parametrize('name, expected', [
    ('../../etc/passwd', 'passwd'),
    ('/etc/shadow', 'shadow'),
    ('..', 'fallback.csv'),
    ('', 'fallback.csv'),
    (None, 'fallback.csv'),
    ('..\\..\\windows\\system32\\cfg', '_.._windows_system32_cfg'),   # backslashes are not separators here
    ('a b;rm -rf /.csv', 'csv'),                                    # everything before the last slash is dropped
    ('.' * 90 + 'x.csv', 'x.csv'),
    ('%2e%2e%2fetc.csv', '_2e_2e_2fetc.csv'),                       # no URL decoding, so no second chance to escape
    ('a\x00b.csv', 'a_b.csv'),                                      # NUL cannot reach the filesystem
])
def test_filenames_are_reduced_to_a_safe_basename(name, expected):
    assert store.safe_name(name, 'fallback.csv') == expected


def test_uploads_stay_inside_the_exports_directory(fixture_bytes):
    evil = [('../../../../tmp/escape.csv', fixture_bytes('activities_jan.csv')[1]),
            ('/etc/passwd.csv', fixture_bytes('holdings_jan.csv')[1])]
    s = store.preview(evil)
    assert s['committable']
    staged = list((store.STAGING / s['id']).glob('[0-9][0-9]-*'))
    assert staged and all(p.resolve().is_relative_to(EXPORTS_DIR.resolve()) for p in staged)
    assert [f['file'] for f in s['files']] == ['escape.csv', 'passwd.csv']
    result = store.commit(s['id'])
    for archived in result['archived']:
        assert (store.UPLOADS / archived).resolve().is_relative_to(EXPORTS_DIR.resolve())
        assert '/' not in archived and '..' not in archived


def test_inside_rejects_paths_outside_the_store():
    with pytest.raises(store.ImportError_):
        store.inside(EXPORTS_DIR, EXPORTS_DIR / '..' / 'escape.csv')
    assert store.inside(EXPORTS_DIR, EXPORTS_DIR / 'ok.csv').name == 'ok.csv'


def test_commit_rejects_forged_preview_ids():
    for bad in ('../../etc', 'zzzzzzzzzzzzzzzz', '', 'a' * 15, None):
        with pytest.raises(store.ImportError_):
            store.commit(bad)


def test_inbox_ignores_symlinks(fixture_bytes, tmp_path):
    store.INBOX.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / 'secret.csv'
    secret.write_text(header() + '2026-01-01,10:00:00,,X,TFSA,Trade,BUY,d,LONG,X,X,X,USD,1,1,0,-1\n')
    (store.INBOX / 'link.csv').symlink_to(secret)
    (store.INBOX / 'real.csv').write_bytes(fixture_bytes('activities_jan.csv')[1])
    result = store.process_inbox()
    assert result['added'] == 4                      # only the real file was imported
    assert (store.INBOX / 'link.csv').is_symlink()   # left untouched, never read
    (store.INBOX / 'link.csv').unlink()
