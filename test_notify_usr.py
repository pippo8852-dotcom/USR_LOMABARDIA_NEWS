"""Test per notify_usr.py: non fanno nessuna richiesta reale a internet o a Telegram,
   simulano (mock) le risposte per verificare che la logica dello script sia corretta."""
import importlib
import json
import os
import re
import unittest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-chat")
os.environ.setdefault("SCRAPERAPI_KEY", "test-key")

import notify_usr as nu


def pagina_di_prova(voci):
    """Costruisce un pezzo di HTML con lo stesso formato della pagina reale,
    a partire da una lista di tuple (giorno, mese, anno, link, titolo)."""
    blocchi = []
    for giorno, mese, anno, link, titolo in voci:
        blocchi.append(f'''
            <span class="article_data">
                {giorno} {mese} {anno}
            </span>
            <h3>
                <a href="{link}">
                    {titolo}
                </a>
            </h3>
        ''')
    return "<html><body>" + "".join(blocchi) + "</body></html>"


class TestParsing(unittest.TestCase):
    def test_estrae_una_comunicazione(self):
        html = pagina_di_prova([("6", "ottobre", "2026", "https://esempio/uno", "Prova Uno")])
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            voci = nu.leggi()
        self.assertEqual(len(voci), 1)
        link, titolo, data = voci[0]
        self.assertEqual(link, "https://esempio/uno")
        self.assertEqual(titolo, "Prova Uno")
        self.assertEqual(data, date(2026, 10, 6))

    def test_estrae_piu_comunicazioni_in_ordine(self):
        html = pagina_di_prova([
            ("7", "ottobre", "2026", "https://esempio/a", "Comunicazione A"),
            ("5", "ottobre", "2026", "https://esempio/b", "Comunicazione B"),
        ])
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            voci = nu.leggi()
        self.assertEqual(len(voci), 2)
        self.assertEqual(voci[0][0], "https://esempio/a")
        self.assertEqual(voci[1][0], "https://esempio/b")

    def test_giorno_con_una_sola_cifra(self):
        html = pagina_di_prova([("2", "settembre", "2026", "https://esempio/c", "Titolo")])
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            voci = nu.leggi()
        self.assertEqual(voci[0][2], date(2026, 9, 2))

    def test_mese_sconosciuto_viene_ignorato(self):
        html = pagina_di_prova([("6", "mesestrano", "2026", "https://esempio/d", "Titolo")])
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            voci = nu.leggi()
        self.assertEqual(voci, [])

    def test_titolo_con_spazi_e_a_capo_viene_pulito(self):
        html = pagina_di_prova([("6", "ottobre", "2026", "https://esempio/e",
                                  "  Titolo\n   con   spazi  ")])
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            voci = nu.leggi()
        self.assertEqual(voci[0][1], "Titolo con spazi")

    def test_nessuna_comunicazione_nella_pagina(self):
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text="<html>vuota</html>")
            mock_get.return_value.raise_for_status = lambda: None
            voci = nu.leggi()
        self.assertEqual(voci, [])

    def test_errore_http_si_propaga(self):
        with patch("notify_usr.requests.get") as mock_get:
            risposta = MagicMock(status_code=403)
            risposta.raise_for_status.side_effect = Exception("403 Forbidden")
            mock_get.return_value = risposta
            with self.assertRaises(Exception):
                nu.leggi()

    def test_la_richiesta_usa_scraperapi(self):
        html = pagina_di_prova([])
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            nu.leggi()
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], nu.SCRAPERAPI_ENDPOINT)
        self.assertEqual(kwargs["params"]["url"], nu.URL)
        self.assertIn("api_key", kwargs["params"])


class TestConfigurazione(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("USR_URL", None)
        importlib.reload(nu)   # ripristina i valori predefiniti per gli altri test

    def test_valori_predefiniti(self):
        os.environ.pop("USR_URL", None)
        importlib.reload(nu)
        self.assertEqual(nu.STATO.name, "stato_usr.json")        # stato separato da quello dell'UST
        self.assertIn("USR Lombardia", nu.NOME_FONTE)
        self.assertEqual(nu.URL, "https://www.mim.gov.it/web/usr-lombardia/comunicazioni")

    def test_l_indirizzo_si_puo_cambiare_con_una_variabile_d_ambiente(self):
        os.environ["USR_URL"] = "https://www.mim.gov.it/web/usr-lombardia/notizie"
        importlib.reload(nu)
        self.assertEqual(nu.URL, "https://www.mim.gov.it/web/usr-lombardia/notizie")

    def test_variabile_vuota_usa_l_indirizzo_predefinito(self):
        os.environ["USR_URL"] = ""
        importlib.reload(nu)
        self.assertEqual(nu.URL, "https://www.mim.gov.it/web/usr-lombardia/comunicazioni")


class TestInvio(unittest.TestCase):
    def test_invia_chiama_telegram_con_i_parametri_giusti(self):
        with patch("notify_usr.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            mock_post.return_value.raise_for_status = lambda: None
            nu.invia("messaggio di prova")
        url_chiamato = mock_post.call_args[0][0]
        dati = mock_post.call_args[1]["data"]
        self.assertIn(nu.TOKEN, url_chiamato)
        self.assertEqual(dati["chat_id"], nu.CHAT_ID)
        self.assertEqual(dati["text"], "messaggio di prova")
        self.assertEqual(dati["parse_mode"], "HTML")
        self.assertEqual(dati["disable_web_page_preview"], "true")


class TestMain(unittest.TestCase):
    def setUp(self):
        # ogni test lavora su un file stato.json temporaneo e isolato
        self._cwd_originale = os.getcwd()
        self._tmp = os.path.join(os.path.dirname(__file__), "_tmp_test_dir")
        os.makedirs(self._tmp, exist_ok=True)
        os.chdir(self._tmp)
        nu.STATO = __import__("pathlib").Path("stato.json")

    def tearDown(self):
        os.chdir(self._cwd_originale)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _finta_pagina_con_una_voce_recente(self):
        oggi = date.today()
        g, m, a = oggi.day, _mese_in_italiano(oggi.month), oggi.year
        return pagina_di_prova([(str(g), m, str(a), "https://esempio/recente", "Novità di oggi")])

    def test_primo_giro_non_invia_nulla_ma_salva_stato(self):
        html = self._finta_pagina_con_una_voce_recente()
        with patch("notify_usr.requests.get") as mock_get, \
             patch("notify_usr.requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            nu.main()
        mock_post.assert_not_called()
        self.assertTrue(nu.STATO.exists())
        stato = json.loads(nu.STATO.read_text())
        self.assertIn(nu.NOME_FONTE, stato)
        self.assertIn("https://esempio/recente", stato[nu.NOME_FONTE]["visti"])

    def test_secondo_giro_non_reinvia_comunicazioni_gia_viste(self):
        html = self._finta_pagina_con_una_voce_recente()
        with patch("notify_usr.requests.get") as mock_get, \
             patch("notify_usr.requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            nu.main()   # primo giro: salva, non invia
            nu.main()   # secondo giro: stessa pagina, deve restare in silenzio
        mock_post.assert_not_called()

    def test_comunicazione_nuova_dopo_il_primo_giro_viene_inviata(self):
        oggi = date.today()
        g, m, a = oggi.day, _mese_in_italiano(oggi.month), oggi.year
        pagina_iniziale = pagina_di_prova([(str(g), m, str(a), "https://esempio/vecchia", "Vecchia")])
        pagina_aggiornata = pagina_di_prova([
            (str(g), m, str(a), "https://esempio/vecchia", "Vecchia"),
            (str(g), m, str(a), "https://esempio/nuova", "Nuova"),
        ])
        with patch("notify_usr.requests.get") as mock_get, \
             patch("notify_usr.requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, text=pagina_iniziale)
            mock_get.return_value.raise_for_status = lambda: None
            nu.main()   # primo giro

            mock_get.return_value = MagicMock(status_code=200, text=pagina_aggiornata)
            mock_get.return_value.raise_for_status = lambda: None
            mock_post.return_value = MagicMock(status_code=200)
            mock_post.return_value.raise_for_status = lambda: None
            nu.main()   # secondo giro: una comunicazione è nuova

        mock_post.assert_called_once()
        testo_inviato = mock_post.call_args[1]["data"]["text"]
        self.assertIn("Nuova", testo_inviato)
        self.assertIn("🔗 Apri la comunicazione", testo_inviato)
        self.assertIn('<a href="https://esempio/nuova">', testo_inviato)
        self.assertNotIn("\nhttps://", testo_inviato)   # nessun indirizzo scritto per esteso
        # la descrizione (titolo) deve comparire prima del link, non dopo
        self.assertLess(testo_inviato.index("Nuova"), testo_inviato.index("https://esempio/nuova"))

    def test_comunicazione_vecchia_oltre_il_limite_viene_ignorata(self):
        vecchia = date.today() - timedelta(days=30)
        g, m, a = vecchia.day, _mese_in_italiano(vecchia.month), vecchia.year
        html = pagina_di_prova([(str(g), m, str(a), "https://esempio/molto-vecchia", "Vecchissima")])
        with patch("notify_usr.requests.get") as mock_get, \
             patch("notify_usr.requests.post") as mock_post:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            mock_get.return_value.raise_for_status = lambda: None
            nu.main()
            # anche cancellando lo stato e rifacendo girare, una comunicazione così vecchia
            # non deve mai essere inviata, perché supera GIORNI_MASSIMI
            nu.STATO.unlink()
            nu.main()
        mock_post.assert_not_called()

    def test_errore_di_lettura_non_blocca_il_salvataggio_dello_stato(self):
        with patch("notify_usr.requests.get") as mock_get:
            mock_get.side_effect = Exception("errore di rete simulato")
            nu.main()   # non deve sollevare eccezioni
        self.assertTrue(nu.STATO.exists())


def _mese_in_italiano(numero):
    inverso = {v: k for k, v in nu.MESI.items()}
    return inverso[numero]


class TestRateLimit(unittest.TestCase):
    def test_invia_riprova_dopo_errore_429(self):
        risposta_429 = MagicMock(status_code=429)
        risposta_429.json.return_value = {"parameters": {"retry_after": 0}}
        risposta_ok = MagicMock(status_code=200)
        risposta_ok.raise_for_status = lambda: None

        with patch("notify_usr.requests.post") as mock_post, \
             patch("notify_usr.time.sleep") as mock_sleep:
            mock_post.side_effect = [risposta_429, risposta_ok]
            nu.invia("messaggio di prova")

        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1)  # retry_after(0) + 1

    def test_invia_fallisce_dopo_troppi_429_consecutivi(self):
        risposta_429 = MagicMock(status_code=429)
        risposta_429.json.return_value = {"parameters": {"retry_after": 0}}
        risposta_429.raise_for_status.side_effect = Exception("429 Too Many Requests")

        with patch("notify_usr.requests.post") as mock_post, \
             patch("notify_usr.time.sleep"):
            mock_post.return_value = risposta_429
            with self.assertRaises(Exception):
                nu.invia("messaggio di prova", tentativi=3)

        self.assertEqual(mock_post.call_count, 3)


class TestFormattoMessaggio(unittest.TestCase):
    def test_struttura_del_messaggio(self):
        testo = nu.formatta_messaggio("Titolo di prova", date(2026, 10, 6),
                                       "https://esempio/link")
        righe = testo.split("\n")
        self.assertEqual(len(righe), 4)
        self.assertEqual(righe[0], nu.NOME_FONTE)
        self.assertEqual(righe[1], "Titolo di prova")
        self.assertEqual(righe[2], "📅 06/10/2026")
        self.assertEqual(righe[3], '<a href="https://esempio/link">🔗 Apri la comunicazione</a>')

    def test_la_scritta_e_il_link_e_l_indirizzo_non_e_visibile(self):
        testo = nu.formatta_messaggio("Titolo", date(2026, 10, 6), "https://esempio/link")
        # il testo visibile dell'ancora è solo la scritta, senza l'indirizzo
        self.assertEqual(re.findall(r">([^<]*)</a>", testo), ["🔗 Apri la comunicazione"])
        # e l'indirizzo compare solo dentro href, mai come riga a sé
        self.assertEqual(testo.count("https://esempio/link"), 1)
        self.assertNotIn("\nhttps://", testo)

    def test_caratteri_speciali_nel_titolo_sono_escapati(self):
        testo = nu.formatta_messaggio("Orari <classi> A&B", date(2026, 10, 6),
                                       "https://esempio/link")
        self.assertIn("Orari &lt;classi&gt; A&amp;B", testo)
        self.assertNotIn("<classi>", testo)

    def test_caratteri_speciali_nel_link_sono_escapati(self):
        testo = nu.formatta_messaggio("Titolo", date(2026, 10, 6),
                                       'https://esempio/p?a=1&b="2"')
        self.assertIn('href="https://esempio/p?a=1&amp;b=&quot;2&quot;"', testo)

    def test_il_titolo_viene_prima_del_link(self):
        testo = nu.formatta_messaggio("Titolo", date(2026, 10, 6), "https://esempio/link")
        self.assertLess(testo.index("Titolo"), testo.index("<a href="))

    def test_nessun_orario_nel_messaggio(self):
        # il sito pubblica solo la data, non l'ora: il messaggio non deve inventarla
        testo = nu.formatta_messaggio("Titolo", date(2026, 10, 6), "https://esempio/link")
        self.assertNotRegex(testo, r"\d{1,2}:\d{2}")


if __name__ == "__main__":
    unittest.main()
