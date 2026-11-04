import ast
from datetime import datetime
import importlib.util
from pathlib import Path
import pytest
from nifty_l2 import legacy_engine as engine
from nifty_l2.storage import Store
from nifty_l2.replay import replay

ROOT = Path(__file__).resolve().parents[1]


def test_extracted_logic_ast_parity():
    spec = importlib.util.spec_from_file_location('extract', ROOT / 'scripts/extract_engine.py')
    extract = importlib.util.module_from_spec(spec); spec.loader.exec_module(extract)
    original = extract.transformed_tree()
    generated = ast.parse((ROOT / 'nifty_l2/legacy_engine.py').read_text())
    names = {n.name for n in original.body if isinstance(n, ast.FunctionDef)}
    actual = [n for n in generated.body if isinstance(n, ast.FunctionDef) and n.name in names]
    expected = [n for n in original.body if isinstance(n, ast.FunctionDef)]
    assert ast.dump(ast.Module(body=actual, type_ignores=[])) == ast.dump(ast.Module(body=expected, type_ignores=[]))


def test_unit_conversion_and_greek_scenario():
    assert engine.to_contract_lots(1500, 75) == 20
    ce = {'option_type': 'CE', 'ltp': 150, 'greeks': {'iv': 15}}
    pe = {'option_type': 'PE', 'ltp': 150, 'greeks': {'iv': 15}}
    c = engine.get_greeks_safe(ce, 24000, 7, 15, fut_price=24000)
    p = engine.get_greeks_safe(pe, 24000, 7, 15, fut_price=24000)
    assert 0 < c['delta'] < 1 and -1 < p['delta'] < 0
    assert c['gamma'] == p['gamma'] and c['gamma'] > 0


def test_missing_data_replay_persists_unavailable_and_is_idempotent(tmp_path):
    store = Store(tmp_path / 'replay.db')
    calls = [{'method': 'optionchain', 'request': {'symbol': engine.NIFTY_SPOT_SYM, 'strikecount': 1, 'timestamp': ''}, 'response': {'s': 'error'}}]
    result = replay(store, observed_at='2026-11-03T09:18:00+05:30', calls=calls)
    assert result['classification'] == 'No Trade'
    assert replay(store, observed_at='2026-11-03T09:18:00+05:30', calls=calls)['duplicate']
    assert store.integrity()['counts']['check_results'] == 18


def test_replay_mismatch_rolls_back(tmp_path):
    store = Store(tmp_path / 'replay.db')
    with pytest.raises(ValueError, match='mismatch'):
        replay(store, observed_at='2026-11-03T09:18:00+05:30', calls=[{'method': 'quotes', 'request': {}, 'response': {}}])
    assert store.integrity()['counts']['events'] == 0


def fixture_calls(tick, dt):
    from datetime import timedelta
    symbol = 'NSE:NIFTY26NOVFUT'
    chain = [{'option_type': '', 'strike_price': -1, 'ltp': 24000 + tick * 5}]
    for strike in range(23900, 24101, 50):
        for side in ('CE', 'PE'):
            chain.append({'option_type': side, 'strike_price': strike,
                          'symbol': f'NSE:NIFTY26NOV{strike}{side}', 'ltp': 120 - tick,
                          'bid': 119.8 - tick, 'ask': 120.2 - tick,
                          'oi': (10000 - tick * 500) if side == 'CE' else (20000 + tick * 1500),
                          'volume': 50000 + tick * 5000, 'oich': 0, 'oichp': 0,
                          'greeks': {'iv': 15}})
    def call(method, request, response):
        return {'method': method, 'request': request, 'response': response}
    bars = []
    for i in range(3):
        ts = int((dt - timedelta(minutes=9 - i * 3)).timestamp())
        bars.append([ts, 24000+i*5, 24020+i*5, 23990+i*5, 24010+i*5, 1000, 50000+i*100])
    return [
        call('optionchain', {'symbol': 'NSE:NIFTY50-INDEX', 'strikecount': 1, 'timestamp': ''},
             {'s': 'ok', 'data': {'expiryData': [{'date': '05-11-2026', 'expiry': 1793894400}]}}),
        call('optionchain', {'symbol': 'NSE:NIFTY50-INDEX', 'strikecount': 10, 'timestamp': '1793894400', 'greeks': '1'},
             {'s': 'ok', 'data': {'optionsChain': chain, 'indiavixData': {'ltp': 15, 'ltpchp': 1}}}),
        call('quotes', {'symbols': ','.join(engine.TOP5_STOCKS)},
             {'s': 'ok', 'd': [{'n': s, 'v': {'lp': 110, 'atp': 100}} for s in engine.TOP5_STOCKS]}),
        call('quotes', {'symbols': 'NSE:NIFTY26NOVFUT,NSE:NIFTY26DECFUT'},
             {'s': 'ok', 'd': [{'s': 'ok', 'n': symbol, 'v': {'lp': 24020}}]}),
        call('history', {'symbol': symbol, 'resolution': '3', 'date_format': '1', 'range_from': '2026-10-30',
                         'range_to': '2026-11-03', 'cont_flag': '1', 'oi_flag': '1'}, {'s': 'ok', 'candles': bars}),
        call('history', {'symbol': 'NSE:NIFTY50-INDEX', 'resolution': '5', 'date_format': '1', 'range_from': '2026-10-22',
                         'range_to': '2026-11-03', 'cont_flag': '1'}, {'s': 'error', 'candles': []}),
    ]


def test_all_nine_checks_across_three_replayed_observations(tmp_path, monkeypatch):
    from datetime import timedelta
    monkeypatch.setenv('NIFTY_FUT_SYMBOL', '')
    monkeypatch.setenv('ACTIVE_INDEX', 'NIFTY')
    store = Store(tmp_path / 'three-windows.db')
    base = datetime.fromisoformat('2026-11-03T09:24:00+05:30')
    for tick in range(3):
        dt = base + timedelta(minutes=3 * tick)
        result = replay(store, observed_at=dt, calls=fixture_calls(tick, dt))
        assert len(result['state']['scorecard']) == 9
        assert result['state']['scorecard'][0]['Bull_Status'] == 'PASS'
        assert result['classification'] == 'No Trade'
    assert result['state']['scorecard'][1]['Bull_Status'] == 'PASS'
    counts = store.integrity()['counts']
    assert counts['check_results'] == 54
    assert counts['header_snapshots'] == 3
    assert counts['option_snapshots'] == 30
    assert counts['futures_data'] == 3
