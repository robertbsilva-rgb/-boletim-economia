from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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


def http_request(
    method: str,
    url: str,
    payload: Any = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> Tuple[int, str]:
    req_headers = {"User-Agent": "EconomyBriefingBot/1.0"}
    if headers:
        req_headers.update(headers)
    data_bytes = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return exc.code, body


@dataclass
class QuoteItem:
    name: str
    symbol: str
    price: float
    change_pct: float
    unit: str = ""


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
    encoded = urllib.parse.quote(symbol)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d"
    data = http_get_json(url) or http_get_json(
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}?range=5d&interval=1d"
    )
    try:
        result = data["chart"]["result"][0]
        closes = [float(c) for c in result["indicators"]["quote"][0]["close"] if c is not None]
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
        return QuoteItem(name=name, symbol=symbol, price=last_close, change_pct=change_pct, unit=unit)
    except Exception:
        return None


def fetch_fx_and_indices() -> tuple[List[QuoteItem], List[QuoteItem]]:
    fx_list: List[QuoteItem] = []
    data = http_get_json("https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL")
    if isinstance(data, dict):
        if "USDBRL" in data:
            d = data["USDBRL"]
            fx_list.append(
                QuoteItem("Dólar Comercial", "USD/BRL", float(d["bid"]), float(d.get("pctChange", 0.0)), "R$")
            )
        if "EURBRL" in data:
            e = data["EURBRL"]
            fx_list.append(
                QuoteItem("Euro", "EUR/BRL", float(e["bid"]), float(e.get("pctChange", 0.0)), "R$")
            )

    if not any(q.symbol == "USD/BRL" for q in fx_list):
        q = _fetch_yahoo_quote("USDBRL=X", "Dólar Comercial", "R$")
        if q:
            fx_list.append(q)
    if not any(q.symbol == "EUR/BRL" for q in fx_list):
        q = _fetch_yahoo_quote("EURBRL=X", "Euro", "R$")
        if q:
            fx_list.append(q)

    dxy = _fetch_yahoo_quote("DX-Y.NYB", "Índice DXY (Dólar Global)", "pts")
    if dxy:
        fx_list.append(dxy)

    indices_list: List[QuoteItem] = []
    for sym, label, unit in [
        ("^BVSP", "Ibovespa (BR)", "pts"),
        ("^GSPC", "S&P 500 (EUA)", "pts"),
        ("^IXIC", "Nasdaq (EUA)", "pts"),
    ]:
        item = _fetch_yahoo_quote(sym, label, unit)
        if item:
            indices_list.append(item)

    return fx_list, indices_list


def _fetch_bcb_sgs_latest(series_code: int) -> Optional[tuple[str, str]]:
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


def fetch_rates_and_inflation() -> List[MacroIndicator]:
    indicators: List[MacroIndicator] = []
    selic = _fetch_bcb_sgs_latest(432)
    if selic:
        indicators.append(MacroIndicator(name="Taxa Selic (Meta)", value=f"{selic[0]} a.a."))
    ipca_12m = _fetch_bcb_sgs_latest(13522)
    if ipca_12m:
        indicators.append(MacroIndicator(name="IPCA (Acum. 12m)", value=ipca_12m[0], reference=f"ref. {ipca_12m[1]}"))
    us10y = _fetch_yahoo_quote("^TNX", "Treasury 10 Anos (EUA)", "%")
    if us10y:
        sign = "+" if us10y.change_pct >= 0 else ""
        val_str = f"{us10y.price:.2f}% ({sign}{us10y.change_pct:.2f}%)".replace(".", ",")
        indicators.append(MacroIndicator(name="Treasury 10Y (EUA)", value=val_str))
    return indicators


def fetch_commodities_and_crypto() -> List[QuoteItem]:
    results: List[QuoteItem] = []
    for sym, label, unit in [
        ("BZ=F", "Petróleo Brent", "US$"),
        ("GC=F", "Ouro (Spot/Fut)", "US$"),
        ("BTC-USD", "Bitcoin", "US$"),
    ]:
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


def fetch_high_impact_calendar(now_brt: dt.datetime) -> List[EconomicEvent]:
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


def _find_quote(items: list[QuoteItem], keyword: str) -> Optional[QuoteItem]:
    for item in items:
        if keyword.lower() in item.name.lower() or keyword.lower() in item.symbol.lower():
            return item
    return None


def _build_deterministic_summary(report: DailyEconomyReport) -> str:
    usd = _find_quote(report.fx, "Dólar")
    ibov = _find_quote(report.indices, "Ibovespa")
    sp500 = _find_quote(report.indices, "S&P 500")

    parts: list[str] = []
    if sp500 and ibov:
        if sp500.change_pct >= 0 and ibov.change_pct >= 0:
            parts.append("Clima construtivo nos mercados, com apetite a risco tanto em Wall Street quanto no Ibovespa.")
        elif sp500.change_pct < 0 and ibov.change_pct < 0:
            parts.append("Sessão de cautela e aversão a risco no exterior e no mercado local.")
        else:
            parts.append("Mercados operam de forma mista entre o cenário doméstico e as bolsas americanas.")

    if usd:
        direcao = "avança" if usd.change_pct > 0.05 else ("recua" if usd.change_pct < -0.05 else "opera estável")
        preco_str = f"{usd.price:.2f}".replace(".", ",")
        var_str = f"{usd.change_pct:+.2f}%".replace(".", ",")
        parts.append(f"No câmbio, o dólar {direcao} a R$ {preco_str} ({var_str}).")

    if report.high_impact_events:
        nomes = ", ".join(e.title for e in report.high_impact_events[:2])
        parts.append(f"Atenção hoje para a agenda de alto impacto: {nomes}.")
    else:
        parts.append("Agenda do dia sem divulgações macroeconômicas de alto impacto, mantendo o foco no fluxo global.")

    return " ".join(parts)


def generate_market_summary(report: DailyEconomyReport) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "sua_chave_gemini_aqui":
        return _build_deterministic_summary(report)

    try:
        fx_txt = ", ".join(f"{q.name}: {q.price:.2f} ({q.change_pct:+.2f}%)" for q in report.fx)
        idx_txt = ", ".join(f"{q.name}: {q.price:,.0f} ({q.change_pct:+.2f}%)" for q in report.indices)
        macro_txt = ", ".join(f"{m.name}: {m.value}" for m in report.rates_inflation)
        comm_txt = ", ".join(f"{q.name}: {q.price:.2f} ({q.change_pct:+.2f}%)" for q in report.commodities_crypto)
        events_txt = (
            "; ".join(f"{e.time_brt} {e.country} {e.title}" for e in report.high_impact_events)
            if report.high_impact_events
            else "Sem eventos de alto impacto hoje"
        )
        prompt = (
            "Você é um economista-chefe escrevendo o resumo matinal para WhatsApp.\n"
            "Com base APENAS nos dados abaixo, escreva um parágrafo curto de 2 a 3 linhas "
            "(máximo 320 caracteres) em português claro e direto explicando o humor do mercado "
            "e o que merece atenção hoje. Não use saudações nem listas.\n\n"
            f"Câmbio: {fx_txt}\nBolsas: {idx_txt}\nJuros/Inflação: {macro_txt}\n"
            f"Commodities/Cripto: {comm_txt}\nAgenda de Hoje: {events_txt}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        status, body = http_request("POST", url, payload={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        if status == 200:
            data = json.loads(body)
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            if text:
                return text
    except Exception:
        pass
    return _build_deterministic_summary(report)


def _arrow(change_pct: float) -> str:
    if change_pct > 0.05:
        return "🟢"
    if change_pct < -0.05:
        return "🔴"
    return "⚪"


def _fmt_br_number(val: float, decimals: int = 2) -> str:
    formatted = f"{val:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_quote_line(q: QuoteItem) -> str:
    icon = _arrow(q.change_pct)
    pct_str = f"{q.change_pct:+.2f}%".replace(".", ",")
    if q.unit == "R$":
        price_str = f"R$ {_fmt_br_number(q.price, 2)}"
    elif q.unit == "US$":
        decimals = 0 if q.price >= 1000 else 2
        price_str = f"US$ {_fmt_br_number(q.price, decimals)}"
    elif q.unit == "pts":
        decimals = 0 if q.price >= 1000 else 2
        price_str = f"{_fmt_br_number(q.price, decimals)} pts"
    else:
        price_str = _fmt_br_number(q.price, 2)
    return f"{icon} *{q.name}:* {price_str} ({pct_str})"


def format_whatsapp_message(report: DailyEconomyReport, market_summary: str) -> str:
    lines: list[str] = [
        f"📊 *BOLETIM ECONÔMICO DIÁRIO* — _{report.date_str}_",
        "",
        "💡 *Termômetro do Mercado*",
        market_summary.strip(),
        "",
        "💱 *Câmbio & Bolsas*",
    ]
    for q in report.fx:
        lines.append(_format_quote_line(q))
    for q in report.indices:
        lines.append(_format_quote_line(q))

    lines.append("")
    lines.append("🏦 *Juros & Inflação (BR / EUA)*")
    for m in report.rates_inflation:
        ref = f" _{m.reference}_" if m.reference else ""
        lines.append(f"• *{m.name}:* {m.value}{ref}")

    lines.append("")
    lines.append("🛢️ *Commodities & Cripto*")
    for q in report.commodities_crypto:
        lines.append(_format_quote_line(q))

    lines.append("")
    lines.append("📅 *Agenda do Dia (Alto Impacto)*")
    if report.high_impact_events:
        for ev in report.high_impact_events:
            extra = f" _(Proj: {ev.forecast})_" if ev.forecast else ""
            lines.append(f"⏰ *{ev.time_brt}* | {ev.country}: {ev.title}{extra}")
    else:
        lines.append("• Sem divulgações críticas (3⭐) previstas para hoje.")
    return "\n".join(lines)


def _resolve_greenapi_host(id_instance: str) -> str:
    custom = os.getenv("GREENAPI_HOST", "").strip().rstrip("/")
    if custom:
        return custom
    if len(id_instance) >= 4 and id_instance[:4].isdigit():
        return f"https://{id_instance[:4]}.api.greenapi.com"
    return "https://api.green-api.com"


def _resolve_brazil_chat_id(base_url: str, id_instance: str, api_token: str, phone: str) -> str:
    if "@" in phone:
        return phone
    clean_phone = "".join(ch for ch in phone if ch.isdigit())
    if not clean_phone.startswith("55") and len(clean_phone) in (10, 11):
        clean_phone = "55" + clean_phone

    try:
        settings_url = f"{base_url}/waInstance{id_instance}/getSettings/{api_token}"
        status, body = http_request("GET", settings_url, timeout=10)
        if status == 200:
            wid = str(json.loads(body).get("wid", ""))
            wid_digits = wid.split("@")[0]
            if wid_digits and clean_phone[-8:] == wid_digits[-8:] and clean_phone[:4] == wid_digits[:4]:
                return wid
    except Exception:
        pass

    if clean_phone.startswith("55") and len(clean_phone) == 13 and clean_phone[4] == "9":
        without_nine = clean_phone[:4] + clean_phone[5:]
        try:
            check_url = f"{base_url}/waInstance{id_instance}/checkWhatsapp/{api_token}"
            status, body = http_request("POST", check_url, payload={"phoneNumber": int(without_nine)}, timeout=10)
            if status == 200 and json.loads(body).get("existsWhatsapp") is True:
                return f"{without_nine}@c.us"
        except Exception:
            pass
    return f"{clean_phone}@c.us"


def send_whatsapp_message(message: str) -> bool:
    id_instance = os.getenv("GREENAPI_ID_INSTANCE", "").strip()
    api_token = os.getenv("GREENAPI_API_TOKEN", "").strip()
    phone = os.getenv("GREENAPI_PHONE", "").strip()

    if not id_instance or not api_token or not phone:
        raise RuntimeError(
            "Configure GREENAPI_ID_INSTANCE, GREENAPI_API_TOKEN e GREENAPI_PHONE no .env ou nos Secrets do GitHub."
        )

    hosts = [_resolve_greenapi_host(id_instance), "https://api.green-api.com"]
    last_error = ""
    for base_url in dict.fromkeys(hosts):
        try:
            chat_id = _resolve_brazil_chat_id(base_url, id_instance, api_token, phone)
            url = f"{base_url}/waInstance{id_instance}/sendMessage/{api_token}"
            status, body = http_request("POST", url, payload={"chatId": chat_id, "message": message}, timeout=20)
            if status == 200:
                return True
            last_error = f"({status}) {body[:250]}"
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"Erro Green-API: {last_error}")


def _load_env_file() -> None:
    env_path = pathlib.Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _load_env_file()

    parser = argparse.ArgumentParser(description="Gera e envia o Boletim Econômico Diário para o WhatsApp.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("⏳ Coletando indicadores econômicos nacionais e internacionais...")
    report = collect_daily_report()

    print("🧠 Gerando resumo executivo do mercado...")
    summary = generate_market_summary(report)

    message = format_whatsapp_message(report, summary)

    print("\n" + "=" * 60)
    print("PRÉVIA DA MENSAGEM DO WHATSAPP:")
    print("=" * 60)
    print(message)
    print("=" * 60 + "\n")

    if args.dry_run:
        print("✅ Modo --dry-run concluído com sucesso.")
        return 0

    print("📲 Enviando mensagem para o WhatsApp...")
    send_whatsapp_message(message)
    print("✅ Boletim enviado com sucesso para o seu WhatsApp!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
