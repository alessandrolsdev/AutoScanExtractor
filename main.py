# -*- coding: utf-8 -*-
"""
main.py

Ponto de entrada principal da aplicação AutoScanExtractor.

Responsabilidades:
1. Importar e rodar o setup do Tesseract.
2. Inicializar o Tkinter.
3. Instanciar e iniciar a classe 'App' da GUI.
"""

import tkinter as tk
from gui import App
from config import setup_tesseract

if __name__ == "__main__":
    # 1. Configura o Tesseract ANTES de criar a GUI
    print("INFO: Configurando Tesseract...")
    setup_tesseract()
    print("INFO: Tesseract configurado.")

    # 2. Inicia a aplicação GUI
    print("INFO: Iniciando a aplicação...")
    root = tk.Tk()
    app = App(root)
    root.mainloop()