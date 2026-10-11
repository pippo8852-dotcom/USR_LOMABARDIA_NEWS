"""Avvisi Telegram: solo comunicazioni USR Lombardia (MIM), lette tramite ScraperAPI
   per aggirare il blocco (403) che il sito applica ai server di GitHub Actions."""
import html
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]      # es. @nomecanale oppure -100123...
SCRAPERAPI_KEY = os.environ["SCRAPERAPI_KEY"]

STATO = Path("stato_usr.json")
NOME_FONTE = "📢 USR Lombardia - Comunicazioni"

# Pagina con l'elenco delle comunicazioni. Per usarne un'altra si cambia qui, oppure si imposta
# la variabile d'ambiente USR_URL nel workflow senza toccare il codice.
URL = os.environ.get("USR_URL") or "https://www.mim.gov.it/web/usr-lombardia/comunicazioni"
SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com"
GIORNI_MASSIMI = 7     # ignora comunicazioni più vecchie di così (serve solo al primo giro)

MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
        "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11,
        "dicembre": 12}

VOCE = re.compile(
    r'<span class="article_data">\s*(\d{1,2})\s+([^\s<]+)\s+(\d{4})\s*</span>'
    r'[\s\S]*?<h3>\s*<a href="([^"]+)"[^>]*>\s*([\s\S]*?)\s*</a>'
)


def oggi():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Rome")).date()
    except Exception:
        return date.today()


def leggi():
    resp = requests.get(
        SCRAPERAPI_ENDPOINT,
        params={"api_key": SCRAPERAPI_KEY, "url": URL},
        timeout=60,
    )
    print(f"📡 Status HTTP USR Lombardia (via ScraperAPI): {resp.status_code}")
    resp.raise_for_status()

    voci = []
    for giorno, mese, anno, link, titolo in VOCE.findall(resp.text):
        n_mese = MESI.get(mese.lower())
        if not n_mese:
            continue
        titolo = " ".join(html.unescape(titolo).split())
        data = date(int(anno), n_mese, int(giorno))
        voci.append((link, titolo, data))
    return voci


def formatta_messaggio(titolo, data, link):
    """Messaggio in HTML di Telegram: la scritta "Apri la comunicazione" è il link stesso,
    quindi l'indirizzo non compare per esteso. Titolo e link vanno "escapati", altrimenti
    caratteri come & o < farebbero rifiutare il messaggio da Telegram."""
    return (
        f"{html.escape(NOME_FONTE, quote=False)}\n"
        f"{html.escape(titolo, quote=False)}\n"
        f"📅 {data.strftime('%d/%m/%Y')}\n"
        f'<a href="{html.escape(link, quote=True)}">🔗 Apri la comunicazione</a>'
    )


def invia(testo, tentativi=5):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    dati = {"chat_id": CHAT_ID, "text": testo, "parse_mode": "HTML",
            "disable_web_page_preview": "true"}
    for tentativo in range(1, tentativi + 1):
        r = requests.post(url, data=dati, timeout=20)
        if r.status_code == 429:
            # Telegram chiede di rallentare: aspetta il tempo che indica lui stesso
            attesa = r.json().get("parameters", {}).get("retry_after", 5)
            print(f"⏳ Telegram: troppe richieste, aspetto {attesa}s (tentativo {tentativo}/{tentativi})")
            time.sleep(attesa + 1)
            continue
        r.raise_for_status()
        return
    r.raise_for_status()  # se dopo tutti i tentativi fallisce ancora, segnala l'errore


def main():
    stato = json.loads(STATO.read_text()) if STATO.exists() else {}
    adesso = oggi()

    try:
        voci = leggi()
    except Exception as e:
        print(f"[{NOME_FONTE}] errore: {e}")
        STATO.write_text(json.dumps(stato, ensure_ascii=False, indent=1))
        return
    if not voci:
        print(f"[{NOME_FONTE}] nessun elemento letto: controlla se il layout è cambiato")
        STATO.write_text(json.dumps(stato, ensure_ascii=False, indent=1))
        return

    visti = set(stato.get(NOME_FONTE, {}).get("visti", []))
    primo_giro = NOME_FONTE not in stato        # al primo giro non invia nulla
    nuove = [v for v in voci if v[0] not in visti]
    nuove = [v for v in nuove if (adesso - v[2]).days <= GIORNI_MASSIMI]

    if not primo_giro:
        for link, titolo, data in reversed(nuove):    # dalla più vecchia
            invia(formatta_messaggio(titolo, data, link))
            time.sleep(2)

    stato[NOME_FONTE] = {"visti": sorted(visti | {v[0] for v in voci})}
    print(f"[{NOME_FONTE}] letti {len(voci)}, inviati {0 if primo_giro else len(nuove)}")

    STATO.write_text(json.dumps(stato, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
