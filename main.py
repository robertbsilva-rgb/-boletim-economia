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
    hint: str = ""


@dataclass
class MacroIndicator:
    name: str
    value: str
    reference: str = ""
    hint: str = ""


@dataclass
class EconomicEvent:
    time_brt: str
    country: str
    title: str
    explanation: str = ""
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


def _fetch_yahoo_quote(symbol: str, name: str, unit: str = "", hint: str = "") -> Optional[QuoteItem]:
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
        return QuoteItem(name=name, symbol=symbol, price=last_close, change_pct=change_pct, unit=unit, hint=hint)
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

    dxy = _fetch_yahoo_quote(
        "DX-Y.NYB",
        "Índice DXY",
        "pts",
        hint="força do dólar no mundo",
    )
    if dxy:
        fx_list.append(dxy)

    indices_list: List[QuoteItem] = []
    for sym, label, unit, hint in [
        ("^BVSP", "Ibovespa (BR)", "pts", "principal índice da Bolsa brasileira"),
        ("^GSPC", "S&P 500 (EUA)", "pts", "500 maiores empresas dos EUA"),
        ("^IXIC", "Nasdaq (EUA)", "pts", "bolsa de tecnologia dos EUA"),
    ]:
        item = _fetch_yahoo_quote(sym, label, unit, hint=hint)
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


def _fetch_brasilapi_rates() -> Dict[str, float]:
    """Busca Selic, CDI e IPCA via BrasilAPI (funciona globalmente no GitHub Actions sem bloqueio)."""
    data = http_get_json("https://brasilapi.com.br/api/taxas/v1")
    result: Dict[str, float] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "nome" in item and "valor" in item:
                try:
                    result[str(item["nome"]).strip().upper()] = float(item["valor"])
                except Exception:
                    pass
    return result


def fetch_rates_and_inflation() -> List[MacroIndicator]:
    indicators: List[MacroIndicator] = []
    br_rates = _fetch_brasilapi_rates()

    # 1. Taxa Selic (Meta)
    selic = _fetch_bcb_sgs_latest(432)
    if selic:
        indicators.append(
            MacroIndicator(
                name="🇧🇷 Taxa Selic (Meta)",
                value=f"{selic[0]} a.a.",
                hint="juros básicos da economia brasileira",
            )
        )
    elif "SELIC" in br_rates:
        val_str = f"{br_rates['SELIC']:.2f}%".replace(".", ",")
        indicators.append(
            MacroIndicator(
                name="🇧🇷 Taxa Selic (Meta)",
                value=f"{val_str} a.a.",
                hint="juros básicos da economia brasileira",
            )
        )

    # 2. Taxa CDI / DI
    if "CDI" in br_rates:
        val_str = f"{br_rates['CDI']:.2f}%".replace(".", ",")
        indicators.append(
            MacroIndicator(
                name="🇧🇷 Taxa CDI (DI)",
                value=f"{val_str} a.a.",
                hint="rendimento base da renda fixa/bancos",
            )
        )
    else:
        cdi = _fetch_bcb_sgs_latest(4389)
        if cdi:
            indicators.append(
                MacroIndicator(
                    name="🇧🇷 Taxa CDI (DI)",
                    value=f"{cdi[0]} a.a.",
                    hint="rendimento base da renda fixa/bancos",
                )
            )

    # 3. IPCA Acumulado 12m
    ipca_12m = _fetch_bcb_sgs_latest(13522)
    if ipca_12m:
        indicators.append(
            MacroIndicator(
                name="🇧🇷 IPCA (Acum. 12m)",
                value=ipca_12m[0],
                reference=f"ref. {ipca_12m[1]}",
                hint="inflação oficial do Brasil",
            )
        )
    elif "IPCA" in br_rates:
        val_str = f"{br_rates['IPCA']:.2f}%".replace(".", ",")
        indicators.append(
            MacroIndicator(
                name="🇧🇷 IPCA (Acum. 12m)",
                value=f"{val_str} a.a.",
                hint="inflação oficial do Brasil",
            )
        )

    # 4. Juros Curto Prazo EUA (T-Bill 13 semanas ^IRX / Fed Funds)
    us_short = _fetch_yahoo_quote("^IRX", "Juros Curto Prazo EUA", "%")
    if us_short:
        preco_fmt = f"{us_short.price:.2f}".replace(".", ",")
        indicators.append(
            MacroIndicator(
                name="🇺🇸 Juros EUA (Fed / Curto Prazo)",
                value=f"{preco_fmt}% a.a.",
                hint="referência da taxa básica americana",
            )
        )

    # 5. Treasury 10 Anos EUA (^TNX)
    us10y = _fetch_yahoo_quote("^TNX", "Treasury 10 Anos (EUA)", "%")
    if us10y:
        sign = "+" if us10y.change_pct >= 0 else ""
        val_str = f"{us10y.price:.2f}% ({sign}{us10y.change_pct:.2f}%)".replace(".", ",")
        indicators.append(
            MacroIndicator(
                name="🇺🇸 Treasury 10Y (EUA)",
                value=val_str,
                hint="juros dos títulos de 10 anos dos EUA; quando sobe, atrai dólar para lá",
            )
        )

    return indicators


def fetch_commodities_and_crypto() -> List[QuoteItem]:
    results: List[QuoteItem] = []
    for sym, label, unit, hint in [
        ("BZ=F", "Petróleo Brent", "US$", "referência internacional do barril"),
        ("GC=F", "Ouro", "US$", "ativo de proteção global"),
        ("BTC-USD", "Bitcoin", "US$", "termômetro de liquidez em cripto"),
    ]:
        item = _fetch_yahoo_quote(sym, label, unit, hint=hint)
        if item:
            results.append(item)
    return results


# Dicionário com (Nome Técnico + Tradução Simples, Explicação prática do impacto)
_EVENT_DETAILS: Dict[str, tuple[str, str]] = {
    "Non-Farm Employment Change": (
        "Payroll — Criação de Empregos",
        "vagas criadas no mês; se vier muito acima da expectativa, fortalece o dólar",
    ),
    "Unemployment Rate": (
        "Unemployment Rate — Taxa de Desemprego",
        "% de desempregados nos EUA; desemprego muito baixo mantém juros altos lá fora",
    ),
    "Average Hourly Earnings m/m": (
        "Average Hourly Earnings (m/m) — Salário Médio por Hora",
        "variação mensal dos salários; alta forte indica pressão de inflação nos EUA",
    ),
    "CPI m/m": (
        "CPI (m/m) — Inflação ao Consumidor no Mês",
        "inflação mensal nos EUA; se vier alta, pressiona o dólar para cima",
    ),
    "CPI y/y": (
        "CPI (a/a) — Inflação ao Consumidor em 12 Meses",
        "inflação acumulada em 1 ano nos EUA; principal termômetro para os juros do Fed",
    ),
    "Core CPI m/m": (
        "Core CPI (m/m) — Núcleo da Inflação Mensal",
        "inflação sem alimentos e energia; mostra a tendência real dos preços nos EUA",
    ),
    "Core PCE Price Index m/m": (
        "Core PCE (m/m) — Inflação Favorita do Fed",
        "índice de preços mais acompanhado pelo Banco Central dos EUA para decidir juros",
    ),
    "Core CPI y/y": (
        "Core CPI (a/a) — Núcleo da Inflação em 12 Meses",
        "inflação sem alimentos e energia acumulada em 1 ano; tendência de fundo dos preços nos EUA",
    ),
    "Federal Funds Rate": (
        "Fed Funds Rate — Decisão de Juros do Fed (FOMC)",
        "define a taxa básica de juros dos EUA; impacta todas as moedas e bolsas do mundo",
    ),
    "FOMC Statement": (
        "FOMC Statement — Comunicado Oficial do Fed",
        "texto que indica se os juros nos EUA vão subir, cair ou ficar parados",
    ),
    "FOMC Press Conference": (
        "FOMC Press Conference — Coletiva do Presidente do Fed",
        "discurso ao vivo que costuma gerar forte oscilação no dólar e nas bolsas",
    ),
    "FOMC Meeting Minutes": (
        "FOMC Minutes — Ata da Reunião do Fed",
        "detalha os bastidores da última decisão de juros dos EUA",
    ),
    "Advance GDP q/q": (
        "Advance GDP (t/t) — Prévia do PIB dos EUA",
        "crescimento trimestral da economia americana",
    ),
    "Prelim GDP q/q": (
        "Prelim GDP (t/t) — PIB Preliminar dos EUA",
        "revisão do crescimento trimestral da economia americana",
    ),
    "Final GDP q/q": (
        "Final GDP (t/t) — PIB Final dos EUA",
        "dado consolidado do crescimento da economia americana no trimestre",
    ),
    "Retail Sales m/m": (
        "Retail Sales (m/m) — Vendas no Varejo",
        "mede a força do consumo das famílias no mês",
    ),
    "ISM Manufacturing PMI": (
        "ISM Manufacturing PMI — Índice de Atividade Industrial",
        "acima de 50 pontos indica expansão da indústria; abaixo de 50 indica retração",
    ),
    "ISM Services PMI": (
        "ISM Services PMI — Índice do Setor de Serviços",
        "mede o ritmo do maior setor da economia americana (acima de 50 = expansão)",
    ),
    "Unemployment Claims": (
        "Unemployment Claims — Pedidos de Auxílio-Desemprego",
        "termômetro semanal de demissões nos EUA",
    ),
    "JOLTS Job Openings": (
        "JOLTS — Vagas de Trabalho Abertas",
        "mede a demanda das empresas por trabalhadores nos EUA",
    ),
    "PPI m/m": (
        "PPI (m/m) — Inflação ao Produtor no Atacado",
        "mede o custo nas fábricas antes de chegar ao consumidor final",
    ),
    "Main Refinancing Rate": (
        "Taxa de Juros do BCE (Banco Central Europeu)",
        "decisão oficial de juros na Zona do Euro",
    ),
}

_COUNTRY_FLAGS: Dict[str, str] = {
    "USD": "🇺🇸 EUA",
    "EUR": "🇪🇺 Zona do Euro",
    "CNY": "🇨🇳 China",
    "GBP": "🇬🇧 Reino Unido",
    "JPY": "🇯🇵 Japão",
    "BRL": "🇧🇷 Brasil",
}


def _humanize_forecast(val: str) -> str:
    """Mantém o valor técnico e traduz abreviações como K (mil) para ficar claro."""
    v = val.strip()
    if not v:
        return ""
    if v.upper().endswith("K"):
        num = v[:-1].replace(".", ",")
        return f"{v} = {num} mil"
    return v.replace(".", ",")


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
                title_pt, explanation = _EVENT_DETAILS.get(
                    raw_title,
                    (raw_title, "indicador macroeconômico de alto impacto nas moedas e bolsas"),
                )
                events.append(
                    EconomicEvent(
                        time_brt=ev_dt.strftime("%H:%M"),
                        country=_COUNTRY_FLAGS.get(country_code, country_code),
                        title=title_pt,
                        explanation=explanation,
                        forecast=_humanize_forecast(str(ev.get("forecast", "") or "")),
                        previous=_humanize_forecast(str(ev.get("previous", "") or "")),
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
                title="Boletim Focus (Banco Central)",
                explanation="pesquisa semanal com as previsões do mercado para Selic, IPCA, PIB e Dólar",
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
        nomes = ", ".join(e.title.split("—")[0].strip() for e in report.high_impact_events[:2])
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
            "(máximo 320 caracteres) em português claro, didático e direto explicando o humor do mercado "
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
    hint_str = f" — _{q.hint}_" if q.hint else ""
    return f"{icon} *{q.name}:* {price_str} ({pct_str}){hint_str}"


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
        ref = f" ({m.reference})" if m.reference else ""
        hint_str = f" — _{m.hint}_" if m.hint else ""
        lines.append(f"• *{m.name}:* {m.value}{ref}{hint_str}")

    lines.append("")
    lines.append("🛢️ *Commodities & Cripto*")
    for q in report.commodities_crypto:
        lines.append(_format_quote_line(q))

    lines.append("")
    lines.append("📅 *Agenda do Dia (Eventos que Mexem no Mercado)*")
    if report.high_impact_events:
        for ev in report.high_impact_events:
            proj = f" | *Projeção:* {ev.forecast}" if ev.forecast else ""
            ant = f" | *Anterior:* {ev.previous}" if ev.previous else ""
            lines.append(f"⏰ *{ev.time_brt}* | {ev.country}: *{ev.title}*{proj}{ant}")
            if ev.explanation:
                lines.append(f"   ↳ _O que é: {ev.explanation}._")
    else:
        lines.append("• Sem divulgações críticas previstas para hoje (mercado segue fluxo técnico e notícias).")
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


# =====================================================================
# RADAR DA AGENDA — envia mensagem curta quando sai o resultado de um evento
# =====================================================================

RADAR_STATE_FILE = pathlib.Path(__file__).resolve().parent / "radar_state.json"

# Evento da agenda -> (série oficial do BLS, tipo de cálculo, defasagem em meses, "alta = dólar forte?")
_BLS_SERIES: Dict[str, Tuple[str, str, int, bool]] = {
    "Non-Farm Employment Change": ("CES0000000001", "diff_k", 1, True),
    "Unemployment Rate": ("LNS14000000", "level_pct", 1, False),
    "Average Hourly Earnings m/m": ("CES0500000003", "mom", 1, True),
    "CPI m/m": ("CUSR0000SA0", "mom", 1, True),
    "CPI y/y": ("CUUR0000SA0", "yoy", 1, True),
    "Core CPI m/m": ("CUSR0000SA0L1E", "mom", 1, True),
    "Core CPI y/y": ("CUUR0000SA0L1E", "yoy", 1, True),
    "PPI m/m": ("WPSFD4", "mom", 1, True),
    "JOLTS Job Openings": ("JTS000000000000000JOL", "level_m", 2, True),
}

FOCUS_TITLE = "__FOCUS__"


@dataclass
class RadarEvent:
    key: str
    raw_title: str
    when: dt.datetime
    country_code: str
    forecast: str
    previous: str


def _load_radar_state() -> Dict[str, str]:
    try:
        return json.loads(RADAR_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_radar_state(state: Dict[str, str], now: dt.datetime) -> None:
    limit = (now - dt.timedelta(days=10)).date().isoformat()
    pruned = {k: v for k, v in state.items() if v >= limit}
    RADAR_STATE_FILE.write_text(json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_today_radar_events(now: dt.datetime) -> List[RadarEvent]:
    today = now.date()
    events: List[RadarEvent] = []
    raw_events = http_get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    if isinstance(raw_events, list):
        for ev in raw_events:
            try:
                if ev.get("impact") != "High":
                    continue
                country_code = ev.get("country", "")
                if country_code not in ("USD", "EUR", "CNY", "BRL"):
                    continue
                when = dt.datetime.fromisoformat(ev["date"]).astimezone(BRT)
                if when.date() != today:
                    continue
                title = str(ev.get("title", "")).strip()
                events.append(
                    RadarEvent(
                        key=f"{when.isoformat()}|{title}",
                        raw_title=title,
                        when=when,
                        country_code=country_code,
                        forecast=str(ev.get("forecast", "") or ""),
                        previous=str(ev.get("previous", "") or ""),
                    )
                )
            except Exception:
                continue

    if today.weekday() == 0:
        when = dt.datetime.combine(today, dt.time(8, 25), tzinfo=BRT)
        events.append(RadarEvent(f"{when.isoformat()}|{FOCUS_TITLE}", FOCUS_TITLE, when, "BRL", "", ""))
    return events


def _fetch_bls_series(series_ids: List[str], now: dt.datetime) -> Dict[str, List[Tuple[int, int, float]]]:
    """Retorna {serie: [(ano, mes, valor), ...]} do mais recente para o mais antigo."""
    payload: Dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": str(now.year - 2),
        "endyear": str(now.year),
    }
    key = os.getenv("BLS_API_KEY", "").strip()
    if key:
        payload["registrationkey"] = key
    status, body = http_request("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", payload=payload, timeout=25)
    result: Dict[str, List[Tuple[int, int, float]]] = {}
    if status != 200:
        print(f"⚠️ BLS indisponível ({status})")
        return result
    try:
        for serie in json.loads(body)["Results"]["series"]:
            rows: List[Tuple[int, int, float]] = []
            for d in serie.get("data", []):
                period = str(d.get("period", ""))
                if not period.startswith("M") or period == "M13":
                    continue
                try:
                    rows.append((int(d["year"]), int(period[1:]), float(d["value"])))
                except ValueError:
                    continue
            rows.sort(reverse=True)
            result[serie["seriesID"]] = rows
    except Exception as exc:
        print(f"⚠️ Erro ao ler BLS: {exc}")
    return result


def _parse_number(val: str) -> Optional[float]:
    v = val.strip().replace("%", "").replace("K", "").replace("M", "").replace("B", "")
    try:
        return float(v)
    except ValueError:
        return None


def _compute_bls_actual(kind: str, rows: List[Tuple[int, int, float]]) -> Optional[Tuple[float, str]]:
    if len(rows) < 2:
        return None
    y0, m0, v0 = rows[0]
    if kind == "diff_k":
        x = round(v0 - rows[1][2])
        return x, f"{x:.0f}K"
    if kind == "level_pct":
        return round(v0, 1), f"{v0:.1f}%"
    if kind == "mom":
        x = round((v0 / rows[1][2] - 1) * 100, 1)
        return x, f"{x:.1f}%"
    if kind == "yoy":
        prev = next((v for (y, m, v) in rows if y == y0 - 1 and m == m0), None)
        if prev is None:
            return None
        x = round((v0 / prev - 1) * 100, 1)
        return x, f"{x:.1f}%"
    if kind == "level_m":
        x = round(v0 / 1000, 2)
        return x, f"{x:.2f}M"
    return None


def _expected_ref(when: dt.datetime, lag: int) -> Tuple[int, int]:
    idx = when.year * 12 + (when.month - 1) - lag
    return idx // 12, idx % 12 + 1


def _interpretation(actual: float, forecast: Optional[float], higher_is_strong_usd: bool) -> str:
    if forecast is None:
        return ""
    if abs(actual - forecast) < 1e-9:
        return "⚖️ Veio *EM LINHA* com a projeção → impacto tende a ser neutro."
    above = actual > forecast
    if above == higher_is_strong_usd:
        tag = "ACIMA" if above else "ABAIXO"
        return f"📈 Veio *{tag}* da projeção → tende a *fortalecer o dólar* e pressionar juros (ruim para bolsas)."
    tag = "ACIMA" if above else "ABAIXO"
    return f"📉 Veio *{tag}* da projeção → tende a *enfraquecer o dólar* e aliviar juros (bom para bolsas)."


def _fmt_pct_br(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _build_focus_block(now: dt.datetime) -> Optional[str]:
    """Busca o Boletim Focus na API Olinda do Banco Central e compara com a semana anterior."""
    years = [now.year, now.year + 1]
    filt = (
        "(Indicador eq 'IPCA' or Indicador eq 'PIB Total' or Indicador eq 'Selic' or Indicador eq 'Câmbio')"
        f" and baseCalculo eq 0 and (DataReferencia eq '{years[0]}' or DataReferencia eq '{years[1]}')"
    )
    query = urllib.parse.urlencode(
        {
            "$top": "200",
            "$filter": filt,
            "$orderby": "Data desc",
            "$format": "json",
            "$select": "Indicador,Data,DataReferencia,Mediana",
        },
        quote_via=urllib.parse.quote,
    )
    data = http_get_json(
        f"https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais?{query}",
        timeout=25,
    )
    if not isinstance(data, dict) or not data.get("value"):
        return None

    series: Dict[Tuple[str, str], List[Tuple[dt.date, float]]] = {}
    for row in data["value"]:
        try:
            k = (row["Indicador"], str(row["DataReferencia"]))
            series.setdefault(k, []).append((dt.date.fromisoformat(row["Data"]), float(row["Mediana"])))
        except Exception:
            continue

    latest_date = max((d for rows in series.values() for d, _ in rows), default=None)
    if latest_date is None or (now.date() - latest_date).days > 4:
        return None  # Focus desta semana ainda não publicado

    labels = [
        ("IPCA", "IPCA (inflação)", "%"),
        ("Selic", "Selic (fim do ano)", "%"),
        ("PIB Total", "PIB (crescimento)", "%"),
        ("Câmbio", "Dólar (fim do ano)", "R$"),
    ]
    lines = [f"*Boletim Focus — Previsões do mercado* _(dados de {latest_date.strftime('%d/%m')})_"]
    for ind, label, unit in labels:
        parts = []
        for y in years:
            rows = sorted(series.get((ind, str(y)), []), reverse=True)
            if not rows:
                continue
            d0, v0 = rows[0]
            week_ago = next((v for d, v in rows if (d0 - d).days >= 7), None)
            arrow = ""
            if week_ago is not None:
                arrow = " 🔺" if v0 > week_ago + 1e-9 else (" 🔻" if v0 < week_ago - 1e-9 else " =")
            val = f"R$ {_fmt_pct_br(v0)}" if unit == "R$" else f"{_fmt_pct_br(v0)}%"
            parts.append(f"{y}: {val}{arrow}")
        if parts:
            lines.append(f"• *{label}:* " + " | ".join(parts))
    lines.append("_🔺 subiu / 🔻 caiu / = estável em relação à semana anterior_")
    lines.append(
        "   ↳ _O que é: pesquisa semanal do Banco Central com economistas; "
        "previsões de inflação subindo costumam indicar juros altos por mais tempo._"
    )
    return "\n".join(lines)


def run_radar(now: dt.datetime, dry_run: bool) -> int:
    state = _load_radar_state()
    events = _fetch_today_radar_events(now)
    due = [
        e for e in events
        if e.key not in state
        and now >= e.when + dt.timedelta(minutes=5)
        and now - e.when <= dt.timedelta(hours=4)
    ]
    if not due:
        print("📡 Radar: nenhum evento novo para avisar agora.")
        _save_radar_state(state, now)
        return 0

    needed = sorted({_BLS_SERIES[e.raw_title][0] for e in due if e.raw_title in _BLS_SERIES})
    bls = _fetch_bls_series(needed, now) if needed else {}

    blocks: Dict[str, List[str]] = {}
    sent_keys: List[str] = []
    for e in sorted(due, key=lambda x: x.when):
        header = f"{e.when.strftime('%H:%M')} | {_COUNTRY_FLAGS.get(e.country_code, e.country_code)}"
        late = now - e.when > dt.timedelta(hours=2)

        if e.raw_title == FOCUS_TITLE:
            block = _build_focus_block(now)
            if block is None and not late:
                continue  # tenta de novo na próxima rodada
            blocks.setdefault(header, []).append(
                block or "*Boletim Focus* — publicado hoje, mas a API do Banco Central ainda não atualizou."
            )
            sent_keys.append(e.key)
            continue

        title_pt, explanation = _EVENT_DETAILS.get(
            e.raw_title, (e.raw_title, "indicador macroeconômico de alto impacto nas moedas e bolsas")
        )
        proj = f"🎯 *Projeção:* {_humanize_forecast(e.forecast)}" if e.forecast else ""
        ant = f"*Anterior:* {_humanize_forecast(e.previous)}" if e.previous else ""
        proj_line = " | ".join(p for p in (proj, ant) if p)

        actual_line = ""
        interp = ""
        if e.raw_title in _BLS_SERIES:
            sid, kind, lag, strong_usd = _BLS_SERIES[e.raw_title]
            rows = bls.get(sid, [])
            ready = bool(rows) and (rows[0][0], rows[0][1]) >= _expected_ref(e.when, lag)
            if ready:
                res = _compute_bls_actual(kind, rows)
                if res:
                    actual_val, actual_txt = res
                    ref = f"{rows[0][1]:02d}/{rows[0][0]}"
                    actual_line = f"✅ *Resultado:* {_humanize_forecast(actual_txt)} _(ref. {ref}, fonte: BLS)_"
                    interp = _interpretation(actual_val, _parse_number(e.forecast), strong_usd)
            if not actual_line and not late:
                continue  # fonte oficial ainda não atualizou; tenta na próxima rodada

        if not actual_line:
            actual_line = "⏱️ *Divulgado agora* — confira o resultado em relação à projeção abaixo."

        lines = [f"*{title_pt}*", actual_line]
        if proj_line:
            lines.append(proj_line)
        if interp:
            lines.append(interp)
        lines.append(f"   ↳ _O que é: {explanation}._")
        blocks.setdefault(header, []).append("\n".join(lines))
        sent_keys.append(e.key)

    if not blocks:
        print("📡 Radar: eventos aguardando atualização da fonte oficial; nova tentativa na próxima rodada.")
        _save_radar_state(state, now)
        return 0

    for header, items in blocks.items():
        message = f"🔔 *RADAR DA AGENDA* — {header}\n\n" + "\n\n".join(items)
        print("\n" + "=" * 60 + "\n" + message + "\n" + "=" * 60)
        if not dry_run:
            send_whatsapp_message(message)

    if dry_run:
        print("✅ Radar --dry-run concluído (nada enviado, memória não alterada).")
        return 0

    for k in sent_keys:
        state[k] = now.date().isoformat()
    _save_radar_state(state, now)
    print(f"✅ Radar: {len(blocks)} alerta(s) enviado(s) para o WhatsApp.")
    return 0


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
    parser.add_argument(
        "--radar",
        action="store_true",
        help="Modo Radar: envia alerta curto apenas quando sair o resultado de um evento da agenda.",
    )
    args = parser.parse_args()

    if args.radar:
        return run_radar(dt.datetime.now(BRT), args.dry_run)

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
