# -*- coding: utf-8 -*-
"""
file_processor.py

Leitura de arquivos (PDF e imagem) e orquestração das camadas de extração.

Responsabilidades:

    1. abrir o arquivo e renderizar as páginas;
    2. pré-processar a imagem para o OCR;
    3. rodar o Tesseract **uma vez** por página, derivando dali tanto o texto
       corrido quanto as palavras posicionadas;
    4. combinar os resultados do texto digital e do OCR, sem descartar nenhum.

Um PDF com camada de texto é lido diretamente, sem OCR. Se o texto digital não
completar os campos principais, o OCR entra como complemento — e os dois
resultados são mesclados por precedência de origem, em vez de um sobrescrever
o outro.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import cv2
import fitz  # PyMuPDF
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from boleto_data import BoletoData, Origem
from config import (
    DEFAULT_LANG,
    DPI_RENDERIZACAO,
    FATOR_AMPLIACAO_OCR,
    MAX_PAGINAS_OCR,
)
from extraction_logic import (
    BoletoParser,
    ExtractionError,
    LayoutNaoReconhecidoError,
    OCRError,
    Palavra,
    palavras_do_dataframe,
    palavras_do_pdf,
    texto_do_dataframe,
)

logger = logging.getLogger(__name__)

EXTENSOES_IMAGEM = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif")
EXTENSOES_PDF = (".pdf",)
EXTENSOES_SUPORTADAS = EXTENSOES_IMAGEM + EXTENSOES_PDF

#: Abaixo disso, a camada de texto do PDF é considerada inexistente (escaneado).
MINIMO_TEXTO_DIGITAL = 50


@dataclass
class PaginaProcessada:
    """Uma página renderizada, com as palavras que o sistema enxergou nela."""

    numero: int
    imagem: Image.Image
    palavras: List[Palavra] = field(default_factory=list)


@dataclass
class ResultadoProcessamento:
    """Dados extraídos e, opcionalmente, o material para inspeção visual."""

    dados: BoletoData
    paginas: List[PaginaProcessada] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pré-processamento
# --------------------------------------------------------------------------- #

def preprocessar_imagem_para_ocr(pil_image: Image.Image) -> tuple:
    """
    Prepara a imagem para o OCR e devolve ``(imagem, escala)``.

    A ampliação acontece **antes** da binarização: ampliar uma imagem já
    binarizada apenas engorda os pixels, enquanto interpolar em tons de cinza
    e só então limiarizar preserva a forma das letras pequenas — que é
    exatamente onde o Tesseract erra em boleto escaneado.

    ``escala`` é a razão entre a imagem devolvida e a original, usada para
    converter as coordenadas do OCR de volta ao espaço da imagem exibida.
    """
    arranjo = np.array(pil_image)

    if arranjo.ndim == 2:
        cinza = arranjo
    elif arranjo.shape[2] == 4:
        cinza = cv2.cvtColor(arranjo, cv2.COLOR_RGBA2GRAY)
    else:
        cinza = cv2.cvtColor(arranjo, cv2.COLOR_RGB2GRAY)

    escala = FATOR_AMPLIACAO_OCR
    if escala != 1.0:
        largura = int(cinza.shape[1] * escala)
        altura = int(cinza.shape[0] * escala)
        cinza = cv2.resize(cinza, (largura, altura), interpolation=cv2.INTER_CUBIC)

    _, binarizada = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return Image.fromarray(binarizada), escala


def _ocr_da_imagem(imagem: Image.Image, pagina: int, escala: float) -> tuple:
    """
    Roda o Tesseract uma única vez e devolve ``(texto, palavras)``.

    ``image_to_data`` já contém tudo que ``image_to_string`` devolveria; rodar
    os dois sobre a mesma imagem dobrava o tempo de OCR sem ganho algum.
    """
    try:
        dataframe = pytesseract.image_to_data(imagem, lang=DEFAULT_LANG, output_type=Output.DATAFRAME)
    except pytesseract.TesseractError as erro:
        raise OCRError(f"Falha do Tesseract: {erro}") from erro

    texto = texto_do_dataframe(dataframe)
    palavras = palavras_do_dataframe(dataframe, pagina=pagina, escala=escala)
    return texto, palavras


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

def _renderizar_pagina(pagina: "fitz.Page") -> Image.Image:
    """Renderiza uma página de PDF como imagem RGB."""
    pixmap = pagina.get_pixmap(dpi=DPI_RENDERIZACAO)
    modo = "RGBA" if pixmap.alpha else "RGB"
    imagem = Image.frombytes(modo, [pixmap.width, pixmap.height], pixmap.samples)
    return imagem.convert("RGB") if imagem.mode != "RGB" else imagem


def processar_pdf(
    caminho_pdf: str,
    parser: BoletoParser,
    coletar_paginas: bool = False,
) -> ResultadoProcessamento:
    """
    Processa um PDF, combinando camada de texto digital e OCR.

    Levanta ``ExtractionError`` (ou subclasse) quando nada pôde ser lido.
    """
    nome_arquivo = os.path.basename(caminho_pdf)
    dados = BoletoData(arquivo_origem=nome_arquivo)
    paginas_processadas: List[PaginaProcessada] = []

    try:
        with fitz.open(caminho_pdf) as documento:
            dados.paginas = len(documento)
            if len(documento) == 0:
                raise LayoutNaoReconhecidoError(f"{nome_arquivo}: PDF sem páginas.")

            escala_pdf = DPI_RENDERIZACAO / 72.0

            # --- Camada digital: texto embutido no PDF, sem OCR ---
            texto_digital = "".join(pagina.get_text("text") for pagina in documento)
            tem_texto_digital = len(texto_digital.strip()) > MINIMO_TEXTO_DIGITAL

            if tem_texto_digital:
                logger.info("%s: usando a camada de texto digital.", nome_arquivo)
                parser.extrair_de_texto(texto_digital, dados, origem=Origem.PDF_DIGITAL)

                if coletar_paginas or not dados.esta_completo():
                    for indice, pagina in enumerate(documento):
                        if indice >= MAX_PAGINAS_OCR:
                            break
                        palavras = palavras_do_pdf(pagina.get_text("words"), escala_pdf, indice)
                        if coletar_paginas:
                            paginas_processadas.append(
                                PaginaProcessada(indice, _renderizar_pagina(pagina), palavras)
                            )
                        if indice == 0:
                            parser.localizar_campos(palavras, dados)

                if dados.esta_completo():
                    logger.info("%s: todos os campos principais vieram do texto digital.", nome_arquivo)
                    return ResultadoProcessamento(dados, paginas_processadas)

                logger.info(
                    "%s: texto digital incompleto (%s). Complementando com OCR.",
                    nome_arquivo, ", ".join(dados.campos_faltantes()),
                )

            # --- Camada OCR: renderiza e reconhece página a página ---
            paginas_ocr: List[PaginaProcessada] = []
            houve_texto_ocr = False

            for indice, pagina in enumerate(documento):
                if indice >= MAX_PAGINAS_OCR:
                    logger.info("%s: limite de %d páginas para OCR atingido.", nome_arquivo, MAX_PAGINAS_OCR)
                    break

                try:
                    imagem = _renderizar_pagina(pagina)
                    processada, escala = preprocessar_imagem_para_ocr(imagem)
                    texto_ocr, palavras = _ocr_da_imagem(processada, indice, escala)
                except OCRError:
                    raise
                except Exception as erro:
                    raise OCRError(f"{nome_arquivo}: erro ao preparar a página {indice + 1}: {erro}") from erro

                if texto_ocr.strip():
                    houve_texto_ocr = True

                parser.extrair_de_texto(texto_ocr, dados, origem=Origem.REGEX)
                parser.extrair_posicional(palavras, dados)
                parser.localizar_campos(palavras, dados)

                paginas_ocr.append(PaginaProcessada(indice, imagem, palavras))

                if dados.esta_completo():
                    logger.info("%s: campos completos na página %d.", nome_arquivo, indice + 1)
                    break

            # Preferimos as páginas do OCR para inspeção: elas têm as palavras
            # que realmente alimentaram a extração.
            if coletar_paginas and paginas_ocr:
                paginas_processadas = paginas_ocr

            if not houve_texto_ocr and not tem_texto_digital:
                raise LayoutNaoReconhecidoError(f"{nome_arquivo}: o OCR não retornou texto.")

            return ResultadoProcessamento(dados, paginas_processadas)

    except ExtractionError:
        raise
    except FileNotFoundError as erro:
        raise ExtractionError(f"{nome_arquivo}: arquivo não encontrado.") from erro
    except Exception as erro:
        raise ExtractionError(f"{nome_arquivo}: {erro}") from erro


# --------------------------------------------------------------------------- #
# Imagem
# --------------------------------------------------------------------------- #

def processar_imagem(
    caminho_imagem: str,
    parser: BoletoParser,
    coletar_paginas: bool = False,
) -> ResultadoProcessamento:
    """Processa uma imagem (PNG, JPG, TIFF...) via OCR."""
    nome_arquivo = os.path.basename(caminho_imagem)
    dados = BoletoData(arquivo_origem=nome_arquivo)

    try:
        with Image.open(caminho_imagem) as arquivo:
            original = arquivo.convert("RGB")

        processada, escala = preprocessar_imagem_para_ocr(original)
        texto_ocr, palavras = _ocr_da_imagem(processada, 0, escala)

        if not texto_ocr.strip():
            raise LayoutNaoReconhecidoError(f"{nome_arquivo}: o OCR não retornou texto.")

        parser.extrair_de_texto(texto_ocr, dados, origem=Origem.REGEX)
        parser.extrair_posicional(palavras, dados)
        parser.localizar_campos(palavras, dados)

        paginas = [PaginaProcessada(0, original, palavras)] if coletar_paginas else []
        return ResultadoProcessamento(dados, paginas)

    except ExtractionError:
        raise
    except FileNotFoundError as erro:
        raise ExtractionError(f"{nome_arquivo}: arquivo não encontrado.") from erro
    except Exception as erro:
        raise ExtractionError(f"{nome_arquivo}: {erro}") from erro


# --------------------------------------------------------------------------- #
# Entrada única
# --------------------------------------------------------------------------- #

def e_suportado(caminho: str) -> bool:
    """True se a extensão do arquivo é processável."""
    return caminho.lower().endswith(EXTENSOES_SUPORTADAS)


def processar_arquivo(
    caminho: str,
    parser: Optional[BoletoParser] = None,
    coletar_paginas: bool = False,
) -> ResultadoProcessamento:
    """
    Processa um arquivo, escolhendo o pipeline pela extensão.

    É o ponto de entrada usado pela GUI, pela CLI e pelos testes.
    """
    parser = parser or BoletoParser()
    if caminho.lower().endswith(EXTENSOES_PDF):
        return processar_pdf(caminho, parser, coletar_paginas)
    if caminho.lower().endswith(EXTENSOES_IMAGEM):
        return processar_imagem(caminho, parser, coletar_paginas)
    raise ExtractionError(
        f"{os.path.basename(caminho)}: formato não suportado "
        f"(aceitos: {', '.join(EXTENSOES_SUPORTADAS)})."
    )


def listar_arquivos_suportados(entradas: Sequence[str], recursivo: bool = False) -> List[str]:
    """
    Expande arquivos e pastas em uma lista de arquivos processáveis.

    Ignora arquivos temporários do Office (``~$...``) e ordena o resultado para
    que o processamento em lote seja determinístico.
    """
    encontrados: List[str] = []

    for entrada in entradas:
        if os.path.isfile(entrada):
            if e_suportado(entrada):
                encontrados.append(entrada)
            continue

        if not os.path.isdir(entrada):
            logger.warning("Entrada ignorada (não existe): %s", entrada)
            continue

        if recursivo:
            for raiz, _, arquivos in os.walk(entrada):
                encontrados.extend(
                    os.path.join(raiz, nome) for nome in arquivos
                    if e_suportado(nome) and not nome.startswith("~$")
                )
        else:
            encontrados.extend(
                os.path.join(entrada, nome) for nome in os.listdir(entrada)
                if e_suportado(nome) and not nome.startswith("~$")
                and os.path.isfile(os.path.join(entrada, nome))
            )

    return sorted(set(encontrados))
