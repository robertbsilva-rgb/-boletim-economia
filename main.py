from __future__ import annotations

import argparse
import os
import pathlib
import sys

from src.collectors import collect_daily_report
from src.ai_summary import generate_market_summary
from src.formatter import format_whatsapp_message
from src.whatsapp import send_whatsapp_message


def _load_env_file() -> None:
    """Carrega variáveis do arquivo .env sem depender de bibliotecas externas."""
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
    # Garante saída UTF-8 no terminal do Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _load_env_file()

    parser = argparse.ArgumentParser(
        description="Gera e envia o Boletim Econômico Diário para o WhatsApp."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas coleta os dados, gera o resumo e exibe a mensagem no terminal (sem enviar ao WhatsApp).",
    )
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
        print("✅ Modo --dry-run concluído com sucesso (envio ao WhatsApp ignorado).")
        return 0

    print("📲 Enviando mensagem para o WhatsApp...")
    send_whatsapp_message(message)
    print("✅ Boletim enviado com sucesso para o seu WhatsApp!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
