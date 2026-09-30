"""Fixture replay for CoinGecko, Frankfurter and the markdown tool/flight
parsers, plus atomic persistence and CLI bounds (no network)."""

import csv
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import atomic_io  # noqa: E402
import scrape_ai_tools  # noqa: E402
import scrape_crypto_prices as crypto  # noqa: E402
import scrape_exchange_rates as fx  # noqa: E402
import scrape_flight_prices as flights  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def _csv(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _quiet(fn, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# --- CoinGecko -------------------------------------------------------------

def test_crypto_snapshot_history_and_alerts_from_fixture(tmp_path):
    data = _json("coingecko_simple_price.json")
    with patch.object(crypto.httpx, "get", return_value=FakeResponse(data)) as get:
        fetched = crypto.fetch_prices(["bitcoin", "ethereum"], ["usd", "thb"])
    assert get.call_args.kwargs["params"]["ids"] == "bitcoin,ethereum"
    _quiet(crypto.save_prices, fetched, ["usd", "thb"], tmp_path)
    _quiet(crypto.append_history, fetched, ["usd", "thb"], tmp_path)
    _quiet(crypto.append_history, fetched, ["usd", "thb"], tmp_path)
    snapshot = _csv(tmp_path / "crypto_prices.csv")
    # "unknown-coin": {} still yields rows with blank values, not a crash.
    assert len(snapshot) == 6
    eth_thb = next(r for r in snapshot if r["coin_id"] == "ethereum" and r["currency"] == "thb")
    assert eth_thb["change_24h_pct"] == "0"
    assert len(_csv(tmp_path / "crypto_history.csv")) == 12
    alerts = _quiet(crypto.print_alerts, fetched, 5.0, ["usd", "thb"])
    assert {(a["coin"], a["currency"], a["direction"]) for a in alerts} == {
        ("bitcoin", "usd", "DOWN"), ("bitcoin", "thb", "DOWN")}


def test_crypto_trending_skips_partial_entries(tmp_path):
    with patch.object(crypto.httpx, "get", return_value=FakeResponse(_json("coingecko_trending.json"))):
        trending = crypto.fetch_trending()
    assert [c["id"] for c in trending] == ["pepe", "newcoin"]
    assert crypto.parse_trending({"coins": "nope"}) == []
    assert crypto.parse_trending(None) == []
    _quiet(crypto.save_trending, trending, tmp_path)
    assert [r["symbol"] for r in _csv(tmp_path / "crypto_trending.csv")] == ["PEPE", "NEW"]


def test_crypto_skips_non_object_coin_entries(tmp_path):
    _quiet(crypto.save_prices, {"bitcoin": None, "eth": {"usd": 1}}, ["usd"], tmp_path)
    assert [r["coin_id"] for r in _csv(tmp_path / "crypto_prices.csv")] == ["eth"]


@pytest.mark.parametrize("argv", [
    ["--coins", "bitcoin,<script>"],
    ["--coins", " , "],
    ["--vs-currencies", "usd,dollars!"],
    ["--alert-threshold", "-1"],
    ["--coins", ",".join(f"c{i}" for i in range(51))],
])
def test_crypto_cli_rejects_bad_input_before_network(argv):
    with patch.object(crypto.httpx, "get") as get, redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as ctx:
            crypto.main(argv)
    assert ctx.value.code == 2
    get.assert_not_called()


def test_crypto_cli_normalises_ids(tmp_path):
    data = _json("coingecko_simple_price.json")
    with patch.object(crypto.httpx, "get", return_value=FakeResponse(data)) as get:
        _quiet(crypto.main, ["--coins", "Bitcoin, ethereum,bitcoin", "--vs-currencies", "USD",
                             "--no-trending", "--output-dir", str(tmp_path)])
    assert get.call_args.kwargs["params"]["ids"] == "bitcoin,ethereum"
    assert get.call_args.kwargs["params"]["vs_currencies"] == "usd"


# --- Frankfurter -----------------------------------------------------------

def test_fx_latest_drops_non_numeric_rates():
    with patch.object(fx.httpx, "get", return_value=FakeResponse(_json("frankfurter_latest.json"))):
        data = fx.fetch_latest("THB", ["USD", "EUR", "JPY"])
    assert data["date"] == "2026-09-25"
    assert set(data["rates"]) == {"USD", "EUR", "JPY"}
    assert fx.parse_latest("garbage", "THB") == {"base": "THB", "date": "", "rates": {}}


def test_fx_history_is_date_sorted_and_trend_detected():
    with patch.object(fx.httpx, "get", return_value=FakeResponse(_json("frankfurter_timeseries.json"))):
        history = fx.fetch_history("THB", ["USD", "EUR"], days=10)
    dates = [row["date"] for row in history]
    assert dates == sorted(dates) and "bad-day" not in dates
    usd = fx.detect_trend(history, "USD", lookback=7)
    assert usd["direction"] == "strengthening"
    assert usd["from_rate"] == 0.0291 and usd["to_rate"] == 0.0300
    assert fx.detect_trend(history, "EUR", lookback=7)["direction"] == "stable"
    assert fx.detect_trend(history[:3], "USD", lookback=7)["direction"] == "unknown"


def test_fx_history_skips_duplicate_rate_dates(tmp_path):
    data = fx.parse_latest(_json("frankfurter_latest.json"), "THB")
    _quiet(fx.save_rates, data, tmp_path, {"USD": {"direction": "stable", "change_pct": 0.1}})
    assert _quiet(fx.append_history, data, tmp_path) == 3
    assert _quiet(fx.append_history, data, tmp_path) == 0
    newer = {**data, "date": "2026-09-26"}
    assert _quiet(fx.append_history, newer, tmp_path) == 3
    assert len(_csv(tmp_path / "exchange_history.csv")) == 6
    rates = {r["currency"]: r for r in _csv(tmp_path / "exchange_rates.csv")}
    assert rates["USD"]["trend_7d"] == "stable"


@pytest.mark.parametrize("argv", [
    ["--base", "BAHT"],
    ["--symbols", "USD,E1R"],
    ["--symbols", "THB"],
    ["--alert-threshold", "-0.1"],
])
def test_fx_cli_rejects_bad_input_before_network(argv):
    with patch.object(fx.httpx, "get") as get, redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as ctx:
            fx.main(argv)
    assert ctx.value.code == 2
    get.assert_not_called()


# --- Markdown parsers ------------------------------------------------------

def test_parse_producthunt_fixture():
    products = scrape_ai_tools.parse_producthunt(_text("producthunt_ai.md"))
    assert [(p["name"], p["description"]) for p in products] == [
        ("Notewise", "AI meeting notes that write themselves"),
        ("Pixelmate", "Generate product photos"),
    ]
    assert all(p["source"] == "ProductHunt" for p in products)


def test_parse_taft_fixture_dedupes_and_ignores_other_links():
    tools = scrape_ai_tools.parse_taft(_text("taaft_most_saved.md"))
    assert [(t["name"], t["url"]) for t in tools] == [
        ("ChatHelper", "https://theresanaiforthat.com/ai/chathelper/"),
        ("VoiceClone", "https://theresanaiforthat.com/ai/voiceclone/"),
    ]


def test_parse_skyscanner_takes_cheapest_real_fare_and_survives_bare_symbol():
    rows = flights.parse_skyscanner(_text("skyscanner_bkk_sin.md"), "BKK", "SIN")
    assert len(rows) == 1
    assert rows[0]["price_thb"] == 3450
    assert rows[0]["url"].endswith("/bkk/sin/")
    assert flights.parse_skyscanner("฿, only", "BKK", "SIN") == []
    assert flights.parse_skyscanner("fees ฿120", "BKK", "SIN") == []


# --- Persistence ordering and atomic writes --------------------------------

def test_flight_alerts_compare_against_previous_run(tmp_path, monkeypatch):
    monkeypatch.setattr(flights, "OUTPUT_DIR", tmp_path)
    route = {"origin": "BKK", "destination": "SIN", "price_thb": 5000, "source": "Skyscanner"}
    monkeypatch.setattr(flights, "fetch_kiwi_tequila", lambda *a: [])
    monkeypatch.setattr(flights, "fetch_skyscanner_free", lambda *a: [dict(route)])
    _quiet(flights.main, routes=[("BKK", "SIN")])
    route["price_thb"] = 4000
    out = io.StringIO()
    with redirect_stdout(out):
        flights.main(routes=[("BKK", "SIN")])
    assert "PRICE DROP -20.0%" in out.getvalue()
    assert [r["price_thb"] for r in _csv(tmp_path / "flight_prices_history.csv")] == ["5000", "4000"]


@pytest.mark.parametrize("argv", [["--days-ahead", "0"], ["--days-ahead", "181"], ["--alert-drop-pct", "0"]])
def test_flight_cli_bounds(argv):
    with redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as ctx:
            flights.cli(argv)
    assert ctx.value.code == 2


def test_ai_tools_new_urls_are_detected_before_history_append(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape_ai_tools, "OUTPUT_DIR", tmp_path)
    first = [{"name": "A", "description": "", "url": "https://x/a", "source": "t"}]
    assert [t["url"] for t in _quiet(scrape_ai_tools.persist_tools, first)] == ["https://x/a"]
    second = first + [{"name": "B", "description": "", "url": "https://x/b", "source": "t"}]
    assert [t["url"] for t in _quiet(scrape_ai_tools.persist_tools, second)] == ["https://x/b"]
    assert len(_csv(tmp_path / "ai_tools_history.csv")) == 3


def test_atomic_write_keeps_previous_snapshot_on_failure(tmp_path):
    target = tmp_path / "snap.csv"
    target.write_text("previous", encoding="utf-8")
    with patch.object(atomic_io.os, "replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            atomic_io.write_text_atomic(target, "partial")
    assert target.read_text(encoding="utf-8") == "previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snap.csv"]
