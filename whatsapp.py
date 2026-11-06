from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Tuple


def _http_request(
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


def _detect_provider() -> str:
    """Detecta automaticamente o provedor caso WHATSAPP_PROVIDER não esteja fixado."""
    explicit = os.getenv("WHATSAPP_PROVIDER", "").strip().lower()
    if explicit in ("greenapi", "meta", "callmebot", "webhook"):
        return explicit

    if os.getenv("GREENAPI_ID_INSTANCE", "").strip() and os.getenv("GREENAPI_API_TOKEN", "").strip():
        return "greenapi"
    if os.getenv("META_TOKEN", "").strip() and os.getenv("META_PHONE_NUMBER_ID", "").strip():
        return "meta"
    if os.getenv("WEBHOOK_URL", "").strip():
        return "webhook"
    return "callmebot"


def send_whatsapp_message(message: str) -> bool:
    """
    Envia a mensagem para o WhatsApp usando o provedor configurado:
    - greenapi (100% gratuito no plano Developer, sem fila/lotação - Recomendado)
    - meta (WhatsApp Cloud API oficial da Meta)
    - callmebot (API gratuita via bot compartilhado)
    - webhook (Evolution API, Z-API ou endpoint customizado)
    """
    provider = _detect_provider()

    if provider == "greenapi":
        return _send_via_greenapi(message)
    if provider == "meta":
        return _send_via_meta(message)
    if provider == "callmebot":
        return _send_via_callmebot(message)
    if provider == "webhook":
        return _send_via_webhook(message)

    raise ValueError(
        f"Provedor WHATSAPP_PROVIDER='{provider}' inválido. Use 'greenapi', 'meta', 'callmebot' ou 'webhook'."
    )


def _resolve_greenapi_host(id_instance: str) -> str:
    custom = os.getenv("GREENAPI_HOST", "").strip().rstrip("/")
    if custom:
        return custom
    if len(id_instance) >= 4 and id_instance[:4].isdigit():
        return f"https://{id_instance[:4]}.api.greenapi.com"
    return "https://api.green-api.com"


def _resolve_brazil_chat_id(base_url: str, id_instance: str, api_token: str, phone: str) -> str:
    """
    Resolve o chatId correto no WhatsApp (tratando a regra do 9º dígito para DDDs brasileiros).
    Se o número destino for o próprio número conectado na instância, usa o 'wid' oficial da conta.
    """
    if "@" in phone:
        return phone

    clean_phone = "".join(ch for ch in phone if ch.isdigit())
    if not clean_phone.startswith("55") and len(clean_phone) in (10, 11):
        clean_phone = "55" + clean_phone

    # 1. Verifica o wid da própria conta conectada via getSettings
    try:
        settings_url = f"{base_url}/waInstance{id_instance}/getSettings/{api_token}"
        status, body = _http_request("GET", settings_url, timeout=10)
        if status == 200:
            wid = str(json.loads(body).get("wid", ""))
            wid_digits = wid.split("@")[0]
            if wid_digits and clean_phone[-8:] == wid_digits[-8:] and clean_phone[:4] == wid_digits[:4]:
                return wid
    except Exception:
        pass

    # 2. Para números do Brasil com 13 dígitos (55 + DDD + 9 + 8 dígitos), verifica no checkWhatsapp
    if clean_phone.startswith("55") and len(clean_phone) == 13 and clean_phone[4] == "9":
        without_nine = clean_phone[:4] + clean_phone[5:]
        try:
            check_url = f"{base_url}/waInstance{id_instance}/checkWhatsapp/{api_token}"
            status, body = _http_request("POST", check_url, payload={"phoneNumber": int(without_nine)}, timeout=10)
            if status == 200 and json.loads(body).get("existsWhatsapp") is True:
                return f"{without_nine}@c.us"
        except Exception:
            pass

    return f"{clean_phone}@c.us"


def _send_via_greenapi(message: str) -> bool:
    """Envia mensagem via Green-API (Plano Developer Gratuito)."""
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
            payload = {
                "chatId": chat_id,
                "message": message,
            }
            status, body = _http_request("POST", url, payload=payload, timeout=20)
            if status == 200:
                return True
            last_error = f"({status}) {body[:250]}"
        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError(f"Erro Green-API: {last_error}")


def _send_via_callmebot(message: str) -> bool:
    phone = os.getenv("CALLMEBOT_PHONE", "").strip()
    apikey = os.getenv("CALLMEBOT_APIKEY", "").strip()
    if not phone or not apikey or apikey == "1234567":
        raise RuntimeError(
            "Configure o provedor de WhatsApp (ex: GREENAPI_ID_INSTANCE + GREENAPI_API_TOKEN + GREENAPI_PHONE) "
            "no arquivo .env ou nos Secrets do GitHub."
        )

    encoded_text = urllib.parse.quote_plus(message)
    url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded_text}&apikey={apikey}"
    status, body = _http_request("GET", url, timeout=20)
    if status == 200:
        return True
    raise RuntimeError(f"Erro CallMeBot ({status}): {body[:200]}")


def _send_via_meta(message: str) -> bool:
    token = os.getenv("META_TOKEN", "").strip()
    phone_id = os.getenv("META_PHONE_NUMBER_ID", "").strip()
    recipient = os.getenv("META_RECIPIENT_PHONE", "").strip()
    if not token or not phone_id or not recipient:
        raise RuntimeError(
            "Configure META_TOKEN, META_PHONE_NUMBER_ID e META_RECIPIENT_PHONE."
        )

    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }
    status, body = _http_request("POST", url, payload=payload, headers=headers, timeout=20)
    if status in (200, 201):
        return True
    raise RuntimeError(f"Erro Meta API ({status}): {body[:200]}")


def _send_via_webhook(message: str) -> bool:
    url = os.getenv("WEBHOOK_URL", "").strip()
    api_key = os.getenv("WEBHOOK_API_KEY", "").strip()
    recipient = os.getenv("WEBHOOK_RECIPIENT_PHONE", "").strip()
    if not url:
        raise RuntimeError("Configure WEBHOOK_URL para envio via Evolution API / Z-API / Webhook.")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["apikey"] = api_key

    payload = {
        "number": recipient,
        "text": message,
        "message": message,
    }
    status, body = _http_request("POST", url, payload=payload, headers=headers, timeout=20)
    if 200 <= status < 300:
        return True
    raise RuntimeError(f"Erro Webhook ({status}): {body[:200]}")
