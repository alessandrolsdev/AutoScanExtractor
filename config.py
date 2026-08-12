# -*- coding: utf-8 -*-
"""
config.py

Constantes globais, configuração de log e descoberta do Tesseract.

A descoberta do Tesseract segue uma ordem única para todos os ambientes
(executável empacotado, Windows, Linux/macOS e CI), em vez dos três caminhos
paralelos que existiam antes:

    1. variável de ambiente ``TESSERACT_CMD`` — sempre vence;
    2. dentro do pacote PyInstaller, quando rodando como ``.exe``;
    3. caminhos usuais de instalação no Windows;
    4. o ``PATH`` do sistema (Linux, macOS, CI).
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from typing import Optional

import pytesseract

logger = logging.getLogger(__name__)

# --- Constantes de extração -------------------------------------------------

DEFAULT_LANG = "por"

#: Confiança mínima (0-100) para uma palavra do OCR entrar na análise posicional.
OCR_CONF_THRESHOLD = 40

#: Distância máxima, em pixels, entre o rótulo "Valor" e o número candidato.
VALOR_MAX_DISTANCE = 700

#: Resolução de renderização das páginas de PDF para OCR.
DPI_RENDERIZACAO = 300

#: Fator de ampliação aplicado antes da binarização, para ajudar o OCR.
FATOR_AMPLIACAO_OCR = 2.0

#: Janela de anos aceita para uma data de vencimento vinda de regex/OCR.
ANO_MINIMO_PLAUSIVEL = 1998
ANO_MAXIMO_PLAUSIVEL = 2100

#: Páginas de PDF submetidas a OCR antes de desistir (boleto costuma estar na 1ª).
MAX_PAGINAS_OCR = 5

# --- Caminhos usuais do Tesseract no Windows --------------------------------

CAMINHOS_WINDOWS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Tesseract-OCR\tesseract.exe"),
)


class TesseractNaoEncontrado(RuntimeError):
    """O Tesseract não foi localizado em nenhum dos caminhos conhecidos."""


def resource_path(relative_path: str) -> str:
    """
    Caminho absoluto de um recurso, dentro ou fora do executável PyInstaller.

    O PyInstaller extrai os arquivos embutidos em ``sys._MEIPASS`` em tempo de
    execução; fora dele, os recursos ficam ao lado deste arquivo.
    """
    base_path = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def esta_empacotado() -> bool:
    """True quando rodando a partir do executável gerado pelo PyInstaller."""
    return getattr(sys, "frozen", False)


def ocultar_console_proprio() -> bool:
    """
    Esconde a janela de console quando o executável é aberto com dois cliques.

    O executável é compilado com console para que a linha de comando funcione
    (``AutoScanExtractor.exe extrair ...``). Quando ele é aberto sem argumentos
    para usar a interface gráfica, esse console fica sobrando.

    A janela só é escondida se o processo for o **único** dono do console — ou
    seja, se ele o criou ao ser aberto pelo Explorer. Rodando a partir de um
    ``cmd`` já existente, o console pertence ao usuário e é preservado.

    Devolve True se a janela foi escondida. Nunca levanta exceção: falhar aqui
    é apenas cosmético.
    """
    if os.name != "nt" or not esta_empacotado():
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        janela = kernel32.GetConsoleWindow()
        if not janela:
            return False

        # GetConsoleProcessList devolve quantos processos usam este console.
        buffer = (ctypes.c_uint * 4)()
        quantidade = kernel32.GetConsoleProcessList(buffer, 4)
        if quantidade != 1:
            return False  # herdamos o console de um terminal do usuário

        ctypes.windll.user32.ShowWindow(janela, 0)  # SW_HIDE
        return True
    except Exception:  # pragma: no cover - específico do Windows
        logger.debug("Não foi possível ocultar o console.", exc_info=True)
        return False


def configurar_logging(verboso: bool = False) -> None:
    """Configura o log da aplicação. Chame uma vez, no ponto de entrada."""
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stdout,
    )
    # O pdfminer/PIL são barulhentos em DEBUG e não interessam aqui.
    logging.getLogger("PIL").setLevel(logging.WARNING)


def _localizar_tesseract() -> Optional[str]:
    """Descobre o executável do Tesseract, na ordem de precedência documentada."""
    do_ambiente = os.environ.get("TESSERACT_CMD")
    if do_ambiente:
        if os.path.isfile(do_ambiente):
            return do_ambiente
        logger.warning("TESSERACT_CMD aponta para um arquivo inexistente: %s", do_ambiente)

    if esta_empacotado():
        embutido = resource_path("tesseract.exe" if os.name == "nt" else "tesseract")
        if os.path.isfile(embutido):
            return embutido

    if os.name == "nt":
        for caminho in CAMINHOS_WINDOWS:
            if caminho and os.path.isfile(caminho):
                return caminho

    return shutil.which("tesseract")


def _localizar_tessdata() -> Optional[str]:
    """Descobre a pasta ``tessdata``, quando ela não está no local padrão."""
    do_ambiente = os.environ.get("TESSDATA_PREFIX")
    if do_ambiente and os.path.isdir(do_ambiente):
        return do_ambiente

    if esta_empacotado():
        embutido = resource_path("tessdata")
        if os.path.isdir(embutido):
            return embutido

    if os.name == "nt":
        for caminho in CAMINHOS_WINDOWS:
            if not caminho:
                continue
            candidato = os.path.join(os.path.dirname(caminho), "tessdata")
            if os.path.isdir(candidato):
                return candidato
    return None


def setup_tesseract(exigir_idioma: bool = True) -> str:
    """
    Localiza e valida o Tesseract, devolvendo o caminho do executável.

    Levanta ``TesseractNaoEncontrado`` com uma mensagem acionável quando o
    binário não existe ou o idioma português não está instalado.
    """
    executavel = _localizar_tesseract()
    if not executavel:
        raise TesseractNaoEncontrado(
            "Tesseract OCR não encontrado.\n"
            "Instale o Tesseract e/ou defina a variável de ambiente TESSERACT_CMD "
            "apontando para o executável.\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  macOS:   brew install tesseract tesseract-lang\n"
            "  Linux:   sudo apt-get install tesseract-ocr tesseract-ocr-por"
        )

    pytesseract.pytesseract.tesseract_cmd = executavel

    tessdata = _localizar_tessdata()
    if tessdata:
        os.environ["TESSDATA_PREFIX"] = tessdata

    try:
        versao = pytesseract.get_tesseract_version()
        idiomas = pytesseract.get_languages(config="")
    except Exception as erro:  # binário existe mas não executa
        raise TesseractNaoEncontrado(
            f"Tesseract encontrado em '{executavel}', mas não foi possível executá-lo: {erro}"
        ) from erro

    logger.info("Tesseract %s em %s", versao, executavel)

    if DEFAULT_LANG not in idiomas:
        mensagem = (
            f"O idioma '{DEFAULT_LANG}' (português) não está instalado no Tesseract.\n"
            f"Idiomas disponíveis: {', '.join(idiomas) or 'nenhum'}\n"
            "  Windows: reinstale marcando 'Portuguese' em Additional language data\n"
            "  macOS:   brew install tesseract-lang\n"
            "  Linux:   sudo apt-get install tesseract-ocr-por"
        )
        if exigir_idioma:
            raise TesseractNaoEncontrado(mensagem)
        logger.warning(mensagem)

    return executavel
