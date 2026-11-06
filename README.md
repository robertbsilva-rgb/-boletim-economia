# 📊 Boletim Econômico Diário no WhatsApp (com IA)

Automação em Python que coleta diariamente os principais **indicadores econômicos nacionais e internacionais**, gera um **resumo executivo de 2 a 3 linhas com IA (Google Gemini)** e envia direto para o seu **WhatsApp** todas as manhãs via **GitHub Actions** (100% gratuito e na nuvem).

---

## 📋 O que vem no Boletim?

1. **💡 Termômetro do Mercado (IA):** Resumo curto de 2-3 linhas explicando o humor do dia com base nos dados reais coletados.
2. **💱 Câmbio & Bolsas:**
   - Dólar Comercial (`USD/BRL`), Euro (`EUR/BRL`) e Índice `DXY` (força global do dólar)
   - `Ibovespa`, `S&P 500` e `Nasdaq`
3. **🏦 Juros & Inflação (BR / EUA):**
   - `Taxa Selic Meta` e `IPCA Acumulado (12m)` *(direto da API oficial SGS do Banco Central)*
   - `Juros do Fed (Fed Funds Rate)` *(via FRED)* e `Treasury de 10 Anos dos EUA (US 10Y Yield)`
4. **🛢️ Commodities & Cripto:**
   - `Petróleo Brent`, `Ouro` e `Bitcoin`
5. **📅 Agenda do Dia (Apenas Alto Impacto ⭐⭐⭐):**
   - Filtra apenas eventos críticos agendados para o dia (Payroll, CPI, FOMC/Fed, PIB, BCE e Boletim Focus às segundas-feiras).

---

## 🚀 Como ativar o envio gratuito para o seu WhatsApp (Sem fila / Sem bot lotado)

Como os números públicos do CallMeBot frequentemente lotam (`"This Bot is full"`), a melhor solução **100% gratuita, sem cartão de crédito e dedicada a você** é o plano **Developer da Green-API**:

1. Acesse [console.green-api.com](https://console.green-api.com/) e crie uma conta gratuita.
2. Clique em **Create an instance** e escolha o plano gratuito **Developer ($0/mês — gratuito para sempre para até 3 conversas)**.
3. Na tela da instância criada, clique para gerar o **QR Code** e escaneie pelo seu celular (**WhatsApp → Aparelhos Conectados → Conectar aparelho**).
4. Copie os dois dados exibidos no painel:
   - **`idInstance`** (ex: `7103123456`)
   - **`apiTokenInstance`** (ex: `a1b2c3d4e5...`)
5. Pronto! Você receberá as mensagens de você mesmo (na sua conversa pessoal do WhatsApp) ou em um grupo só seu.

> **Alternativas também suportadas automaticamente em [`src/whatsapp.py`](src/whatsapp.py):**
> - **API Oficial da Meta (WhatsApp Cloud API):** Gratuito usando o número de teste em [developers.facebook.com](https://developers.facebook.com/).
> - **CallMeBot:** Caso queira tentar os números secundários deles (`+34 623 78 64 49`, `+34 621 371 153` ou `+34 644 26 33 77`).

---

## 🔑 Chave Gratuita do Google Gemini (Resumo por IA)

1. Acesse o [Google AI Studio](https://aistudio.google.com/apikey) com sua conta Google.
2. Clique em **Create API Key** (100% gratuito).
3. Guarde a chave gerada para colocar no `.env` (teste local) ou nos **Secrets** do GitHub.

---

## 💻 Testando no seu Computador

1. Instale as dependências:
   ```powershell
   pip install -r requirements.txt
   ```
2. Faça um teste de prévia no terminal (sem enviar para o WhatsApp):
   ```powershell
   python main.py --dry-run
   ```
3. Para testar o envio real para o seu celular, copie [`.env.example`](.env.example) para `.env`, preencha `GREENAPI_ID_INSTANCE`, `GREENAPI_API_TOKEN` e `GREENAPI_PHONE`, e rode:
   ```powershell
   python main.py
   ```

---

## ☁️ Automatizando na Nuvem com GitHub Actions (100% Gratuito)

O arquivo [`.github/workflows/daily_economy.yml`](.github/workflows/daily_economy.yml) já está configurado para rodar **de segunda a sexta-feira às 08:00 (horário de Brasília)**.

1. Crie um repositório no seu GitHub e suba os arquivos deste projeto.
2. No seu repositório do GitHub, vá em **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
3. Adicione os seguintes segredos:
   - `GREENAPI_ID_INSTANCE`: O ID da sua instância gratuita na Green-API
   - `GREENAPI_API_TOKEN`: O Token da sua instância na Green-API
   - `GREENAPI_PHONE`: Seu número com DDI e DDD, apenas números (ex: `5511999999999`) — *Obs.: no Brasil, verifique se o seu WhatsApp usa ou não o 9º dígito (ex: DDDs fora de SP/RJ costumam não ter o 9 inicial no ID do WhatsApp)*
   - `GEMINI_API_KEY`: Sua chave gratuita do Google AI Studio
4. Para testar imediatamente na nuvem, clique na aba **Actions** do seu repositório → **Boletim Econômico Diário (WhatsApp)** → **Run workflow**.
