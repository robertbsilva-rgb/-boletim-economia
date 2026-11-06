from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

BRT = dt.timezone(dt.timedelta(hours=-3), name="BRT")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def http_get_text(url: str, timeout: int = 12) -> Optional[str]:
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return resp.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


def http_get_json(url: str, timeout: int = 12) -> Any:
    text = http_get_text(url, timeout=timeout)
    if text:
        try:
            return json.loads(text)
        except Exception:
            pass
    return None


@dataclass
class QuoteItem:
    name: str
    symbol: str
    price: float
    change_pct: float
    unit: str = ""  # "R$", "US$", "%", "pts", ""


@dataclass
class MacroIndicator:
    name: str
    value: str
    reference: str = ""


@dataclass
class EconomicEvent:
    time_brt: str
    country: str
    title: str
    forecast: str = ""
    previous: str = ""


@dataclass
class DailyEconomyReport:
    date_str: str
    fx: List[QuoteItem]
    indices: List[QuoteItem]
    rates_inflation: List[MacroIndicator]
    commodities_crypto: List[QuoteItem]
    high_impact_events: List[EconomicEvent]


def _fetch_yahoo_quote(symbol: str, name: str, unit: str = "") -> Optional[QuoteItem]:
    """Busca cotação atual e variação percentual diária via endpoint JSON do Yahoo Finance."""
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d"
    data = http_get_json(url)
    if not data:
        url2 = f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d"
        data = http_get_json(url2)
    try:
        result = data["chart"]["result"][0]
        closes = [
            float(c)
            for c in result["indicators"]["quote"][0]["close"]
            if c is not None
        ]
        if not closes:
            meta_price = result.get("meta", {}).get("regularMarketPrice")
            prev_price = result.get("meta", {}).get("chartPreviousClose")
            if meta_price is None:
                return None
            last_close = float(meta_price)
            prev_close = float(prev_price) if prev_price else last_close
        else:
            last_close = closes[-1]
            prev_close = closes[-2] if len(closes) >= 2 else float(
                result.get("meta", {}).get("chartPreviousClose") or last_close
            )
        change_pct = ((last_close - prev_close) / prev_close * 100.0) if prev_close else 0.0
        return QuoteItem(
            name=name,
            symbol=symbol,
            price=last_close,
            change_pct=change_pct,
            unit=unit,
        )
    except Exception:
        return None


def fetch_fx_and_indices() -> tuple[List[QuoteItem], List[QuoteItem]]:
    """Coleta Câmbio (Dólar, Euro, DXY) e Bolsas (Ibovespa, S&P 500, Nasdaq)."""
    fx_list: List[QuoteItem] = []

    # 1. Tenta AwesomeAPI para USD-BRL e EUR-BRL
    data = http_get_json("https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL")
    if isinstance(data, dict):
        if "USDBRL" in data:
            d = data["USDBRL"]
            fx_list.append(
                QuoteItem(
                    name="Dólar Comercial",
                    symbol="USD/BRL",
                    price=float(d["bid"]),
                    change_pct=float(d.get("pctChange", 0.0)),
                    unit="R$",
                )
            )
        if "EURBRL" in data:
            e = data["EURBRL"]
            fx_list.append(
                QuoteItem(
                    name="Euro",
                    symbol="EUR/BRL",
                    price=float(e["bid"]),
                    change_pct=float(e.get("pctChange", 0.0)),
                    unit="R$",
                )
            )

    # Fallback para Yahoo Finance caso AwesomeAPI não retorne
    if not any(q.symbol == "USD/BRL" for q in fx_list):
        q = _fetch_yahoo_quote("USDBRL=X", "Dólar Comercial", "R$")
        if q:
            fx_list.append(q)
    if not any(q.symbol == "EUR/BRL" for q in fx_list):
        q = _fetch_yahoo_quote("EURBRL=X", "Euro", "R$")
        if q:
            fx_list.append(q)

    # Índice DXY (Força global do Dólar)
    dxy = _fetch_yahoo_quote("DX-Y.NYB", "Índice DXY (Dólar Global)", "pts")
    if dxy:
        fx_list.append(dxy)

    # Bolsas
    indices_specs = [
        ("^BVSP", "Ibovespa (BR)", "pts"),
        ("^GSPC", "S&P 500 (EUA)", "pts"),
        ("^IXIC", "Nasdaq (EUA)", "pts"),
    ]
    indices_list: List[QuoteItem] = []
    for sym, label, unit in indices_specs:
        item = _fetch_yahoo_quote(sym, label, unit)
        if item:
            indices_list.append(item)

    return fx_list, indices_list


def _fetch_bcb_sgs_latest(series_code: int) -> Optional[tuple[str, str]]:
    """Busca o último valor disponível de uma série do SGS do Banco Central do Brasil."""
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados/ultimos/1?formato=json"
    items = http_get_json(url)
    try:
        if items and isinstance(items, list):
            val = float(str(items[-1]["valor"]).replace(",", "."))
            date_ref = str(items[-1].get("data", ""))
            return f"{val:.2f}%".replace(".", ","), date_ref
    except Exception:
        pass
    return None


def _fetch_fed_funds_range() -> Optional[str]:
    """Busca a faixa atual do Fed Funds nos EUA via CSV público do FRED."""
    low_txt = http_get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARL")
    high_txt = http_get_text("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFEDTARU")
    try:
        if low_txt and high_txt:
            low_val = float(low_txt.strip().splitlines()[-1].split(",")[1])
            high_val = float(high_txt.strip().splitlines()[-1].split(",")[1])
            return f"{low_val:.2f}% - {high_val:.2f}%".replace(".", ",")
    except Exception:
        pass
    return None


def fetch_rates_and_inflation() -> List[MacroIndicator]:
    """Coleta Juros e Inflação (Selic, IPCA 12m, Treasury 10Y EUA, Fed Funds)."""
    indicators: List[MacroIndicator] = []

    # 1. Selic Meta (SGS 432)
    selic = _fetch_bcb_sgs_latest(432)
    if selic:
        indicators.append(
            MacroIndicator(name="Taxa Selic (Meta)", value=f"{selic[0]} a.a.")
        )

    # 2. IPCA acumulado 12 meses (SGS 13522)
    ipca_12m = _fetch_bcb_sgs_latest(13522)
    if ipca_12m:
        indicators.append(
            MacroIndicator(
                name="IPCA (Acum. 12m)",
                value=ipca_12m[0],
                reference=f"ref. {ipca_12m[1]}",
            )
        )

    # 3. Fed Funds Rate (EUA)
    fed_range = _fetch_fed_funds_range()
    if fed_range:
        indicators.append(
            MacroIndicator(name="Juros Fed (EUA)", value=f"{fed_range} a.a.")
        )

    # 4. US 10Y Treasury Yield (^TNX)
    us10y = _fetch_yahoo_quote("^TNX", "Treasury 10 Anos (EUA)", "%")
    if us10y:
        sign = "+" if us10y.change_pct >= 0 else ""
        val_str = f"{us10y.price:.2f}% ({sign}{us10y.change_pct:.2f}%)".replace(".", ",")
        indicators.append(
            MacroIndicator(name="Treasury 10Y (EUA)", value=val_str)
        )

    return indicators


def fetch_commodities_and_crypto() -> List[QuoteItem]:
    """Coleta Petróleo Brent, Ouro e Bitcoin."""
    specs = [
        ("BZ=F", "Petróleo Brent", "US$"),
        ("GC=F", "Ouro (Spot/Fut)", "US$"),
        ("BTC-USD", "Bitcoin", "US$"),
    ]
    results: List[QuoteItem] = []
    for sym, label, unit in specs:
        item = _fetch_yahoo_quote(sym, label, unit)
        if item:
            results.append(item)
    return results


_EVENT_TRANSLATIONS: Dict[str, str] = {
    "Non-Farm Employment Change": "Payroll (Criação de Empregos)",
    "Unemployment Rate": "Taxa de Desemprego",
    "Average Hourly Earnings m/m": "Salário Médio por Hora (m/m)",
    "CPI m/m": "Inflação CPI (m/m)",
    "CPI y/y": "Inflação CPI (a/a)",
    "Core CPI m/m": "Núcleo do CPI (m/m)",
    "Core PCE Price Index m/m": "Inflação PCE (Favorita do Fed)",
    "Federal Funds Rate": "Decisão de Juros do Fed (FOMC)",
    "FOMC Statement": "Comunicado do FOMC (Fed)",
    "FOMC Press Conference": "Coletiva de Jerome Powell (Fed)",
    "FOMC Meeting Minutes": "Ata do FOMC (Fed)",
    "Advance GDP q/q": "PIB dos EUA (Prévia t/t)",
    "Prelim GDP q/q": "PIB dos EUA (Preliminar t/t)",
    "Final GDP q/q": "PIB dos EUA (Final t/t)",
    "Retail Sales m/m": "Vendas no Varejo (m/m)",
    "ISM Manufacturing PMI": "PMI Industrial ISM",
    "ISM Services PMI": "PMI de Serviços ISM",
    "Unemployment Claims": "Pedidos de Auxílio-Desemprego",
    "JOLTS Job Openings": "Vagas Abertas (JOLTS)",
    "PPI m/m": "Inflação ao Produtor PPI (m/m)",
    "Main Refinancing Rate": "Decisão de Juros do BCE (Europa)",
}

_COUNTRY_FLAGS: Dict[str, str] = {
    "USD": "🇺🇸 EUA",
    "EUR": "🇪🇺 Zona do Euro",
    "CNY": "🇨🇳 China",
    "GBP": "🇬🇧 Reino Unido",
    "JPY": "🇯🇵 Japão",
    "BRL": "🇧🇷 Brasil",
}


def fetch_high_impact_calendar(now_brt: Optional[dt.datetime] = None) -> List[EconomicEvent]:
    """Busca eventos econômicos de alto impacto agendados para hoje."""
    if now_brt is None:
        now_brt = dt.datetime.now(BRT)
    today_date = now_brt.date()
    events: List[EconomicEvent] = []

    raw_events = http_get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    if isinstance(raw_events, list):
        for ev in raw_events:
            try:
                if ev.get("impact") != "High":
                    continue
                country_code = ev.get("country", "")
                if country_code not in ("USD", "EUR", "CNY", "BRL"):
                    continue
                date_iso = ev.get("date", "")
                if not date_iso:
                    continue
                ev_dt = dt.datetime.fromisoformat(date_iso).astimezone(BRT)
                if ev_dt.date() != today_date:
                    continue
                raw_title = str(ev.get("title", "")).strip()
                title_pt = _EVENT_TRANSLATIONS.get(raw_title, raw_title)
                events.append(
                    EconomicEvent(
                        time_brt=ev_dt.strftime("%H:%M"),
                        country=_COUNTRY_FLAGS.get(country_code, country_code),
                        title=title_pt,
                        forecast=str(ev.get("forecast", "") or ""),
                        previous=str(ev.get("previous", "") or ""),
                    )
                )
            except Exception:
                continue

    # Lembrete automático de Boletim Focus toda segunda-feira
    if today_date.weekday() == 0:
        events.insert(
            0,
            EconomicEvent(
                time_brt="08:25",
                country="🇧🇷 Brasil",
                title="Divulgação do Boletim Focus (Banco Central)",
            ),
        )

    events.sort(key=lambda e: e.time_brt)
    return events


def collect_daily_report() -> DailyEconomyReport:
    """Executa toda a coleta diária e retorna o relatório consolidado."""
    now_brt = dt.datetime.now(BRT)
    fx, indices = fetch_fx_and_indices()
    rates_inflation = fetch_rates_and_inflation()
    commodities_crypto = fetch_commodities_and_crypto()
    events = fetch_high_impact_calendar(now_brt)

    return DailyEconomyReport(
        date_str=now_brt.strftime("%d/%m/%Y"),
        fx=fx,
        indices=indices,
        rates_inflation=rates_inflation,
        commodities_crypto=commodities_crypto,
        high_impact_events=events,
    )
