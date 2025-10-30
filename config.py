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

# --- CAMINHOS DE DESENVOLVIMENTO ---
# Detecta o sistema operacional para definir os caminhos corretos
DEV_TESSERACT_PATH = ""
DEV_TESSDATA_PATH = ""

if platform.system() == "Windows":
    # Caminho padrão de instalação do Tesseract 64-bit no Windows
    DEV_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    DEV_TESSDATA_PATH = r"C:\Program Files\Tesseract-OCR\tessdata"
else:
    # Caminho padrão de instalação no Ubuntu (GitHub Actions)
    DEV_TESSERACT_PATH = "/usr/bin/tesseract"
    DEV_TESSDATA_PATH = "/usr/share/tessdata"


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

# --- CONFIGURAÇÃO DO TESSERACT  ---
def setup_tesseract():
    """
    Define o caminho para o executável do Tesseract e seus dados.
    Diferencia entre o modo de produção (.exe) e desenvolvimento (.py / pytest).
    """
    tesseract_exe_path = ""
    tessdata_dir = ""
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

        else:
            # --- MODO 2: RODANDO COMO SCRIPT .PY (DESENVOLVIMENTO / TESTE) ---
            application_path = os.path.dirname(os.path.abspath(__file__)) # Raiz do projeto
            
            tesseract_exe_path = DEV_TESSERACT_PATH
            tessdata_dir = DEV_TESSDATA_PATH

            # Validação
            if not os.path.exists(tesseract_exe_path):
                raise FileNotFoundError(f"Tesseract (Dev) não encontrado em {tesseract_exe_path}. Verifique o caminho no config.py.")
            if not os.path.isdir(tessdata_dir):
                raise FileNotFoundError(f"Pasta tessdata (Dev) não encontrada em {tessdata_dir}. Verifique o caminho no config.py.")

        # --- Configuração Global (vale para os dois modos) ---
        
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
        print(f"INFO: Caminho do Tesseract CMD definido para: {tesseract_exe_path}")

        os.environ['TESSDATA_PREFIX'] = tessdata_dir
        print(f"INFO: TESSDATA_PREFIX definido para: {tessdata_dir}")

        # --- Verificação  ---
        # Este try/except é *aninhado* dentro do try principal
        try:
            version = pytesseract.get_tesseract_version()
            languages = pytesseract.get_languages(config='')
            print(f"INFO: Versão Tesseract detectada: {version}")
            
            if DEFAULT_LANG not in languages:
                print(f"AVISO: Idioma '{DEFAULT_LANG}' (Português) não foi encontrado nos dados do Tesseract!")
            else:
                print(f"INFO: Idioma '{DEFAULT_LANG}' (Português) encontrado em tessdata.")
                
        except pytesseract.TesseractNotFoundError:
            # Este erro não deve acontecer se as validações acima passaram
            raise FileNotFoundError(f"Tesseract não executável no caminho: {pytesseract.pytesseract.tesseract_cmd}")
        except Exception as te:
            print(f"AVISO: Erro durante a verificação do Tesseract: {te}")

    # Bloco EXCEPT principal 
    except Exception as e:
        # Loga o erro para o console (bom para CI) e re-levanta a exceção
        error_message = (f"FALHA CRÍTICA no setup_tesseract:\n{e}\n\n"
                        f"Caminho base detectado: {application_path}\n"
                        f"Tentativa Tesseract CMD: {tesseract_exe_path if 'tesseract_exe_path' in locals() else 'Não definido'}\n"
                        f"Tentativa TESSDATA_PREFIX: {tessdata_dir if 'tessdata_dir' in locals() else 'Não definido'}\n")
        print(error_message) # Imprime o erro no log do CI
        raise e # Re-levanta a exceção para o pytest ver