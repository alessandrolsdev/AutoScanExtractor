# -*- coding: utf-8 -*-
"""
tests/test_extraction_logic.py

Testes unitários do BoletoParser: conversão de tipos, regex e localização
visual dos campos.
"""

from datetime import date
from decimal import Decimal

import pytest

from boleto_data import BoletoData, Origem
from extraction_logic import Palavra, localizar_texto


# --- Vencimento por contexto (comportamento histórico preservado) -----------

def test_vencimento_com_rotulo_explicito(parser):
    texto = """
    Pagador: Sr. Ninguém
    Beneficiário: Empresa Fictícia
    Vencimento: 01/01/2025
    Valor: R$ 100,00
    """
    assert parser._extrair_vencimento_regex_contexto(texto) == "01/01/2025"


def test_vencimento_por_proximidade_da_palavra_venc(parser):
    texto = """
    Documento emitido em 10/12/2024
    Algum texto aleatório
    Data de venc. 15/02/2025
    """
    assert parser._extrair_vencimento_regex_contexto(texto) == "15/02/2025"


def test_vencimento_cai_para_a_data_mais_distante(parser):
    texto = """
    Data Emissão: 01/12/2024
    Data Documento: 05/12/2024
    Data Limite: 25/12/2024
    """
    assert parser._extrair_vencimento_regex_contexto(texto) == "25/12/2024"


def test_vencimento_ausente_retorna_none(parser):
    assert parser._extrair_vencimento_regex_contexto("Texto sem nenhuma data.") is None


# --- Conversão de datas -----------------------------------------------------

def test_parse_data_converte_para_tipo_date(parser):
    assert parser._parse_data("15/02/2025") == date(2025, 2, 15)


def test_parse_data_corrige_confusoes_de_ocr(parser):
    """O OCR lê 0 como O e 5 como S; a data ainda precisa sair correta."""
    assert parser._parse_data("O1/O2/2O25") == date(2025, 2, 1)
    assert parser._parse_data("1S/03/202S") == date(2025, 3, 15)


def test_parse_data_expande_ano_de_dois_digitos(parser):
    assert parser._parse_data("01/02/25") == date(2025, 2, 1)


@pytest.mark.parametrize("entrada", ["32/01/2025", "01/13/2025", "00/00/2025", "31/02/2025"])
def test_parse_data_rejeita_datas_impossiveis(parser, entrada):
    """Antes, qualquer coisa com cara de data entrava na planilha como texto."""
    assert parser._parse_data(entrada) is None


def test_parse_data_rejeita_ano_implausivel(parser):
    assert parser._parse_data("01/01/1200") is None


# --- Conversão de valores ---------------------------------------------------

def test_parse_valor_com_separador_de_milhar(parser):
    """
    Regressão: ``_clean_data`` trocava "." por "-" e corrompia todo valor
    acima de mil, gravando "1-234,56" na planilha.
    """
    assert parser._parse_valor("1.234,56") == Decimal("1234.56")


def test_parse_valor_simples_e_com_ruido(parser):
    assert parser._parse_valor("106,00") == Decimal("106.00")
    assert parser._parse_valor("  R$ 2.500,00 ") == Decimal("2500.00")
    assert parser._parse_valor("1O6,OO") == Decimal("106.00")


@pytest.mark.parametrize("entrada", ["", None, "abc", "0,00"])
def test_parse_valor_rejeita_lixo(parser, entrada):
    assert parser._parse_valor(entrada) is None


# --- Extração a partir de texto --------------------------------------------

def test_extrai_campos_de_um_texto_de_boleto(parser):
    texto = (
        "Beneficiário: EMPRESA EXEMPLO LTDA CNPJ 12.345.678/0001-90\n"
        "Vencimento: 10/03/2026\n"
        "(=) Valor do Documento 2.500,00\n"
        "Pagador: JOAO DA SILVA CPF: 123.456.789-00\n"
    )
    dados = parser.extrair_de_texto(texto, BoletoData(arquivo_origem="x.pdf"))

    assert dados.vencimento.valor == date(2026, 3, 10)
    assert dados.valor_documento.valor == Decimal("2500.00")
    assert dados.beneficiario.valor == "EMPRESA EXEMPLO LTDA"
    assert dados.pagador.valor == "JOAO DA SILVA"


def test_linha_digitavel_tem_precedencia_sobre_a_regex(parser, tmp_path):
    """
    Quando os dígitos verificadores fecham, o dado do código de barras vence.

    O texto abaixo traz um vencimento impresso divergente do codificado; a
    linha digitável é a fonte confiável e deve prevalecer.
    """
    from tests.conftest import gerar_linha_digitavel
    import linha_digitavel as ld

    linha = gerar_linha_digitavel(venc=date(2026, 9, 15), valor=Decimal("1234.56"))
    texto = (
        f"{ld.formatar_linha_digitavel(linha)}\n"
        "Vencimento: 01/01/2001\n"
        "(=) Valor do Documento 9.999,99\n"
    )
    dados = parser.extrair_de_texto(
        texto, BoletoData(arquivo_origem="x.pdf"), referencia=date(2026, 8, 1)
    )

    assert dados.linha_digitavel_valida
    assert dados.vencimento.valor == date(2026, 9, 15)
    assert dados.vencimento.origem == Origem.LINHA_DIGITAVEL
    assert dados.valor_documento.valor == Decimal("1234.56")


def test_dado_digital_nao_e_sobrescrito_por_ocr(parser):
    """
    Regressão: o resultado do texto digital era descartado ao cair no OCR.

    Agora as camadas se combinam por precedência de origem.
    """
    dados = BoletoData(arquivo_origem="x.pdf")
    parser.extrair_de_texto(
        "Beneficiário: NOME CORRETO LTDA\n", dados, origem=Origem.PDF_DIGITAL
    )
    parser.extrair_de_texto(
        "Beneficiário: NOME ERRADO DO OCR\n", dados, origem=Origem.REGEX
    )
    assert dados.beneficiario.valor == "NOME CORRETO LTDA"


def test_candidato_invalido_e_rejeitado(parser):
    assert not parser._is_valid_candidate("")
    assert not parser._is_valid_candidate("123")
    assert not parser._is_valid_candidate("12/03/2025")
    assert not parser._is_valid_candidate("NOSSO NÚMERO")
    assert parser._is_valid_candidate("EMPRESA EXEMPLO LTDA")


# --- Localização visual -----------------------------------------------------

def _palavras(*itens):
    return [Palavra(texto, x, y, 60, 20) for texto, x, y in itens]


def test_localiza_texto_em_palavras_consecutivas():
    palavras = _palavras(("EMPRESA", 10, 10), ("EXEMPLO", 80, 10), ("LTDA", 150, 10))
    regiao = localizar_texto(palavras, "EMPRESA EXEMPLO LTDA")
    assert regiao is not None
    assert regiao.x == 10
    assert regiao.largura == 200


def test_localizacao_ignora_token_muito_maior_que_o_alvo():
    """
    Regressão: "106,00" está contido no fim da linha digitável
    ("...83100000010600"), e o valor acabava marcado sobre o código de barras.
    """
    palavras = _palavras(("83100000010600", 500, 40),)
    assert localizar_texto(palavras, "106,00") is None


def test_localizacao_prefere_ocorrencia_perto_do_rotulo():
    """O mesmo valor aparece duas vezes; vence o que está junto do rótulo."""
    palavras = _palavras(
        ("535,71", 100, 100),          # ocorrência solta, no resumo
        ("Documento", 900, 900),       # rótulo do campo
        ("535,71", 900, 940),          # ocorrência do campo em si
    )
    regiao = localizar_texto(palavras, "535,71", perto_de=("documento",))
    assert regiao is not None
    assert regiao.y == 940
