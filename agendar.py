"""
Inscrição automática na agenda CCKM (Krav Maga) — unidade São José, turma das 17:30.

Roda na segunda e na quarta. A lista abre às 17:30 (24h antes da aula), então o
script abre a página um pouco antes e fica conferindo até a turma aparecer.

Variáveis de ambiente opcionais:
  DRY_RUN=1      -> faz tudo, menos clicar em "Agendar" (para testar)
  FORCE=1        -> roda mesmo que amanhã não seja terça/quinta
  MAX_MINUTOS=45 -> quanto tempo esperar a turma aparecer
"""

import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

URL = "https://skyincloud.com/cckm/index_agenda.php"
LUGAR_SAO_JOSE = "2"
HORARIO = "17:30"

ALUNOS = [
    ("Miguel Sória", "2"),  # Laranja
    ("Paulo", "3"),         # Verde
]

DIAS = {1: "TER", 3: "QUI"}  # weekday() de amanhã -> prefixo no site

DRY_RUN = os.getenv("DRY_RUN") == "1"
FORCE = os.getenv("FORCE") == "1"
MAX_MINUTOS = int(os.getenv("MAX_MINUTOS", "45"))


def log(msg):
    agora = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M:%S")
    print(f"[{agora}] {msg}", flush=True)


def normaliza(txt):
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return " ".join(txt.lower().split())


def alvo():
    amanha = datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=1)
    dia = DIAS.get(amanha.weekday())
    if not dia:
        if not FORCE:
            log(f"Amanhã ({amanha:%d/%m}) não é terça nem quinta. Nada a fazer.")
            sys.exit(0)
        dia = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"][amanha.weekday()]
    return dia, amanha.strftime("%d/%m")


def abre_turma(page, dia, data):
    """Seleciona São José e a turma certa. Devolve o texto da turma ou None."""
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.select_option("#lugar", LUGAR_SAO_JOSE)
    page.wait_for_timeout(2500)
    opcoes = page.eval_on_selector_all(
        "#turma option", "els => els.map(o => [o.value, o.textContent.trim()])"
    )
    for valor, texto in opcoes:
        partes = [p.strip() for p in texto.split(" - ")]
        if len(partes) >= 3 and partes[0] == dia and partes[1] == data and partes[2] == HORARIO:
            page.select_option("#turma", valor)
            page.wait_for_selector("#nome", state="visible", timeout=20_000)
            page.wait_for_timeout(1500)
            return texto
    return None


def inscritos(page):
    celulas = page.eval_on_selector_all("td", "els => els.map(e => e.textContent)")
    return {normaliza(c) for c in celulas}


def total_texto(page):
    corpo = page.inner_text("body")
    for linha in corpo.splitlines():
        if "Total de Alunos" in linha:
            return " ".join(linha.split())
    return ""


def main():
    dia, data = alvo()
    log(f"Procurando turma {dia} - {data} - {HORARIO} em São José"
        + (" (DRY_RUN)" if DRY_RUN else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        limite = time.time() + MAX_MINUTOS * 60
        turma = None
        while time.time() < limite:
            try:
                turma = abre_turma(page, dia, data)
            except Exception as e:  # rede lenta, timeout etc.
                log(f"Erro ao abrir a página: {e}")
            if turma:
                break
            log("Turma ainda não apareceu. Tentando de novo em 20s...")
            time.sleep(20)

        if not turma:
            log("ERRO: a turma não apareceu dentro do tempo limite.")
            browser.close()
            sys.exit(1)

        log(f"Turma encontrada: {turma}")
        falhou = False

        for nome, graduacao in ALUNOS:
            if normaliza(nome) in inscritos(page):
                log(f"{nome} já está na lista. Pulando.")
                continue

            if "Máximo de Alunos" in total_texto(page):
                t = total_texto(page)
                try:
                    atual = int(t.split("Turma :")[1].split()[0])
                    maximo = int(t.split("Máximo de Alunos :")[1].split()[0])
                    if atual >= maximo:
                        log(f"ERRO: turma cheia ({t}). Não inscrevi {nome}.")
                        falhou = True
                        break
                except (IndexError, ValueError):
                    pass

            page.fill("#nome", nome)
            page.select_option("#graduacao", graduacao)
            if DRY_RUN:
                log(f"[DRY_RUN] Preenchido {nome} (graduação {graduacao}), sem enviar.")
                continue

            page.click("#Salvar")
            page.wait_for_timeout(3000)

            # Recarrega a turma para confirmar
            abre_turma(page, dia, data)
            if normaliza(nome) in inscritos(page):
                log(f"OK: {nome} inscrito.")
            else:
                log(f"ERRO: {nome} não apareceu na lista depois de agendar.")
                falhou = True
                break

        log(total_texto(page))
        browser.close()
        sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
