# -*- coding: utf-8 -*-
"""
main.py

Ponto de entrada do AutoScanExtractor.

Sem argumentos abre a interface gráfica; com argumentos, delega para a CLI::

    python main.py                                  # interface gráfica
    python main.py extrair -e boletos/ -s saida.xlsx
    python main.py inspecionar boleto.pdf
"""

import sys

from cli import main

if __name__ == "__main__":
    sys.exit(main())
