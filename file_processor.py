# -*- coding: utf-8 -*-
"""
file_processor.py

Contém a lógica para manipular arquivos (PDFs, Imagens).
É responsável por:
1. Abrir arquivos.
2. Chamar o pré-processamento de imagem (OpenCV).
3. Orquestrar a extração (Modo Digital, Modo 1, Modo 2)
   usando o BoletoParser.
4. Lidar com erros de nível de arquivo e OCR.
"""

import os
import fitz # PyMuPDF
import cv2 # OpenCV
import numpy as np
import pytesseract
from PIL import Image

# Importações de nossos módulos
from boleto_data import BoletoData
from extraction_logic import BoletoParser, ExtractionError, OCRError, LayoutNaoReconhecidoError
from config import DEFAULT_LANG

# --- FUNÇÃO DE PRÉ-PROCESSAMENTO DE IMAGEM (V2.1 - CORRIGIDO) ---
def preprocessar_imagem_para_ocr(pil_image: Image) -> Image:
    """
    Aplica técnicas de pré-processamento na imagem para melhorar a qualidade do OCR.
    Recebe uma imagem PIL e retorna uma imagem PIL processada.
    """
    # Converte a imagem PIL para o formato OpenCV (NumPy array BGR)
    open_cv_image = np.array(pil_image)
    if len(open_cv_image.shape) == 2:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_GRAY2BGR)
    elif open_cv_image.shape[2] == 4:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGBA2BGR)
    else:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)

    gray_image = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
    (thresh, binary_image) = cv2.threshold(gray_image, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    scale_percent = 200
    width = int(binary_image.shape[1] * scale_percent / 100)
    height = int(binary_image.shape[0] * scale_percent / 100)
    dim = (width, height)
    resized_image = cv2.resize(binary_image, dim, interpolation = cv2.INTER_LINEAR)

    final_image_pil = Image.fromarray(resized_image)
    return final_image_pil

# --- Funções de Processamento de Arquivos ---

def processar_pdf(caminho_pdf: str, parser: BoletoParser) -> BoletoData:
    """ 
    Processa um arquivo PDF. Tenta extrair texto digital, se falhar, usa OCR.
    Agora levanta exceções em caso de falha.
    """
    nome_arquivo = os.path.basename(caminho_pdf)
    doc = None
    try:
        doc = fitz.open(caminho_pdf)
        texto_digital_completo = ""

        # Tenta extrair texto diretamente do PDF
        for page in doc:
            texto_digital_completo += page.get_text("text")

        # Se encontrou texto digital razoável...
        if texto_digital_completo.strip() and len(texto_digital_completo.strip()) > 50:
            print(f"--- DEBUG (V21.0): Usando Modo Digital para {nome_arquivo} ---")
            # Tenta extrair dados usando apenas o Modo 1 (Regex) no texto digital
            dados_pagina = parser.parse_modo1_regex(texto_digital_completo, f"{nome_arquivo} (Digital)")

            # Se encontrou os campos principais, considera sucesso e não faz OCR
            if all(v != 'Não encontrado' for k, v in dataclasses.asdict(dados_pagina).items() if k in ['vencimento', 'beneficiario', 'valor_documento']):
                print(f"--- DEBUG (V21.0): Modo Digital extraiu todos os dados. Concluído.")
                doc.close()
                return dados_pagina

        # --- Fallback para OCR ---
        print(f"--- DEBUG (V21.0): Usando Modo OCR para {nome_arquivo} (Digital pode ter falhado) ---")
        doc.close() # Fecha e reabre para garantir (pode não ser necessário, mas seguro)
        doc = fitz.open(caminho_pdf)
        
        texto_completo_ocr = ""
        img_processada_para_modo2 = None
        dados_finais = None

        # Processa apenas a primeira página
        if len(doc) > 0:
            page = doc[0]
            try:
                pix = page.get_pixmap(dpi=300)
                samples = pix.samples
                mode = "RGB"
                if pix.alpha: mode = "RGBA"
                img = Image.frombytes(mode, [pix.width, pix.height], samples)
                if img.mode == 'RGBA': img = img.convert('RGB')

                img_processada = preprocessar_imagem_para_ocr(img)
                img_processada_para_modo2 = img_processada

                # --- Executa o OCR (Tesseract) na imagem processada ---
                texto_ocr_pagina = pytesseract.image_to_string(img_processada, lang=DEFAULT_LANG)
                texto_completo_ocr = texto_ocr_pagina
            except Exception as page_e:
                print(f"--- ERRO (V21.0): Erro ao processar página do PDF para OCR: {page_e} ---")
                raise OCRError(f"{nome_arquivo}: Erro no OCR da página: {page_e}") from page_e

        doc.close() # Fecha o PDF

        if texto_completo_ocr.strip():
            # --- TENTATIVA 1 com OCR (MODO 1 - REGEX) ---
            dados_finais = parser.parse_modo1_regex(texto_completo_ocr, f"{nome_arquivo} (OCR)")

            # --- TENTATIVA 2 com OCR (MODO 2 - POSICIONAL) ---
            # O Modo 2 agora atualiza o objeto BoletoData diretamente
            dados_finais = parser.parse_modo2_posicional(img_processada_para_modo2, dados_finais)
            
            return dados_finais
        
        # Se o OCR não retornou nada
        raise LayoutNaoReconhecidoError(f"{nome_arquivo}: O OCR não retornou texto.")

    except Exception as e:
        if 'doc' in locals() and doc: doc.close()
        # Se já for uma das nossas exceções, apenas a repassa
        if isinstance(e, ExtractionError):
            raise e
        # Se for uma exceção genérica, a encapsula
        raise ExtractionError(f"{nome_arquivo}: {str(e)}") from e


def extrair_dados_da_imagem(caminho_imagem: str, parser: BoletoParser) -> BoletoData:
    """ 
    Processa um arquivo de imagem (PNG, JPG, etc.). Usa OCR diretamente.
    Agora levanta exceções em caso de falha.
    """
    nome_arquivo = os.path.basename(caminho_imagem)
    try:
        img_original = Image.open(caminho_imagem)
        if img_original.mode != 'RGB': img_original = img_original.convert('RGB')

        img_processada = preprocessar_imagem_para_ocr(img_original)

        # --- TENTATIVA 1 (MODO 1 - REGEX) ---
        texto_extraido = pytesseract.image_to_string(img_processada, lang=DEFAULT_LANG)
        if not texto_extraido.strip():
             raise LayoutNaoReconhecidoError(f"{nome_arquivo}: O OCR não retornou texto.")
            
        dados_da_imagem = parser.parse_modo1_regex(texto_extraido.strip(), nome_arquivo)

        # --- TENTATIVA 2 (MODO 2 - POSICIONAL) ---
        # O Modo 2 agora atualiza o objeto BoletoData diretamente
        dados_da_imagem = parser.parse_modo2_posicional(img_processada, dados_da_imagem)

        return dados_da_imagem

    except Exception as e:
        if isinstance(e, ExtractionError):
            raise e
        raise ExtractionError(f"{nome_arquivo}: {str(e)}") from e