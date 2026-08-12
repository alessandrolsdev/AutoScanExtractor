# -*- coding: utf-8 -*-
"""
tests/test_full_pipeline.py

Testes de ponta a ponta: arquivo real entra, dados estruturados saem.

Diferente da versão anterior, que apenas verificava se "algo" foi extraído
(um boleto lido 100% errado passaria), aqui os valores esperados são
afirmados explicitamente.
"""

from datetime import date
from decimal import Decimal

import pytest

import file_processor
from boleto_data import BoletoData, Origem
from extraction_logic import ExtractionError

# Valores conferidos manualmente nas amostras versionadas em tests/test_data.
ESPERADO_JPG = {
    "vencimento": date(2020, 7, 8),
    "valor": Decimal("106.00"),
    "codigo_barras": "23794.02510 97746.393988 98000.060008 1 83100000010600",
    "beneficiario_contem": "BRADESCARD",
    "pagador_contem": "EUZENI",
}

ESPERADO_PDF = {
    "vencimento": date(2025, 11, 17),
    "valor": Decimal("535.71"),
    "codigo_barras": "03399.00672 41210.101527 30991.101012 6 12680000053571",
    "beneficiario_contem": "ESTACIO",
    "pagador_contem": "ALESSANDRO",
}


def _sem_acento_maiusculo(texto: str) -> str:
    import unicodedata

    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in normalizado if not unicodedata.combining(c)).upper()


def _conferir(dados: BoletoData, esperado: dict) -> None:
    assert dados.linha_digitavel_valida, "a linha digitável deveria ter sido validada pelos DVs"
    assert dados.vencimento.valor == esperado["vencimento"]
    assert dados.valor_documento.valor == esperado["valor"]
    assert dados.codigo_barras.valor == esperado["codigo_barras"]
    assert esperado["beneficiario_contem"] in _sem_acento_maiusculo(dados.beneficiario.valor)
    assert esperado["pagador_contem"] in _sem_acento_maiusculo(dados.pagador.valor)


# --- Amostras reais ---------------------------------------------------------

def test_pipeline_de_imagem_escaneada(parser, arquivos_teste):
    resultado = file_processor.processar_arquivo(arquivos_teste["jpg"], parser)
    _conferir(resultado.dados, ESPERADO_JPG)


def test_pipeline_de_pdf_escaneado(parser, arquivos_teste):
    resultado = file_processor.processar_arquivo(arquivos_teste["pdf"], parser)
    _conferir(resultado.dados, ESPERADO_PDF)


# --- PDF digital: o caminho que não era testado ----------------------------

def test_pipeline_de_pdf_digital(parser, boleto_digital):
    """
    Regressão do bug que quebrava **todo** PDF com camada de texto.

    ``file_processor`` usava ``dataclasses.asdict`` sem importar o módulo, e o
    ``NameError`` resultante era mascarado pelo ``except Exception`` genérico
    como se fosse um erro de leitura do arquivo. Como a única amostra do repo
    era um PDF escaneado, a suíte nunca entrava nesse ramo.
    """
    resultado = file_processor.processar_arquivo(boleto_digital["caminho"], parser)
    dados = resultado.dados

    assert dados.vencimento.valor == boleto_digital["vencimento"]
    assert dados.valor_documento.valor == boleto_digital["valor"]
    assert "EMPRESA EXEMPLO" in dados.beneficiario.valor
    assert "JOAO DA SILVA" in dados.pagador.valor


def test_pdf_digital_nao_precisa_de_ocr(parser, boleto_digital):
    """Havendo camada de texto completa, nenhum campo deve vir do OCR."""
    resultado = file_processor.processar_arquivo(boleto_digital["caminho"], parser)
    origens = {
        campo.origem for campo in resultado.dados.campos().values() if campo.encontrado
    }
    assert Origem.REGEX not in origens
    assert Origem.POSICIONAL not in origens


# --- Coleta de páginas para inspeção visual --------------------------------

def test_coleta_paginas_para_inspecao(parser, arquivos_teste):
    resultado = file_processor.processar_arquivo(
        arquivos_teste["jpg"], parser, coletar_paginas=True
    )
    assert resultado.paginas, "nenhuma página coletada para inspeção"
    assert resultado.paginas[0].palavras, "nenhuma palavra posicionada coletada"


def test_campos_recebem_posicao_na_pagina(parser, arquivos_teste):
    """Os campos precisam de coordenadas para o modo de inspeção funcionar."""
    resultado = file_processor.processar_arquivo(
        arquivos_teste["pdf"], parser, coletar_paginas=True
    )
    com_regiao = [
        nome for nome, campo in resultado.dados.campos().items()
        if campo.encontrado and campo.regiao is not None
    ]
    assert len(com_regiao) >= 4, f"poucos campos localizados na página: {com_regiao}"


def test_anotacao_gera_imagem(parser, arquivos_teste, tmp_path):
    from PIL import Image

    from visualizer import salvar_anotacao

    resultado = file_processor.processar_arquivo(
        arquivos_teste["jpg"], parser, coletar_paginas=True
    )
    destino = tmp_path / "anotado.png"
    salvar_anotacao(resultado.paginas[0].imagem, resultado.dados, str(destino))

    assert destino.exists()
    with Image.open(destino) as imagem:
        assert imagem.size == resultado.paginas[0].imagem.size


# --- Erros ------------------------------------------------------------------

def test_arquivo_inexistente_levanta_erro_de_extracao(parser):
    with pytest.raises(ExtractionError):
        file_processor.processar_arquivo("/caminho/que/nao/existe.pdf", parser)


def test_formato_nao_suportado_levanta_erro(parser, tmp_path):
    arquivo = tmp_path / "documento.txt"
    arquivo.write_text("conteúdo")
    with pytest.raises(ExtractionError, match="não suportado"):
        file_processor.processar_arquivo(str(arquivo), parser)


def test_listagem_de_arquivos_suportados(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"")
    (tmp_path / "b.jpg").write_bytes(b"")
    (tmp_path / "c.txt").write_text("x")
    (tmp_path / "~$temp.pdf").write_bytes(b"")
    subpasta = tmp_path / "sub"
    subpasta.mkdir()
    (subpasta / "d.png").write_bytes(b"")

    encontrados = file_processor.listar_arquivos_suportados([str(tmp_path)])
    assert [p.rsplit("/", 1)[-1] for p in encontrados] == ["a.pdf", "b.jpg"]

    recursivo = file_processor.listar_arquivos_suportados([str(tmp_path)], recursivo=True)
    assert len(recursivo) == 3
