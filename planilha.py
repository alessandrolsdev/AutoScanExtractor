# -*- coding: utf-8 -*-
"""
planilha.py

Leitura e escrita da planilha de resultados.

Ficava dentro da GUI, o que impedia testar a consolidação sem abrir uma janela
— e escondia um bug de perda de dados: a deduplicação por código de barras
tratava todos os boletos *sem* código lido como se fossem o mesmo registro,
colapsando o lote inteiro em uma única linha. Aqui a deduplicação só se aplica
a códigos efetivamente válidos.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Set

import pandas as pd

from boleto_data import COLUNAS_PLANILHA, TEXTO_NAO_ENCONTRADO, BoletoData

logger = logging.getLogger(__name__)


class PlanilhaError(Exception):
    """Falha ao ler ou gravar a planilha."""


@dataclass
class ResumoPlanilha:
    """O que aconteceu ao consolidar a planilha."""

    caminho: str
    total_registros: int = 0
    novos_registros: int = 0
    duplicados_removidos: int = 0
    arquivos_ignorados: int = 0
    colunas: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Planilha: {self.caminho}\n"
            f"Total de registros: {self.total_registros}\n"
            f"Novos adicionados: {self.novos_registros}\n"
            f"Arquivos ignorados (já processados): {self.arquivos_ignorados}"
        )


def carregar_existente(caminho: str) -> pd.DataFrame:
    """
    Lê a planilha anterior, se houver.

    Uma planilha corrompida ou aberta em outro programa não interrompe o lote:
    o erro é registrado e o processamento segue criando uma planilha nova.
    """
    if not caminho or not os.path.exists(caminho):
        return pd.DataFrame()
    try:
        existente = pd.read_excel(caminho)
        logger.info("Planilha existente carregada: %d registro(s).", len(existente))
        return existente
    except Exception as erro:
        logger.warning(
            "Não foi possível ler a planilha '%s' (%s). Uma nova será criada.", caminho, erro
        )
        return pd.DataFrame()


def arquivos_ja_processados(existente: pd.DataFrame) -> Set[str]:
    """Nomes de arquivo já presentes na planilha, para pular reprocessamento."""
    if existente.empty or "Arquivo_Origem" not in existente.columns:
        return set()
    nomes = set(existente["Arquivo_Origem"].dropna().astype(str))
    # Versões anteriores gravavam sufixos indicando o modo de leitura.
    for nome in list(nomes):
        for sufixo in (" (Digital)", " (OCR)"):
            if nome.endswith(sufixo):
                nomes.add(nome[: -len(sufixo)])
    return nomes


def _tem_codigo_valido(serie: pd.Series) -> pd.Series:
    """Marca as linhas cujo código de barras pode ser usado para deduplicar."""
    if serie is None:
        return pd.Series(dtype=bool)
    texto = serie.fillna("").astype(str).str.strip()
    return (texto != "") & (texto != TEXTO_NAO_ENCONTRADO)


def deduplicar(quadro: pd.DataFrame) -> tuple:
    """
    Remove registros repetidos pelo código de barras.

    Linhas sem código de barras legível são sempre preservadas: não há como
    afirmar que são o mesmo boleto, e descartá-las apagava dados reais.
    """
    if quadro.empty or "Codigo_Barras" not in quadro.columns:
        return quadro, 0

    com_codigo = _tem_codigo_valido(quadro["Codigo_Barras"])
    identificaveis = quadro[com_codigo]
    sem_codigo = quadro[~com_codigo]

    antes = len(identificaveis)
    identificaveis = identificaveis.drop_duplicates(subset=["Codigo_Barras"], keep="last")
    removidos = antes - len(identificaveis)

    combinado = pd.concat([identificaveis, sem_codigo], ignore_index=False).sort_index()
    return combinado.reset_index(drop=True), removidos


def montar_dataframe(registros: Sequence[BoletoData]) -> pd.DataFrame:
    """Converte os boletos extraídos em um DataFrame com as colunas padrão."""
    if not registros:
        return pd.DataFrame(columns=COLUNAS_PLANILHA)
    return pd.DataFrame([boleto.to_row() for boleto in registros])


def _ordenar_colunas(quadro: pd.DataFrame) -> pd.DataFrame:
    """Coloca as colunas conhecidas na ordem padrão, preservando as demais."""
    conhecidas = [coluna for coluna in COLUNAS_PLANILHA if coluna in quadro.columns]
    extras = [coluna for coluna in quadro.columns if coluna not in COLUNAS_PLANILHA]
    return quadro[conhecidas + extras]


def salvar(
    caminho: str,
    registros: Iterable[BoletoData],
    existente: pd.DataFrame = None,
    arquivos_ignorados: int = 0,
) -> ResumoPlanilha:
    """
    Consolida os novos registros com a planilha existente e grava o arquivo.

    Levanta ``PlanilhaError`` quando o arquivo não pode ser gravado (o caso
    comum é a planilha estar aberta no Excel).
    """
    registros = [boleto for boleto in registros if boleto.tem_algum_dado()]
    existente = pd.DataFrame() if existente is None else existente

    novos = montar_dataframe(registros)
    combinado = pd.concat([existente, novos], ignore_index=True) if not existente.empty else novos
    combinado = _ordenar_colunas(combinado)
    combinado, duplicados = deduplicar(combinado)

    if "Vencimento" in combinado.columns:
        combinado["Vencimento"] = pd.to_datetime(combinado["Vencimento"], errors="coerce").dt.date

    try:
        pasta = os.path.dirname(os.path.abspath(caminho))
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        combinado.to_excel(caminho, index=False)
    except PermissionError as erro:
        raise PlanilhaError(
            f"Não foi possível gravar '{caminho}'. "
            "Verifique se a planilha não está aberta em outro programa."
        ) from erro
    except Exception as erro:
        raise PlanilhaError(f"Não foi possível gravar '{caminho}': {erro}") from erro

    resumo = ResumoPlanilha(
        caminho=caminho,
        total_registros=len(combinado),
        novos_registros=len(novos),
        duplicados_removidos=duplicados,
        arquivos_ignorados=arquivos_ignorados,
        colunas=list(combinado.columns),
    )
    logger.info(
        "Planilha gravada: %d registro(s), %d novo(s), %d duplicado(s) removido(s).",
        resumo.total_registros, resumo.novos_registros, resumo.duplicados_removidos,
    )
    return resumo
