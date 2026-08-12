# -*- coding: utf-8 -*-
"""
cli.py

Interface de linha de comando do AutoScanExtractor.

Exemplos::

    autoscan extrair -e boletos/ -s planilha.xlsx
    autoscan extrair -e a.pdf b.jpg -s saida.xlsx --recursivo
    autoscan inspecionar boleto.pdf              # mostra e marca onde cada dado foi lido
    autoscan gui                                 # abre a interface gráfica

Sem argumentos, abre a interface gráfica — o mesmo comportamento de antes.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)

DESCRICAO = "Extrai vencimento, valor, beneficiário, pagador e código de barras de boletos."
EPILOGO = """exemplos:
  %(prog)s extrair -e boletos/ -s planilha.xlsx
  %(prog)s extrair -e nota.pdf -s saida.xlsx --verboso
  %(prog)s inspecionar boleto.pdf -s marcado.png
  %(prog)s gui
"""

CODIGO_SUCESSO = 0
CODIGO_FALHA = 1
CODIGO_USO_INVALIDO = 2


def construir_parser() -> argparse.ArgumentParser:
    """Monta o parser de argumentos da CLI."""
    parser = argparse.ArgumentParser(
        prog="autoscan",
        description=DESCRICAO,
        epilog=EPILOGO,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verboso", "-v", action="store_true", help="mostra o log detalhado.")
    parser.add_argument("--versao", action="store_true", help="mostra a versão e sai.")

    subcomandos = parser.add_subparsers(dest="comando")

    extrair = subcomandos.add_parser(
        "extrair", help="processa arquivos/pastas e grava a planilha.",
        description="Processa boletos em lote e consolida os dados em uma planilha Excel.",
    )
    extrair.add_argument(
        "-e", "--entrada", nargs="+", required=True, metavar="CAMINHO",
        help="arquivos e/ou pastas a processar.",
    )
    extrair.add_argument(
        "-s", "--saida", metavar="PLANILHA.xlsx",
        help="planilha de saída (padrão: boletos.xlsx na pasta atual).",
    )
    extrair.add_argument(
        "-r", "--recursivo", action="store_true",
        help="percorre subpastas ao receber uma pasta.",
    )
    extrair.add_argument(
        "--sem-planilha", action="store_true",
        help="apenas imprime os resultados, sem gravar arquivo.",
    )
    extrair.add_argument(
        "--reprocessar", action="store_true",
        help="processa novamente arquivos que já constam na planilha.",
    )
    extrair.add_argument("--verboso", "-v", action="store_true", help=argparse.SUPPRESS)

    inspecionar = subcomandos.add_parser(
        "inspecionar", help="mostra onde cada dado foi encontrado no documento.",
        description=(
            "Processa um único arquivo e gera uma imagem com os campos destacados, "
            "indicando de onde cada dado foi lido."
        ),
    )
    inspecionar.add_argument("arquivo", help="arquivo PDF ou imagem a inspecionar.")
    inspecionar.add_argument(
        "-s", "--saida", metavar="IMAGEM.png",
        help="imagem anotada de saída (padrão: <arquivo>_anotado.png).",
    )
    inspecionar.add_argument(
        "-p", "--pagina", type=int, default=None, metavar="N",
        help="página a anotar (1 = primeira). Padrão: a página com os campos.",
    )
    inspecionar.add_argument(
        "--sem-imagem", action="store_true",
        help="apenas imprime o relatório, sem gerar imagem.",
    )
    inspecionar.add_argument("--verboso", "-v", action="store_true", help=argparse.SUPPRESS)

    subcomandos.add_parser("gui", help="abre a interface gráfica.")
    return parser


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #

def comando_extrair(args: argparse.Namespace) -> int:
    """Processa um lote e grava a planilha."""
    from extractor_service import ServicoExtracao
    from file_processor import listar_arquivos_suportados
    from planilha import PlanilhaError

    arquivos = listar_arquivos_suportados(args.entrada, recursivo=args.recursivo)
    if not arquivos:
        print("Nenhum arquivo suportado encontrado (.pdf, .png, .jpg, .jpeg, .tiff, .bmp, .gif).",
              file=sys.stderr)
        return CODIGO_FALHA

    destino = None if args.sem_planilha else (args.saida or "boletos.xlsx")

    servico = ServicoExtracao()
    try:
        resumo = servico.processar_lote(
            arquivos,
            caminho_planilha=destino,
            on_log=print,
            pular_ja_processados=not args.reprocessar,
        )
    except PlanilhaError as erro:
        print(f"\nERRO ao gravar a planilha: {erro}", file=sys.stderr)
        return CODIGO_FALHA

    print("\n" + resumo.texto())
    return CODIGO_FALHA if resumo.falhas and not resumo.processados else CODIGO_SUCESSO


def comando_inspecionar(args: argparse.Namespace) -> int:
    """Processa um arquivo e mostra onde cada campo foi encontrado."""
    from extraction_logic import ExtractionError
    from file_processor import processar_arquivo
    from visualizer import descrever_extracao, pagina_com_campos, salvar_anotacao

    if not os.path.isfile(args.arquivo):
        print(f"Arquivo não encontrado: {args.arquivo}", file=sys.stderr)
        return CODIGO_FALHA

    try:
        resultado = processar_arquivo(args.arquivo, coletar_paginas=not args.sem_imagem)
    except ExtractionError as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return CODIGO_FALHA

    print(descrever_extracao(resultado.dados))

    if args.sem_imagem:
        return CODIGO_SUCESSO

    if not resultado.paginas:
        print("\nNão foi possível renderizar a página para anotar.", file=sys.stderr)
        return CODIGO_FALHA

    if args.pagina is not None:
        indice = args.pagina - 1
    else:
        indice = pagina_com_campos(resultado.paginas, resultado.dados) or 0

    pagina = next((p for p in resultado.paginas if p.numero == indice), resultado.paginas[0])

    destino = args.saida or f"{os.path.splitext(args.arquivo)[0]}_anotado.png"
    salvar_anotacao(pagina.imagem, resultado.dados, destino, pagina=pagina.numero)
    print(f"\nImagem anotada: {destino}")
    return CODIGO_SUCESSO


def comando_gui(_args: argparse.Namespace) -> int:
    """Abre a interface gráfica."""
    from config import ocultar_console_proprio

    # No executável do Windows, o console existe para servir à CLI; ao abrir a
    # interface gráfica ele só atrapalha.
    ocultar_console_proprio()

    try:
        from gui import iniciar_gui
    except ImportError as erro:  # Tkinter ausente (comum em servidores Linux)
        print(
            f"Não foi possível carregar a interface gráfica: {erro}\n"
            "Use o modo de linha de comando: autoscan extrair --help",
            file=sys.stderr,
        )
        return CODIGO_FALHA
    return iniciar_gui()


# --------------------------------------------------------------------------- #
# Ponto de entrada
# --------------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    """Ponto de entrada da CLI. Devolve o código de saída do processo."""
    from config import configurar_logging

    parser = construir_parser()
    args = parser.parse_args(argv)

    if getattr(args, "versao", False):
        from version import __version__
        print(f"AutoScanExtractor {__version__}")
        return CODIGO_SUCESSO

    configurar_logging(verboso=getattr(args, "verboso", False))

    # Os comandos de extração precisam do Tesseract; a GUI faz essa checagem
    # sozinha para poder mostrar o erro em uma caixa de diálogo.
    if args.comando in ("extrair", "inspecionar"):
        from config import TesseractNaoEncontrado, setup_tesseract

        try:
            setup_tesseract()
        except TesseractNaoEncontrado as erro:
            print(f"ERRO: {erro}", file=sys.stderr)
            return CODIGO_FALHA

    comandos = {
        "extrair": comando_extrair,
        "inspecionar": comando_inspecionar,
        "gui": comando_gui,
    }

    if args.comando is None:
        # Sem subcomando: abre a GUI, preservando o comportamento histórico.
        return comando_gui(args)

    return comandos[args.comando](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
