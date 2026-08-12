# -*- coding: utf-8 -*-
"""
tests/test_cli.py

Testes da linha de comando.

Como a CLI usa exatamente o mesmo serviço da interface gráfica, estes testes
exercitam o lote de ponta a ponta sem abrir nenhuma janela — algo impossível
enquanto o processamento vivia dentro da GUI.
"""

import shutil

import pandas as pd
import pytest

import cli


def test_ajuda_nao_quebra(capsys):
    with pytest.raises(SystemExit) as saida:
        cli.main(["--help"])
    assert saida.value.code == 0
    assert "extrair" in capsys.readouterr().out


def test_versao(capsys):
    assert cli.main(["--versao"]) == cli.CODIGO_SUCESSO
    assert "AutoScanExtractor" in capsys.readouterr().out


def test_extrair_gera_planilha(tmp_path, arquivos_teste):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    shutil.copy(arquivos_teste["jpg"], entrada / "boleto.jpg")
    destino = tmp_path / "resultado.xlsx"

    codigo = cli.main(["extrair", "-e", str(entrada), "-s", str(destino)])

    assert codigo == cli.CODIGO_SUCESSO
    assert destino.exists()

    gravado = pd.read_excel(destino)
    assert len(gravado) == 1
    assert gravado["Arquivo_Origem"].iloc[0] == "boleto.jpg"
    assert gravado["Codigo_Barras_Valido"].iloc[0] == "Sim"
    assert float(gravado["Valor_Documento"].iloc[0]) == pytest.approx(106.00)


def test_extrair_sem_arquivos_suportados(tmp_path, capsys):
    (tmp_path / "nota.txt").write_text("nada aqui")
    codigo = cli.main(["extrair", "-e", str(tmp_path), "-s", str(tmp_path / "x.xlsx")])
    assert codigo == cli.CODIGO_FALHA
    assert "Nenhum arquivo suportado" in capsys.readouterr().err


def test_extrair_pula_arquivos_ja_processados(tmp_path, arquivos_teste):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    shutil.copy(arquivos_teste["jpg"], entrada / "boleto.jpg")
    destino = tmp_path / "resultado.xlsx"

    cli.main(["extrair", "-e", str(entrada), "-s", str(destino)])
    cli.main(["extrair", "-e", str(entrada), "-s", str(destino)])

    assert len(pd.read_excel(destino)) == 1


def test_inspecionar_gera_imagem_anotada(tmp_path, arquivos_teste, capsys):
    destino = tmp_path / "anotado.png"
    codigo = cli.main(["inspecionar", arquivos_teste["jpg"], "-s", str(destino)])

    assert codigo == cli.CODIGO_SUCESSO
    assert destino.exists()

    saida = capsys.readouterr().out
    assert "Linha digitável: válida" in saida
    assert "Vencimento" in saida


def test_inspecionar_arquivo_inexistente(capsys):
    assert cli.main(["inspecionar", "/nao/existe.pdf"]) == cli.CODIGO_FALHA
    assert "não encontrado" in capsys.readouterr().err


def test_inspecionar_sem_imagem(tmp_path, arquivos_teste, capsys):
    codigo = cli.main(["inspecionar", arquivos_teste["jpg"], "--sem-imagem"])
    assert codigo == cli.CODIGO_SUCESSO
    assert not list(tmp_path.glob("*.png"))
