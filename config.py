# -*- coding: utf-8 -*-
"""
config.py

Armazena constantes globais, configurações e a lógica de inicialização
de serviços externos, como o Tesseract.
"""

import os
import sys
import pytesseract
import platform # Necessário para detectar o OS (Windows/Linux)

# --- Constantes de Extração ---
DEFAULT_LANG = 'por'
OCR_CONF_THRESHOLD = 40
VALOR_MAX_DISTANCE = 700

# --- CAMINHOS DE DESENVOLVIMENTO (APENAS WINDOWS) ---
# Usado para rodar 'python main.py' ou 'pytest' na sua máquina Windows
DEV_TESSERACT_PATH_WINDOWS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEV_TESSDATA_PATH_WINDOWS = r"C:\Program Files\Tesseract-OCR\tessdata"


# --- FUNÇÃO HELPER PARA ENCONTRAR ARQUIVOS NO .EXE ---
def resource_path(relative_path):
    """
    Obtém o caminho absoluto para um recurso (ex: ícone, arquivo de dados).
    Necessário para que o executável PyInstaller encontre arquivos incluídos.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- CONFIGURAÇÃO DO TESSERACT (VERSÃO 3.0 - CORRETA PARA CI) ---
def setup_tesseract():
    """
    Define o caminho para o executável do Tesseract e seus dados.
    Diferencia entre o modo de produção (.exe), desenvolvimento Windows
    e desenvolvimento Linux/CI.
    """
    application_path = ""
    
    # Bloco TRY principal para pegar erros de configuração
    try:
        if getattr(sys, 'frozen', False):
            # --- MODO 1: RODANDO COMO .EXE (PRODUÇÃO) ---
            application_path = sys._MEIPASS
            
            tesseract_exe_path = os.path.join(application_path, 'tesseract.exe')
            tessdata_dir = os.path.join(application_path, 'tessdata')
            
            # Validação
            if not os.path.exists(tesseract_exe_path):
                raise FileNotFoundError(f"tesseract.exe não encontrado em (EXE) {tesseract_exe_path}")
            if not os.path.isdir(tessdata_dir):
                raise FileNotFoundError(f"Pasta tessdata não encontrada em (EXE) {tessdata_dir}")

            # Define os caminhos para o Pytesseract
            pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
            os.environ['TESSDATA_PREFIX'] = tessdata_dir
            print(f"INFO: Tesseract (EXE) configurado. CMD: {tesseract_exe_path}")

        elif platform.system() == "Windows":
            # --- MODO 2: RODANDO COMO SCRIPT .PY (DESENVOLVIMENTO - WINDOWS) ---
            application_path = os.path.dirname(os.path.abspath(__file__)) # Raiz do projeto
            tesseract_exe_path = DEV_TESSERACT_PATH_WINDOWS
            tessdata_dir = DEV_TESSDATA_PATH_WINDOWS

            # Validação
            if not os.path.exists(tesseract_exe_path):
                raise FileNotFoundError(f"Tesseract (Dev-Windows) não encontrado em {tesseract_exe_path}.")
            if not os.path.isdir(tessdata_dir):
                raise FileNotFoundError(f"Pasta tessdata (Dev-Windows) não encontrada em {tessdata_dir}.")

            # Define os caminhos para o Pytesseract
            pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
            os.environ['TESSDATA_PREFIX'] = tessdata_dir
            print(f"INFO: Tesseract (Dev-Windows) configurado. CMD: {tesseract_exe_path}")

        else:
            # --- MODO 3: RODANDO COMO SCRIPT .PY (DESENVOLVIMENTO - LINUX/MAC/CI) ---
            # Assumimos que Tesseract foi instalado no PATH do sistema
            # (ex: via 'apt-get' ou 'brew').
            # NÃO definimos 'tesseract_cmd' ou 'TESSDATA_PREFIX'.
            # Deixamos o Pytesseract encontrar o Tesseract automaticamente.
            application_path = os.path.dirname(os.path.abspath(__file__))
            print("INFO: Tesseract (Dev-Linux/Mac/CI) - Usando Tesseract do PATH do sistema.")
            # A validação de caminhos não é necessária, o Pytesseract fará isso abaixo.

        # --- Verificação Global (roda para todos os modos) ---
        try:
            version = pytesseract.get_tesseract_version()
            languages = pytesseract.get_languages(config='')
            print(f"INFO: Versão Tesseract detectada: {version}")
            
            if DEFAULT_LANG not in languages:
                print(f"AVISO: Idioma '{DEFAULT_LANG}' (Português) não foi encontrado!")
                # No CI, isso é um erro fatal, pois o 'por' foi explicitamente instalado.
                if platform.system() != "Windows":
                     raise FileNotFoundError(f"Idioma '{DEFAULT_LANG}' não encontrado pelo Tesseract no CI.")
            else:
                print(f"INFO: Idioma '{DEFAULT_LANG}' (Português) encontrado em tessdata.")
                
        except pytesseract.TesseractNotFoundError as e_find:
            # Isso vai pegar o erro se o Modo 3 (Linux) não encontrar o Tesseract
            print(f"FALHA CRÍTICA: Pytesseract não encontrou o Tesseract no PATH do sistema.")
            raise e_find
        except Exception as te:
            print(f"AVISO: Erro durante a verificação do Tesseract: {te}")

    # Bloco EXCEPT principal (sem tkinter)
    except Exception as e:
        # Loga o erro para o console (bom para CI) e re-levanta a exceção
        error_message = (f"FALHA CRÍTICA no setup_tesseract:\n{e}\n\n"
                        f"Caminho base detectado: {application_path}\n")
        print(error_message) 
        raise e # Re-levanta a exceção para o pytest ver