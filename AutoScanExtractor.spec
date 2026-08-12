# -*- mode: python ; coding: utf-8 -*-
"""
AutoScanExtractor.spec

Arquivo de build do PyInstaller.

Estava documentado no README e listado na estrutura do projeto, mas nunca foi
versionado: o ``.gitignore`` tinha uma regra ``*.spec`` que o excluía. Quem
clonasse o repositório não conseguia gerar o executável — justamente o
principal entregável do projeto.

Uso:

    pyinstaller AutoScanExtractor.spec

Para embutir o Tesseract no executável (deixando o .exe autossuficiente),
aponte a variável de ambiente ``TESSERACT_DIR`` para a pasta de instalação
antes de compilar::

    set TESSERACT_DIR=C:\\Program Files\\Tesseract-OCR
    pyinstaller AutoScanExtractor.spec

Sem essa variável o executável é gerado assim mesmo, porém exigindo o
Tesseract instalado na máquina de destino.
"""

import glob
import os

#: Idiomas embutidos. Português é o essencial; os outros ajudam o Tesseract a
#: detectar orientação e a lidar com documentos mistos.
IDIOMAS_EMBUTIDOS = ("por", "eng", "osd")

binaries = []
datas = [("assets", "assets")]

tesseract_dir = os.environ.get("TESSERACT_DIR", "").strip()
if tesseract_dir and os.path.isdir(tesseract_dir):
    executavel = os.path.join(tesseract_dir, "tesseract.exe")
    if os.path.isfile(executavel):
        binaries.append((executavel, "."))

    # O tesseract.exe depende das DLLs que vivem ao lado dele.
    for dll in glob.glob(os.path.join(tesseract_dir, "*.dll")):
        binaries.append((dll, "."))

    tessdata = os.path.join(tesseract_dir, "tessdata")
    for idioma in IDIOMAS_EMBUTIDOS:
        arquivo = os.path.join(tessdata, f"{idioma}.traineddata")
        if os.path.isfile(arquivo):
            datas.append((arquivo, "tessdata"))

    print(f"[spec] Tesseract embutido a partir de {tesseract_dir}")
else:
    print("[spec] TESSERACT_DIR não definido: o executável exigirá Tesseract instalado.")


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Módulos pesados que o projeto não usa; excluí-los reduz bastante o .exe.
    excludes=["matplotlib", "scipy", "notebook", "IPython", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AutoScanExtractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Console habilitado para que o mesmo executável sirva à linha de comando
    # (`AutoScanExtractor.exe extrair -e ... -s ...`). Ao ser aberto com dois
    # cliques, sem argumentos, o programa esconde o próprio console antes de
    # abrir a janela — ver `ocultar_console_proprio` em config.py.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/meu_novo_icone.ico",
)
