# -*- coding: utf-8 -*-
"""
config.py

Armazena constantes globais, configurações e a lógica de inicialização
de serviços externos, como o Tesseract.
"""

import os
import sys
import pytesseract
import platform # Usado para encontrar o caminho padrão do Tesseract

# --- Constantes de Extração ---
DEFAULT_LANG = 'por'
OCR_CONF_THRESHOLD = 40     # Confiança mínima do OCR (do seu Modo 2)
VALOR_MAX_DISTANCE = 700  # Distância máxima para associar valor (do seu Modo 2)

# --- CAMINHOS DE DESENVOLVIMENTO ---
# Usado para rodar 'python main.py' ou 'pytest'
# Detecta o caminho padrão do Tesseract no Windows.
if platform.system() == "Windows":
    # Caminho padrão de instalação do Tesseract 64-bit
    DEV_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    DEV_TESSDATA_PATH = r"C:\Program Files\Tesseract-OCR\tessdata"
else:
    # Caminhos para Mac/Linux (ajuste se necessário)
    DEV_TESSERACT_PATH = "/usr/local/bin/tesseract" 
    DEV_TESSDATA_PATH = "/usr/local/share/tessdata"


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

# --- CONFIGURAÇÃO DO TESSERACT (VERSÃO CORRIGIDA) ---
def setup_tesseract():
    """
    Define o caminho para o executável do Tesseract e seus dados.
    Esta função agora diferencia entre o modo de produção (.exe)
    e o modo de desenvolvimento (.py / pytest).
    """
    tesseract_exe_path = ""
    tessdata_dir = ""
    application_path = ""

    try:
        if getattr(sys, 'frozen', False):
            # --- MODO 1: RODANDO COMO .EXE (PRODUÇÃO) ---
            # O PyInstaller extrai tudo para uma pasta temporária '_MEIPASS'
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
    if platform.system() == "Windows":
        # Windows (Sua máquina local)
        application_path = os.path.dirname(os.path.abspath(__file__))
        tesseract_exe_path = DEV_TESSERACT_PATH
        tessdata_dir = DEV_TESSDATA_PATH
    else:
        # Linux (Robô do GitHub Actions) ou MacOS
        # O `apt-get` instala o Tesseract no /usr/bin/
        # e os dados em /usr/share/tessdata
        application_path = os.path.dirname(os.path.abspath(__file__))
        tesseract_exe_path = "/usr/bin/tesseract"
        tessdata_dir = "/usr/share/tessdata"

        # --- Configuração Global (vale para os dois modos) ---
        
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
        print(f"INFO: Caminho do Tesseract CMD definido para: {tesseract_exe_path}")

        os.environ['TESSDATA_PREFIX'] = tessdata_dir
        print(f"INFO: TESSDATA_PREFIX definido para: {tessdata_dir}")

        # --- Verificação (Opcional) ---
        try:
            version = pytesseract.get_tesseract_version()
            languages = pytesseract.get_languages(config='')
            print(f"INFO: Versão Tesseract detectada: {version}")
            
            if DEFAULT_LANG not in languages:
                messagebox.showwarning("Aviso Tesseract", 
                                    f"O idioma '{DEFAULT_LANG}' (Português) não foi encontrado nos dados do Tesseract!")
            else:
                print(f"INFO: Idioma '{DEFAULT_LANG}' (Português) encontrado em tessdata.")
                
        except pytesseract.TesseractNotFoundError:
            # Este erro não deve acontecer se as validações acima passaram, mas é um seguro
            messagebox.showerror("Erro Crítico Tesseract", 
                               f"Tesseract não foi encontrado ou não é executável no caminho:\n{pytesseract.pytesseract.tesseract_cmd}\n"
                               "O programa não pode continuar.")
            sys.exit(1)
        except Exception as te:
            print(f"AVISO: Erro durante a verificação do Tesseract: {te}")
            messagebox.showwarning("Aviso Tesseract", f"Ocorreu um problema ao verificar a instalação do Tesseract:\n{te}")

    
except Exception as e:
    # Loga o erro para o console (bom para CI) e re-levanta a exceção
    error_message = (f"FALHA CRÍTICA no setup_tesseract:\n{e}\n\n"
                    f"Caminho base detectado: {application_path}\n"
                    f"Tentativa Tesseract CMD: {tesseract_exe_path if 'tesseract_exe_path' in locals() else 'Não definido'}\n"
                    f"Tentativa TESSDATA_PREFIX: {tessdata_dir if 'tessdata_dir' in locals() else 'Não definido'}\n")
    print(error_message) # Imprime o erro no log do CI
    raise e # Re-levanta a exceção para o pytest ver