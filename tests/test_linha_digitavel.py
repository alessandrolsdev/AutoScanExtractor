# -*- coding: utf-8 -*-
"""
tests/test_linha_digitavel.py

Testes da decodificação e validação da linha digitável.

Esta é a camada que torna vencimento e valor determinísticos, então os testes
cobrem tanto a aritmética dos dígitos verificadores quanto a recuperação de
leituras de OCR imperfeitas.
"""

from datetime import date
from decimal import Decimal

import pytest

import linha_digitavel as ld
from tests.conftest import gerar_linha_digitavel


# --- Dígitos verificadores --------------------------------------------------

def test_modulo10_bate_com_exemplo_real():
    """
    Confere o módulo 10 contra os três campos de uma linha digitável publicada.

    Os DVs impressos são 1, 7 e 8; acertar os três por acaso teria chance de
    1 em 1000.
    """
    linha = "34191790010104351004791020150008184670000002000"
    assert ld.modulo10(linha[0:9]) == int(linha[9])
    assert ld.modulo10(linha[10:20]) == int(linha[20])
    assert ld.modulo10(linha[21:31]) == int(linha[31])


def test_modulo11_trata_restos_especiais():
    """Restos 0, 1 e 10 devem produzir DV igual a 1, conforme a FEBRABAN."""
    # O DV calculado nunca pode ser 0, 10 ou 11.
    for codigo in ("0" * 43, "1" * 43, "9" * 43, "1234567890" * 4 + "123"):
        assert 1 <= ld.modulo11_codigo_barras(codigo) <= 9


def test_valida_linha_gerada():
    linha = gerar_linha_digitavel()
    assert ld.validar_linha_digitavel(linha)


@pytest.mark.parametrize("posicao", [0, 9, 20, 31, 32, 46])
def test_rejeita_linha_com_digito_alterado(posicao):
    """Alterar qualquer dígito deve quebrar algum dos verificadores."""
    linha = list(gerar_linha_digitavel())
    linha[posicao] = "0" if linha[posicao] != "0" else "9"
    assert not ld.validar_linha_digitavel("".join(linha))


def test_rejeita_entradas_malformadas():
    assert not ld.validar_linha_digitavel("")
    assert not ld.validar_linha_digitavel("123")
    assert not ld.validar_linha_digitavel("a" * 47)


# --- Conversões -------------------------------------------------------------

def test_conversao_linha_codigo_barras_ida_e_volta():
    linha = gerar_linha_digitavel()
    codigo = ld.linha_para_codigo_barras(linha)
    assert len(codigo) == ld.TAMANHO_CODIGO_BARRAS
    assert ld.validar_codigo_barras(codigo)
    assert ld.codigo_barras_para_linha(codigo) == linha


def test_formatacao_da_linha():
    linha = gerar_linha_digitavel()
    formatada = ld.formatar_linha_digitavel(linha)
    assert formatada.count(".") == 3
    assert formatada.count(" ") == 4
    assert "".join(c for c in formatada if c.isdigit()) == linha


# --- Fator de vencimento ----------------------------------------------------

def test_fator_1000_e_a_data_base_conhecida():
    """O fator 1000 equivale a 03/07/2000 — a referência oficial da FEBRABAN."""
    assert ld.fator_para_data(1000, referencia=date(2000, 1, 1)) == date(2000, 7, 3)


def test_fator_9999_encerra_o_primeiro_ciclo():
    assert ld.fator_para_data(9999, referencia=date(2025, 1, 1)) == date(2025, 2, 21)


def test_fator_reiniciado_apos_2025():
    """
    Depois de 21/02/2025 o fator reinicia em 1000.

    Sem tratar o reinício, todo boleto emitido a partir de 2025 teria a data de
    vencimento decodificada com 27 anos de erro.
    """
    assert ld.fator_para_data(1000, referencia=date(2025, 6, 1)) == date(2025, 2, 22)


def test_fator_zero_significa_sem_vencimento():
    assert ld.fator_para_data(0) is None


def test_decodifica_vencimento_e_valor():
    venc, valor = date(2026, 9, 15), Decimal("1234.56")
    linha = gerar_linha_digitavel(venc=venc, valor=valor)
    decodificado = ld.decodificar(linha, referencia=date(2026, 8, 1))
    assert decodificado.vencimento == venc
    assert decodificado.valor == valor
    assert decodificado.banco == "341"


def test_decodificar_rejeita_linha_invalida():
    linha = list(gerar_linha_digitavel())
    linha[5] = "0" if linha[5] != "0" else "7"
    with pytest.raises(ld.LinhaDigitavelInvalida):
        ld.decodificar("".join(linha))


# --- Busca em texto de OCR --------------------------------------------------

def test_encontra_linha_em_texto_com_letras_confundidas():
    """O OCR troca 0 por O e 1 por l; a busca precisa atravessar isso."""
    linha = gerar_linha_digitavel()
    suja = ld.formatar_linha_digitavel(linha).replace("0", "O").replace("1", "l")
    texto = f"BANCO EXEMPLO\nPagável em qualquer banco\n{suja}\nBeneficiário: FULANO"

    achado = ld.encontrar_linha_digitavel(texto, referencia=date(2026, 8, 1))
    assert achado is not None
    assert achado.linha_digitavel == linha


def test_corrige_dois_digitos_errados_usando_os_dv():
    """Os próprios dígitos verificadores servem de oráculo para a correção."""
    linha = gerar_linha_digitavel()
    quebrada = list(linha)
    quebrada[7] = "8" if quebrada[7] != "8" else "0"
    quebrada[25] = "6" if quebrada[25] != "6" else "5"
    quebrada = "".join(quebrada)

    assert not ld.validar_linha_digitavel(quebrada)
    assert ld.corrigir_por_dv(quebrada) == linha


def test_nao_inventa_linha_onde_nao_existe():
    """
    Texto sem boleto não pode gerar falso positivo.

    Quatro dígitos verificadores tornam isso improvável, e o filtro de
    plausibilidade (data e valor) elimina o que sobra.
    """
    assert ld.encontrar_linha_digitavel("") is None
    assert ld.encontrar_linha_digitavel("Nota fiscal 123456, total 500,00 em 01/02/2026") is None
    assert ld.encontrar_linha_digitavel("0" * 60) is None


def test_encontra_linha_quebrada_em_varias_linhas_de_texto():
    """O OCR frequentemente quebra a linha digitável em pedaços."""
    linha = gerar_linha_digitavel()
    formatada = ld.formatar_linha_digitavel(linha)
    meio = len(formatada) // 2
    texto = f"Cabeçalho\n{formatada[:meio]}\n{formatada[meio:]}\nRodapé"

    achado = ld.encontrar_linha_digitavel(texto, referencia=date(2026, 8, 1))
    assert achado is not None
    assert achado.linha_digitavel == linha
