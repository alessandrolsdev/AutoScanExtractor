# -*- coding: utf-8 -*-
"""
tests/test_planilha.py

Testes da consolidação da planilha.

A regra central aqui é a deduplicação: boletos sem código de barras legível
precisam sobreviver, porque não há como afirmar que são o mesmo documento.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

import planilha
from boleto_data import TEXTO_NAO_ENCONTRADO, BoletoData, Origem


def _boleto(nome, codigo=None, valor="100.00", venc=date(2026, 1, 10), valida=False):
    dados = BoletoData(arquivo_origem=nome)
    dados.vencimento.definir(venc, origem=Origem.REGEX)
    dados.valor_documento.definir(Decimal(valor), origem=Origem.REGEX)
    dados.beneficiario.definir("EMPRESA X", origem=Origem.REGEX)
    if codigo:
        dados.codigo_barras.definir(codigo, origem=Origem.LINHA_DIGITAVEL)
        dados.linha_digitavel_valida = valida
    return dados


def test_boletos_sem_codigo_de_barras_nao_colapsam(tmp_path):
    """
    Regressão do bug de perda de dados.

    ``drop_duplicates(subset=['Codigo_Barras'])`` tratava todas as linhas com
    "Não encontrado" como duplicatas entre si: um lote de 5 boletos cujo código
    o OCR não leu virava **uma única linha** na planilha.
    """
    destino = tmp_path / "saida.xlsx"
    boletos = [_boleto(f"boleto_{indice}.pdf") for indice in range(5)]

    resumo = planilha.salvar(str(destino), boletos)

    assert resumo.total_registros == 5
    assert resumo.duplicados_removidos == 0
    gravado = pd.read_excel(destino)
    assert len(gravado) == 5
    assert set(gravado["Arquivo_Origem"]) == {f"boleto_{i}.pdf" for i in range(5)}


def test_codigos_de_barras_repetidos_sao_deduplicados(tmp_path):
    destino = tmp_path / "saida.xlsx"
    boletos = [
        _boleto("a.pdf", codigo="12345.67890 12345.678901 12345.678901 1 12340000010000"),
        _boleto("b.pdf", codigo="12345.67890 12345.678901 12345.678901 1 12340000010000"),
        _boleto("c.pdf", codigo="99999.99999 99999.999999 99999.999999 9 99990000020000"),
    ]

    resumo = planilha.salvar(str(destino), boletos)

    assert resumo.duplicados_removidos == 1
    assert resumo.total_registros == 2


def test_mistura_de_com_e_sem_codigo(tmp_path):
    """Deduplicar os identificáveis não pode arrastar os demais junto."""
    destino = tmp_path / "saida.xlsx"
    codigo = "12345.67890 12345.678901 12345.678901 1 12340000010000"
    boletos = [
        _boleto("a.pdf", codigo=codigo),
        _boleto("b.pdf", codigo=codigo),
        _boleto("c.pdf"),
        _boleto("d.pdf"),
    ]

    resumo = planilha.salvar(str(destino), boletos)

    assert resumo.total_registros == 3  # 1 deduplicado + 2 sem código
    gravado = pd.read_excel(destino)
    assert (gravado["Codigo_Barras"] == TEXTO_NAO_ENCONTRADO).sum() == 2


def test_colunas_saem_tipadas(tmp_path):
    """
    Data e valor vão para o Excel como tipos nativos.

    Antes eram strings, o que impedia ordenar por vencimento ou somar valores
    diretamente na planilha.
    """
    destino = tmp_path / "saida.xlsx"
    planilha.salvar(str(destino), [_boleto("a.pdf", valor="1234.56", venc=date(2026, 3, 10))])

    gravado = pd.read_excel(destino)
    assert pd.api.types.is_numeric_dtype(gravado["Valor_Documento"])
    assert float(gravado["Valor_Documento"].iloc[0]) == pytest.approx(1234.56)
    assert pd.to_datetime(gravado["Vencimento"].iloc[0]).date() == date(2026, 3, 10)


def test_anexa_a_planilha_existente(tmp_path):
    destino = tmp_path / "saida.xlsx"
    planilha.salvar(str(destino), [_boleto("a.pdf")])

    existente = planilha.carregar_existente(str(destino))
    resumo = planilha.salvar(str(destino), [_boleto("b.pdf")], existente=existente)

    assert resumo.total_registros == 2
    assert set(pd.read_excel(destino)["Arquivo_Origem"]) == {"a.pdf", "b.pdf"}


def test_arquivos_ja_processados_reconhece_sufixos_antigos():
    """Versões anteriores gravavam 'nome.pdf (OCR)' na coluna de origem."""
    existente = pd.DataFrame({"Arquivo_Origem": ["a.pdf (OCR)", "b.pdf (Digital)", "c.pdf"]})
    nomes = planilha.arquivos_ja_processados(existente)
    assert {"a.pdf", "b.pdf", "c.pdf"} <= nomes


def test_planilha_corrompida_nao_derruba_o_lote(tmp_path):
    """Uma planilha ilegível vira aviso, não exceção: o lote precisa continuar."""
    destino = tmp_path / "quebrada.xlsx"
    destino.write_text("isso não é um arquivo xlsx")
    assert planilha.carregar_existente(str(destino)).empty


def test_boletos_sem_nenhum_dado_sao_descartados(tmp_path):
    destino = tmp_path / "saida.xlsx"
    resumo = planilha.salvar(str(destino), [BoletoData(arquivo_origem="vazio.pdf")])
    assert resumo.total_registros == 0
