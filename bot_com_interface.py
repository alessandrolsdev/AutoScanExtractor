import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import os
import pytesseract # <--- Tesseract
import pandas as pd
from PIL import Image
import re
import threading
import sys
import fitz
import cv2
import numpy as np

# --- FUNÇÃO HELPER PARA ENCONTRAR ARQUIVOS NO .EXE ---
def resource_path(relative_path):
    """ Pega o caminho absoluto para o recurso, funciona em dev e no PyInstaller """
    try:
        # PyInstaller cria uma pasta temp e guarda o caminho em _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- CONFIGURAÇÃO (MODO DE TESTE - TESSERACT) ---
try:
    # Caminho fixo para o executável do Tesseract (ajuste se necessário)
    tesseract_exe_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
    # Caminho fixo para a pasta de dados do Tesseract (ajuste se necessário)
    tessdata_path = r'C:\Program Files\Tesseract-OCR\tessdata'
    os.environ['TESSDATA_PREFIX'] = tessdata_path
except Exception as e:
    messagebox.showerror("Erro de Inicialização", f"Não foi possível configurar o Tesseract OCR:\n{e}")
    sys.exit(1)

# --- FUNÇÃO DE PRÉ-PROCESSAMENTO DE IMAGEM (V2.1 - CORRIGIDO) ---
def preprocessar_imagem_para_ocr(pil_image):
    open_cv_image = np.array(pil_image)
    if len(open_cv_image.shape) == 2:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_GRAY2BGR)
    elif open_cv_image.shape[2] == 4:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGBA2BGR)
    else:
        open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)

    gray_image = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
    (thresh, binary_image) = cv2.threshold(gray_image, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    width = int(binary_image.shape[1] * 2)
    height = int(binary_image.shape[0] * 2)
    dim = (width, height)
    resized_image = cv2.resize(binary_image, dim, interpolation = cv2.INTER_LINEAR)
    final_image_pil = Image.fromarray(resized_image) # Retorna PIL para Pytesseract
    return final_image_pil

# --- FUNÇÃO DE VALIDAÇÃO (V5.1 - Simples e Eficaz) ---
def is_valid_candidate(text):
    """Verificação básica se o texto não é obviamente lixo (V5.1)"""
    if not text: return False
    text = text.strip()
    if len(text) <= 3:
        return False
    
    # Adicionamos "VALOR" à lista de lixo para evitar que o Beneficiário pegue "(=) VALOR DOCUMENTO"
    lixo_sem_valor = ["NOSSO NÚMERO", "AGÊNCIA", "CÓDIGO BENEFICIÁRIO", "VENCIMENTO", "RECIBO DO PAGADOR", "AUTENTICAÇÃO MECANICA", "VALOR"]
    # Evita pegar só números ou o próprio CNPJ/CPF como nome
    if re.fullmatch(r"[\d\s\.\/\-\,\—]+", text): # Adicionado — e ,
        return False
    if any(k in text.upper() for k in lixo_sem_valor):
        return False
    return True

# --- LÓGICA DE EXTRAÇÃO (V14.5 - Regex Final) ---
# Esta função ainda é usada como a "Tentativa 1" (Modo Rápido)
def parse_boleto_text(texto_extraido, nome_arquivo_origem):
    """
    Pega o texto cru do OCR de um boleto e o nome do arquivo,
    retorna uma lista com um dicionário de dados do boleto (V14.5).
    """
    print(f"\n--- DEBUG (V14.5 - Regex): Iniciando parse para {nome_arquivo_origem} ---") 

    dados_encontrados = {
        'Arquivo_Origem': nome_arquivo_origem,
        'Vencimento': 'Não encontrado',
        'Valor_Documento': 'Não encontrado', 
        'Beneficiário': 'Não encontrado',
        'Pagador': 'Não encontrado',
        'Codigo_Barras': 'Não encontrado'
    }
    texto_trabalho = texto_extraido
    match_codigo = None

    # 1. Regex para Código de Barras
    print("--- DEBUG (V14.5 - Regex): Tentando encontrar Código de Barras...") 
    match_codigo = re.search( r"(\d{5}\.[_O\d]{5}\s+[_O\d]{5}\.[_O\d]{6}\s+[_O\d]{5}\.[_O\d]{6}\s+[_O\d]\s+[_O\d]{14})", texto_trabalho )
    if not match_codigo: match_codigo = re.search( r"([\dO]{9}[\.\s]?[\dO][\s\n]+[\dO]{10}[\.\s]?[\dO][\s\n]+[\dO]{10}[\.\s]?[\dO][\s\n]+[\dO][\s\n]+[\dO]{14})", texto_trabalho, re.IGNORECASE )
    if not match_codigo: match_codigo = re.search( r"([\dO]{5}[^\d\n]?[\dO]{5}[\s\n]+[\dO]{5}[^\d\n]?[\dO]{6}[\s\n]+[\dO]{5}[^\d\n]?[\dO]{6}[\s\n]+[\dO][\s\n]+[\dO]{14})", texto_trabalho, re.IGNORECASE )
    if not match_codigo:
        match_codigo_flex = re.search( r"(\d{5})\D?(\d{5})\D?(\d{5})\D?(\d{6})\D?(\d{5})\D?(\d{6})\D?(\d)\D?(\d{14})", texto_trabalho)
        if match_codigo_flex:
            groups = match_codigo_flex.groups()
            codigo_formatado = f"{groups[0]}.{groups[1]} {groups[2]}.{groups[3]} {groups[4]}.{groups[5]} {groups[6]} {groups[7]}"
            dados_encontrados['Codigo_Barras'] = codigo_formatado
            print(f"--- DEBUG (V14.5 - Regex): Código de Barras encontrado (Flex): {dados_encontrados['Codigo_Barras']}") 

    if match_codigo and dados_encontrados['Codigo_Barras'] == 'Não encontrado': 
        codigo_limpo = re.sub(r"[\s\n]+", " ", match_codigo.group(1))
        dados_encontrados['Codigo_Barras'] = codigo_limpo.replace("O", "0").replace("o", "0").replace("_", "0") # Adiciona _
        print(f"--- DEBUG (V14.5 - Regex): Código de Barras encontrado (Cascata): {dados_encontrados['Codigo_Barras']}") 
    if dados_encontrados['Codigo_Barras'] == 'Não encontrado':
        print("--- DEBUG (V14.5 - Regex): Código de Barras NÃO encontrado.") 

    # 2. Regex para Data de Vencimento (V14.5 - Tolerante a OCR)
    print("--- DEBUG (V14.5 - Regex): Tentando encontrar Vencimento...") 
    match_vencimento = re.search(r"Venciment[o|a|u][\s\n]*([\dO]{2}/[\dO]{2}/[\dO]{4})", texto_trabalho, re.IGNORECASE)
    if match_vencimento:
        vencimento_sujo = match_vencimento.group(1)
        dados_encontrados['Vencimento'] = vencimento_sujo.replace("O", "0") # Limpa 'O' por '0'
        print(f"--- DEBUG (V14.5 - Regex): Vencimento encontrado: {dados_encontrados['Vencimento']}") 
    else:
        print("--- DEBUG (V14.5 - Regex): Vencimento NÃO encontrado.") 

    # 3. Regex para Beneficiário
    print("--- DEBUG (V14.5 - Regex): Tentando encontrar Beneficiário (via Número CNPJ)...") 
    match_linha_cnpj = re.search(r"^\s*(.*?CNPJ\s*\d{2}[\.\s]?\d{3}[\.\s]?\d{3}/\d{4}[\-\s]?\d{2}.*)$", texto_trabalho, re.MULTILINE | re.IGNORECASE)
    beneficiario_encontrado = False
    if match_linha_cnpj:
        print("--- DEBUG (V14.5 - Regex): Encontrou linha com CNPJ.") 
        linha_completa = match_linha_cnpj.group(1).strip()
        match_nome_mesma_linha = re.search(r"^([^\n]+?)\s*CNPJ", linha_completa, re.IGNORECASE)
        if match_nome_mesma_linha and is_valid_candidate(match_nome_mesma_linha.group(1)):
                dados_encontrados['Beneficiário'] = match_nome_mesma_linha.group(1).strip()
                beneficiario_encontrado = True
                print(f"--- DEBUG (V14.5 - Regex): Beneficiário encontrado (mesma linha CNPJ): {dados_encontrados['Beneficiário']}") 
        else:
            print("--- DEBUG (V14.5 - Regex): Não encontrou nome na mesma linha do CNPJ. Tentando linha anterior...") 
            pos_inicio_linha_cnpj = match_linha_cnpj.start()
            texto_antes = texto_trabalho[:pos_inicio_linha_cnpj].strip()
            linhas_antes = texto_antes.split('\n')
            if linhas_antes and linhas_antes[-1].strip():
                linha_anterior = linhas_antes[-1].strip()
                if is_valid_candidate(linha_anterior) :
                        dados_encontrados['Beneficiário'] = linha_anterior
                        beneficiario_encontrado = True
                        print(f"--- DEBUG (V14.5 - Regex): Beneficiário encontrado (linha anterior CNPJ): {dados_encontrados['Beneficiário']}") 
                else:
                        print(f"--- DEBUG (V14.5 - Regex): Candidato (linha anterior CNPJ) REJEITADO pela validação: '{linha_anterior}'") 
    else:
            print("--- DEBUG (V14.5 - Regex): Não encontrou linha com CNPJ.") 

    # --- FALLBACKS V14.5 (Tolerante a OCR) ---
    if not beneficiario_encontrado:
        print("--- DEBUG (V14.5 - Regex): Tentando fallback 1 (Mesma Linha)...") 
        match_empresa = re.search(r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Benefici[á|a|o]rio[^\w\n]*([^\n]+)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        
        if match_empresa:
            nome_bruto = match_empresa.group(1).strip()
            nome_sem_cnpj = re.sub(r'\s*CNPJ.*$', '', nome_bruto, flags=re.IGNORECASE).strip()

            if is_valid_candidate(nome_sem_cnpj):
                dados_encontrados['Beneficiário'] = nome_sem_cnpj
                beneficiario_encontrado = True
                print(f"--- DEBUG (V14.5 - Regex): Beneficiário encontrado (Fallback 1 - Mesma Linha): {dados_encontrados['Beneficiário']}")
            else:
                 print(f"--- DEBUG (V14.5 - Regex): Candidato (Fallback 1) REJEITADO: '{nome_sem_cnpj}'")

    if not beneficiario_encontrado:
        print("--- DEBUG (V14.5 - Regex): Tentando fallback 2 (Próxima Linha)...") 
        match_empresa = re.search(r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Benefici[á|a|o]rio\s*\n\s*([^\n]+)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        
        if match_empresa:
            nome_bruto = match_empresa.group(1).strip()
            if "CNPJ" not in nome_bruto.upper() and is_valid_candidate(nome_bruto):
                dados_encontrados['Beneficiário'] = nome_bruto
                beneficiario_encontrado = True
                print(f"--- DEBUG (V14.5 - Regex): Beneficiário encontrado (Fallback 2 - Próxima Linha): {dados_encontrados['Beneficiário']}")
            else:
                 print(f"--- DEBUG (V14.5 - Regex): Candidato (Fallback 2) REJEITADO: '{nome_bruto}'")
    # --- FIM V14.5 ---

    if not beneficiario_encontrado:
            print("--- DEBUG (V14.5 - Regex): Beneficiário NÃO encontrado após todas as tentativas.") 

    # 4. Regex para Pagador
    print("--- DEBUG (V14.5 - Regex): Tentando encontrar Pagador (via CPF)...") 
    match_cpf = re.search(r"CPF[:\s]*(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?\d{2})", texto_trabalho, re.MULTILINE | re.IGNORECASE)
    pagador_encontrado = False
    if match_cpf:
        print(f"--- DEBUG (V14.5 - Regex): Encontrou padrão numérico CPF: '{match_cpf.group(1)}'") 
        pos_cpf = match_cpf.start()
        inicio_linha_cpf = texto_trabalho.rfind('\n', 0, pos_cpf) + 1
        texto_antes_cpf = texto_trabalho[inicio_linha_cpf:pos_cpf].strip()
        match_pagador_mesma_linha = re.search(r"Pagador:?\s+(.+)", texto_antes_cpf, re.IGNORECASE)
        if match_pagador_mesma_linha and is_valid_candidate(match_pagador_mesma_linha.group(1)):
            dados_encontrados['Pagador'] = match_pagador_mesma_linha.group(1).strip()
            pagador_encontrado = True
            print(f"--- DEBUG (V1An 4.5 - Regex): Pagador encontrado (mesma linha CPF): {dados_encontrados['Pagador']}") 
        else:
                print("--- DEBUG (V14.5 - Regex): Não encontrou Pagador na mesma linha do CPF. Tentando linha anterior...") 
                texto_antes_cpf = texto_trabalho[:pos_cpf].strip()
                linhas_antes = texto_antes_cpf.split('\n')
                if len(linhas_antes) > 0:
                    linha_anterior = linhas_antes[-1].strip()
                    if len(linhas_antes) > 1 and re.search(r"Pagador", linhas_antes[-2], re.IGNORECASE):
                            if is_valid_candidate(linha_anterior):
                                dados_encontrados['Pagador'] = linha_anterior
                                pagador_encontrado = True
                                print(f"--- DEBUG (V14.5 - Regex): Pagador encontrado (linha anterior CPF): {dados_encontrados['Pagador']}") 
                            else: print(f"--- DEBUG (V14.5 - Regex): Candidato (linha anterior CPF) REJEITADO: '{linha_anterior}'") 
                else: print("--- DEBUG (V14.5 - Regex): Não encontrou linha anterior ao CPF.") 
    else:
        print("--- DEBUG (V14.5 - Regex): Não encontrou padrão numérico do CPF.") 
                            
    if not pagador_encontrado:
        print("--- DEBUG (V14.5 - Regex): Tentando fallback do Pagador...") 
        match_pagador = re.search(r"^\s*Pagador:?\s+([^\n]+?)(?=\s*CPF|$)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        if not match_pagador: match_pagador = re.search(r"^\s*Pagador\s*\n\s*([^\n]+?)(?=\s*CPF|$)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        if match_pagador:
                nome_pagador_bruto = match_pagador.group(1).strip()
                if is_valid_candidate(nome_pagador_bruto):
                    dados_encontrados['Pagador'] = nome_pagador_bruto
                    pagador_encontrado = True
                    print(f"--- DEBUG (V1AN 4.5 - Regex): Pagador encontrado (fallback): {dados_encontrados['Pagador']}") 
                else: print(f"--- DEBUG (V14.5 - Regex): Candidato (fallback) REJEITADO: '{nome_pagador_bruto}'") 
    
    if dados_encontrados['Pagador'] != 'Não encontrado':
        dados_encontrados['Pagador'] = re.sub(r'\s*-\s*$', '', dados_encontrados['Pagador']).strip()
    if not pagador_encontrado:
        print("--- DEBUG (V14.5 - Regex): Pagador NÃO encontrado após todas as tentativas.") 

    # --- 5. Regex para Valor do Documento (ATUALIZADO V14.5 - Corrige R$) ---
    print("--- DEBUG (V14.5 - Regex): Tentando encontrar Valor do Documento...")
    valor_encontrado = None
    
    regex_valor = r"([ \d\.]*,\d{2})" 
    regex_lixo = r"[^\n\d]*" # Pega lixo como "R$"

    # Tentativa 1: Rótulo e Valor na mesma linha (Ignora R$)
    match_valor = re.search(r"Valor (?:do )?Documento" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
    if match_valor:
        valor_encontrado = match_valor.group(1)
        print("--- DEBUG (V14.5 - Regex): Valor encontrado (T1 - Mesma linha):", valor_encontrado)

    # Tentativa 2: Rótulo "(=) Valor Documento" e valor na linha de baixo (Opcional "do")
    if not valor_encontrado:
        match_valor = re.search(r"=\)\s*Valor\s*(?:do )?Documento\s*\n" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
        if match_valor:
            valor_encontrado = match_valor.group(1)
            print("--- DEBUG (V14.5 - Regex): Valor encontrado (T2 - Fallback = Valor):", valor_encontrado)
            
    # Tentativa 3: Rótulo "Valor (do) Documento" e valor na linha de baixo (mais genérico)
    if not valor_encontrado:
        match_valor = re.search(r"Valor (?:do )?Documento\s*\n" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
        if match_valor:
            valor_encontrado = match_valor.group(1)
            print("--- DEBUG (V14.5 - Regex): Valor encontrado (T3 - Rótulo/Valor linhas dif):", valor_encontrado)

    # Tentativa 4: Rótulo "Valor Cobrado" (comum em faturas)
    if not valor_encontrado:
        match_valor = re.search(r"Valor Cobrado" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
        if match_valor:
            valor_encontrado = match_valor.group(1)
            print("--- DEBUG (V14.5 - Regex): Valor encontrado (T4 - Valor Cobrado):", valor_encontrado)
            
    # Tentativa 5: Rótulo "Valor Cobrado" na linha de baixo
    if not valor_encontrado:
        match_valor = re.search(r"Valor Cobrado\s*\n" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
        if match_valor:
            valor_encontrado = match_valor.group(1)
            print("--- DEBUG (V14.5 - Regex): Valor encontrado (T5 - Valor Cobrado linha dif):", valor_encontrado)

    # Tentativa 6: Apenas "Valor" e o valor (pode ser arriscado, mas é um fallback)
    if not valor_encontrado:
        match_valor = re.search(r"^\s*Valor\s+" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE | re.MULTILINE)
        if match_valor:
            valor_encontrado = match_valor.group(1)
            print("--- DEBUG (V14.5 - Regex): Valor encontrado (T6 - Apenas Valor):", valor_encontrado)

    if valor_encontrado:
        valor_limpo = valor_encontrado.strip()
        valor_limpo = re.sub(r'\s', '', valor_limpo)
        dados_encontrados['Valor_Documento'] = valor_limpo
        print(f"--- DEBUG (V14.5 - Regex): Valor final limpo: {valor_limpo}")
    else:
        print("--- DEBUG (V14.5 - Regex): Valor NÃO encontrado após todas as tentativas.")
    # --- FIM V14.5 ---

    print(f"--- DEBUG (V14.5 - Regex): Parse finalizado para {nome_arquivo_origem}. Resultado: {dados_encontrados} ---") 

    if any(v != 'Não encontrado' for k, v in dados_encontrados.items() if k != 'Arquivo_Origem'):
        return [dados_encontrados]
    else:
        print(f"--- DEBUG (V14.5 - Regex): Nenhum dado útil encontrado para {nome_arquivo_origem}. Descartando.") 
        return []

# --- INÍCIO: LÓGICA HÍBRIDA POSICIONAL (V15.0) ---

def _find_keyword_pos(df, keyword_list):
    """Encontra a primeira ocorrência de qualquer palavra-chave no DataFrame e retorna sua linha."""
    for keyword in keyword_list:
        # Usamos regex com \b (word boundary) para não pegar "VENCIMENTO" dentro de outra palavra
        # E case=False para ignorar maiúsculas/minúsculas
        try:
            match = df[df['text'].str.contains(r'\b' + re.escape(keyword) + r'\b', case=False, na=False, flags=re.IGNORECASE)]
            if not match.empty:
                return match.iloc[0]
        except Exception as e:
            print(f"--- ERRO (V15.0 - Posicional): Erro no regex _find_keyword_pos: {e} ---")
            continue
    return None

def _find_data_nearby(df, keyword_row, y_tolerance_factor=1.0, x_limit=300, x_min_dist=0, direction='right'):
    """Encontra texto próximo a uma linha de keyword no DataFrame."""
    kx, ky, kw, kh = keyword_row['left'], keyword_row['top'], keyword_row['width'], keyword_row['height']
    ky_mid = ky + kh / 2
    
    nearby_words = []
    
    for i, row in df.iterrows():
        if row.name == keyword_row.name: continue # Não corresponder a si mesmo
        if pd.isna(row['text']) or not str(row['text']).strip(): continue # Ignorar texto vazio

        px, py, pw, ph = row['left'], row['top'], row['width'], row['height']
        py_mid = py + ph / 2
        
        if direction == 'right':
            # Está na mesma "linha" (tolerância Y)
            if abs(py_mid - ky_mid) < (kh * y_tolerance_factor):
                # Está à direita da palavra-chave (com distância mínima)
                if (px > (kx + kw + x_min_dist)) and (px < (kx + x_limit)):
                    nearby_words.append(row)
                    
        elif direction == 'below':
            # Está abaixo da palavra-chave
            y_distance = py - (ky + kh)
            # Está na mesma "coluna" (centros X próximos)
            x_center_diff = abs((px + pw / 2) - (kx + kw / 2))
            
            if y_distance > 0 and y_distance < (kh * 3) and x_center_diff < x_limit:
                 nearby_words.append(row)

    # Ordena por Posição (Y e depois X) para remontar a frase
    nearby_words.sort(key=lambda r: (r['top'], r['left']))
    return " ".join([str(w['text']) for w in nearby_words])

def _buscar_dados_posicionais(dados_df, campos_faltantes, dados_encontrados):
    """
    Tenta encontrar os campos_faltantes usando o DataFrame posicional do Tesseract.
    Modifica o dicionário 'dados_encontrados' no local.
    """
    
    print(f"--- DEBUG (V15.0 - Posicional): Buscando campos: {campos_faltantes} ---")
    
    if 'Vencimento' in campos_faltantes:
        keyword_row = _find_keyword_pos(dados_df, ['VENCIMENTO', 'VENCIMENT', 'VENCIM', 'VENC', 'VENCIMENTO'])
        if keyword_row is not None:
            # 1. Tenta à direita
            texto_proximo = _find_data_nearby(dados_df, keyword_row, direction='right', x_limit=300, y_tolerance_factor=1.0)
            match = re.search(r'([\dO]{2}/[\dO]{2}/[\dO]{4})', texto_proximo)
            if match:
                dados_encontrados['Vencimento'] = match.group(1).replace('O','0')
            else:
                # 2. Tenta abaixo
                texto_proximo = _find_data_nearby(dados_df, keyword_row, direction='below', x_limit=150, y_tolerance_factor=1.0)
                match = re.search(r'([\dO]{2}/[\dO]{2}/[\dO]{4})', texto_proximo)
                if match:
                    dados_encontrados['Vencimento'] = match.group(1).replace('O','0')
            
            if dados_encontrados['Vencimento'] != 'Não encontrado':
                print(f"--- DEBUG (V15.0 - Posicional): Vencimento encontrado: {dados_encontrados['Vencimento']} ---")

    if 'Beneficiário' in campos_faltantes:
        keyword_row = _find_keyword_pos(dados_df, ['BENEFICIÁRIO', 'BENEFICIARIO', 'BENEFICI'])
        if keyword_row is not None:
            # 1. Tenta à direita (para nomes longos)
            texto_proximo = _find_data_nearby(dados_df, keyword_row, direction='right', x_limit=800, y_tolerance_factor=1.0, x_min_dist=5)
            if is_valid_candidate(texto_proximo):
                dados_encontrados['Beneficiário'] = texto_proximo
            else:
                # 2. Tenta abaixo
                texto_proximo = _find_data_nearby(dados_df, keyword_row, direction='below', x_limit=400, y_tolerance_factor=1.0)
                if is_valid_candidate(texto_proximo):
                    dados_encontrados['Beneficiário'] = texto_proximo
            
            if dados_encontrados['Beneficiário'] != 'Não encontrado':
                 print(f"--- DEBUG (V15.0 - Posicional): Beneficiário encontrado: {dados_encontrados['Beneficiário']} ---")

    if 'Valor_Documento' in campos_faltantes:
        # "Valor Documento" é difícil porque "Valor" é comum. Vamos procurar "Documento" perto de "Valor"
        keyword_row = _find_keyword_pos(dados_df, ['DOCUMENTO', 'DOCUM', 'DOCUMENT'])
        if keyword_row is not None:
             # 1. Tenta à direita
            texto_proximo = _find_data_nearby(dados_df, keyword_row, direction='right', x_limit=300, y_tolerance_factor=1.0)
            match = re.search(r'([ \d\.]*,\d{2})', texto_proximo)
            if match:
                dados_encontrados['Valor_Documento'] = re.sub(r'\s', '', match.group(1))
            else:
                # 2. Tenta abaixo
                texto_proximo = _find_data_nearby(dados_df, keyword_row, direction='below', x_limit=150, y_tolerance_factor=1.0)
                match = re.search(r'([ \d\.]*,\d{2})', texto_proximo)
                if match:
                    dados_encontrados['Valor_Documento'] = re.sub(r'\s', '', match.group(1))
            
            if dados_encontrados['Valor_Documento'] != 'Não encontrado':
                print(f"--- DEBUG (V15.0 - Posicional): Valor do Documento encontrado: {dados_encontrados['Valor_Documento']} ---")

    return # O dicionário 'dados_encontrados' foi modificado


def processar_imagem_hibrido(img_processada, nome_arquivo):
    """
    (V15.0) Tenta o Modo Rápido (Regex) primeiro, e depois o Modo Posicional para os campos faltantes.
    Retorna (lista_de_dados, erro_str)
    """
    try:
        # --- Tentativa 1: Modo Rápido (Regex V14.5) ---
        texto_extraido_full = pytesseract.image_to_string(img_processada, lang='por')
        dados_encontrados_lista = parse_boleto_text(texto_extraido_full, nome_arquivo)
        
        # Se o Regex não encontrou NADA, ou nenhum dado útil, não há o que fazer.
        if not dados_encontrados_lista:
            print(f"--- DEBUG (V15.0 - Híbrido): Modo Regex falhou em encontrar dados básicos para {nome_arquivo}. ---")
            return [], None
            
        dados = dados_encontrados_lista[0]
        
        # --- Verificação: O que falta? ---
        campos_faltantes = []
        if dados['Vencimento'] == 'Não encontrado': campos_faltantes.append('Vencimento')
        if dados['Beneficiário'] == 'Não encontrado': campos_faltantes.append('Beneficiário')
        if dados['Valor_Documento'] == 'Não encontrado': campos_faltantes.append('Valor_Documento')
        
        # Se não falta nada, ótimo!
        if not campos_faltantes:
            print(f"--- DEBUG (V15.0 - Híbrido): Modo Regex foi 100% suficiente para {nome_arquivo}. ---")
            return [dados], None
            
        # --- Tentativa 2: Modo Posicional (para campos faltantes) ---
        print(f"--- DEBUG (V15.0 - Híbrido): Ativando Modo Posicional para: {campos_faltantes} ---")
        
        # Executa o OCR posicional (caro, por isso é a Tentativa 2)
        dados_df = pytesseract.image_to_data(img_processada, lang='por', output_type=pytesseract.Output.DATAFRAME)
        
        # Limpa o DataFrame
        dados_df = dados_df[dados_df['conf'] > 30] # Remove lixo de baixa confiança
        dados_df.dropna(subset=['text'], inplace=True) # Remove linhas sem texto
        dados_df['text'] = dados_df['text'].astype(str) # Garante que texto é string

        if dados_df.empty:
             print(f"--- DEBUG (V15.0 - Híbrido): Modo Posicional não encontrou texto confiável. ---")
             return [dados], None # Retorna o que o Regex pegou

        # Chama a função que busca e modifica o dicionário 'dados'
        _buscar_dados_posicionais(dados_df, campos_faltantes, dados)
        
        print(f"--- DEBUG (V15.0 - Híbrido): Processamento híbrido finalizado para {nome_arquivo}. ---")
        return [dados], None

    except Exception as e:
        import traceback
        print(f"--- ERRO (V15.0 - Híbrido): Erro crítico no processamento híbrido: {e} ---")
        print(traceback.format_exc())
        return [], f"Erro no processamento híbrido: {e}"

# --- FIM: LÓGICA HÍBRIDA POSICIONAL (V15.0) ---


def processar_pdf(caminho_pdf):
    dados_do_pdf = []
    nome_arquivo = os.path.basename(caminho_pdf)
    texto_extraido = ""
    try:
        doc = fitz.open(caminho_pdf)
        texto_digital_completo = ""
        # Tenta extrair texto digital PRIMEIRO
        for page in doc:
            texto_digital_completo += page.get_text("text")

        dados_digital = []
        if texto_digital_completo.strip() and len(texto_digital_completo.strip()) > 50:
            print(f"--- DEBUG (V15.0): Usando Modo Digital para {nome_arquivo} ---")
            # Usamos o parse V14.5, que é rápido
            dados_pagina = parse_boleto_text(texto_digital_completo, f"{nome_arquivo} (Digital)")
            if dados_pagina: dados_digital.extend(dados_pagina)

        # Verifica se o modo digital encontrou dados SUFICIENTES
        # (Se o digital encontrou, não precisamos do OCR Híbrido)
        if any(d['Pagador'] != 'Não encontrado' and d['Beneficiário'] != 'Não encontrado' and d['Valor_Documento'] != 'Não encontrado' for d in dados_digital):
            print(f"--- DEBUG (V15.0): Modo Digital extraiu todos os dados-chave. Usando resultado digital.")
            doc.close()
            return dados_digital, None
        else:
             if dados_digital:
                 print(f"--- DEBUG (V15.0): Modo Digital não extraiu todos os dados, tentando OCR Híbrido para {nome_arquivo} ---")
                 # Pega o que o digital encontrou, mas vai tentar o OCR mesmo assim
                 dados_do_pdf.extend(dados_digital)
             else:
                 print(f"--- DEBUG (V15.0): Modo Digital não extraiu dados, tentando OCR Híbrido para {nome_arquivo} ---")
            
             # Limpa a lista se o modo digital não foi bom, para não duplicar
             dados_do_pdf = []


        # Se não achou texto digital útil, parte para OCR HíBRIDO página a página
        print(f"--- DEBUG (V15.0): Usando Modo OCR Híbrido para {nome_arquivo} ---")
        doc.close() # Fecha e reabre para segurança
        doc = fitz.open(caminho_pdf)
        
        for num_pagina, page in enumerate(doc):
            try:
                pix = page.get_pixmap(dpi=300)
                samples = pix.samples
                mode = "RGB"
                if pix.alpha: mode = "RGBA"
                img = Image.frombytes(mode, [pix.width, pix.height], samples)
                if img.mode == 'RGBA': img = img.convert('RGB')

                img_processada = preprocessar_imagem_para_ocr(img)
                
                # --- CHAMADA V15.0 ---
                # Chama a nova função híbrida em vez do parse simples
                dados_pagina_ocr, erro_hibrido = processar_imagem_hibrido(img_processada, f"{nome_arquivo} (OCR Pag {num_pagina+1})")
                
                if erro_hibrido:
                     print(f"--- ERRO (V15.0): Erro ao processar página {num_pagina+1} (Híbrido): {erro_hibrido} ---")
                     continue
                if dados_pagina_ocr: 
                    dados_do_pdf.extend(dados_pagina_ocr)
                    
            except Exception as page_e:
                print(f"--- ERRO (V15.0): Erro ao renderizar página {num_pagina+1}: {page_e} ---")
                continue
                
        doc.close()
        return dados_do_pdf, None
        
    except Exception as e:
        try:
            if 'doc' in locals() and doc: doc.close()
        except: pass
        return [], f"{nome_arquivo}: {str(e)}"

def extrair_dados_da_imagem(caminho_imagem):
    try:
        nome_arquivo = os.path.basename(caminho_imagem)
        img_original = Image.open(caminho_imagem)
        if img_original.mode != 'RGB': img_original = img_original.convert('RGB')
        
        img_processada = preprocessar_imagem_para_ocr(img_original)
        
        # --- CHAMADA V1S.0 ---
        # Chama a nova função híbrida
        dados_da_imagem, erro_hibrido = processar_imagem_hibrido(img_processada, nome_arquivo)
        
        if erro_hibrido:
            return [], erro_hibrido
        if dados_da_imagem: 
            return dados_da_imagem, None
        else: 
            return [], None
            
    except Exception as e: return [], str(e)

# --- CLASSE DA APLICAÇÃO (GUI) ---
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Extrator V15.0 (Modo Híbrido)") # <--- Título V15.0
        self.root.geometry("600x550") # Altura para barra de progresso e botões
        
        self.arquivos_para_processar = [] # Lista de arquivos de ENTRADA
        self.output_filepath = "" 	  # Caminho do arquivo de SAÍDA
        self.cancel_processing = False    # Flag de cancelamento (V14.0)

        self.lbl_title = tk.Label(root, text="AutoScanExtractor", font=("Helvetica", 16, "bold"))
        self.lbl_title.pack(pady=10)

        self.frame_controles = tk.Frame(root, padx=10, pady=10)
        self.frame_controles.pack(fill=tk.X)

        # --- Passo 1: Seleção de Entrada (V12.0) ---
        self.lbl_passo1 = tk.Label(self.frame_controles, text="Passo 1: Selecione os arquivos de entrada", font=("Helvetica", 10, "bold"))
        self.lbl_passo1.pack(anchor="w")
        
        self.btn_selecionar_entrada = tk.Button(self.frame_controles, text="Selecionar Arquivos ou Pasta", command=self.selecionar_entrada)
        self.btn_selecionar_entrada.pack(fill=tk.X, pady=5)
        
        self.lbl_input = tk.Label(self.frame_controles, text="Nenhum arquivo/pasta selecionado.", bg="white", relief="sunken", anchor="w", padx=5, height=2, wraplength=550, justify=tk.LEFT)
        self.lbl_input.pack(fill=tk.X, pady=(0, 10))

        # --- Passo 2: Seleção de Saída (V12.0) ---
        self.lbl_passo2 = tk.Label(self.frame_controles, text="Passo 2: Defina a planilha de saída (será atualizada se já existir)", font=("Helvetica", 10, "bold"))
        self.lbl_passo2.pack(anchor="w")
        
        self.btn_selecionar_saida = tk.Button(self.frame_controles, text="Definir Local da Planilha (.xlsx)", command=self.selecionar_planilha_saida)
        self.btn_selecionar_saida.pack(fill=tk.X, pady=5)

        self.lbl_output = tk.Label(self.frame_controles, text="Nenhuma planilha de saída definida.", bg="white", relief="sunken", anchor="w", padx=5, height=2, wraplength=550, justify=tk.LEFT)
        self.lbl_output.pack(fill=tk.X, pady=(0, 10))

        # --- Passo 3: Iniciar (V14.0 - Botão Cancelar) ---
        self.btn_iniciar = tk.Button(self.frame_controles, text="3. Iniciar Processamento", command=self.iniciar_processamento, state="disabled", bg="lightgray")
        self.btn_iniciar.pack(fill=tk.X, pady=10)

        # --- Barra de Progresso (V13.0) ---
        self.progress_bar = ttk.Progressbar(self.frame_controles, orient="horizontal", length=100, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=5, side=tk.BOTTOM)

        # --- Log ---
        self.frame_log = tk.Frame(root, padx=10, pady=0) # Reduzido pady
        self.frame_log.pack(fill=tk.BOTH, expand=True)

        self.lbl_log = tk.Label(self.frame_log, text="Log de Atividades:", font=("Helvetica", 10, "bold"))
        self.lbl_log.pack(anchor="w")

        self.log_area = scrolledtext.ScrolledText(self.frame_log, height=6, state="disabled")
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # --- Frame para botões de resultado (V13.0) ---
        self.frame_resultados = tk.Frame(root, padx=10, pady=5)
        self.frame_resultados.pack(fill=tk.X)
        
        self.btn_abrir_planilha = tk.Button(self.frame_resultados, text="Abrir Planilha", command=self.abrir_planilha, state="disabled")
        self.btn_abrir_pasta = tk.Button(self.frame_resultados, text="Abrir Pasta de Saída", command=self.abrir_pasta, state="disabled")
        
        
    def log(self, message):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")
        self.root.update_idletasks()

    def verificar_estado_iniciar(self):
        """Habilita o botão 'Iniciar' apenas se a entrada E a saída estiverem prontas."""
        if self.arquivos_para_processar and self.output_filepath:
            self.btn_iniciar.config(state="normal", bg="lawn green")
            self.log("Tudo pronto! Clique em 'Iniciar Processamento'.")
        else:
            self.btn_iniciar.config(state="disabled", bg="lightgray")

    def selecionar_entrada(self):
        """ (V12.0) Pergunta por arquivos, se cancelar, pergunta por pasta."""
        tipos_arquivo = [
            ("Arquivos Suportados", "*.pdf *.png *.jpg *.jpeg *.tiff *.bmp *.gif"),
            ("Todos os Arquivos", "*.*")
        ]
        arquivos = filedialog.askopenfilenames(title="Selecione um ou mais arquivos (ou Cancele para selecionar uma pasta)", filetypes=tipos_arquivo)
        
        if arquivos:
             self.arquivos_para_processar = list(arquivos)
             self.lbl_input.config(text=f"{len(self.arquivos_para_processar)} arquivo(s) selecionado(s).")
             self.log(f"{len(self.arquivos_para_processar)} arquivo(s) selecionado(s).")
             for f in self.arquivos_para_processar:
                 self.log(f"  > {os.path.basename(f)}")
             self.verificar_estado_iniciar()
             return

        # Se o usuário cancelou a seleção de arquivos, pergunta sobre a pasta
        if messagebox.askyesno("Selecionar Pasta?", "Nenhum arquivo selecionado. Você gostaria de selecionar uma pasta inteira?"):
            self.selecionar_pasta()
        else:
            self.log("Seleção de entrada cancelada.")
            
    def selecionar_pasta(self):
        """ (V12.0) Chamado por selecionar_entrada """
        caminho = filedialog.askdirectory(title="Selecione a pasta onde estão os arquivos")
        if not caminho:
            return

        self.arquivos_para_processar = []
        formatos_suportados = ('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif', '.pdf')
        
        try:
            # Varre a pasta e coleta os arquivos válidos
            for nome_arquivo in os.listdir(caminho):
                if nome_arquivo.lower().endswith(formatos_suportados) and not nome_arquivo.startswith('~$'):
                    self.arquivos_para_processar.append(os.path.join(caminho, nome_arquivo))
            
            if not self.arquivos_para_processar:
                self.lbl_input.config(text=f"Nenhum arquivo compatível encontrado em:\n{caminho}")
                self.log(f"AVISO: Nenhum arquivo compatível (.pdf, .png, .jpg...) encontrado na pasta selecionada.")
            else:
                self.lbl_input.config(text=f"Pronto para processar {len(self.arquivos_para_processar)} arquivos da pasta:\n{caminho}")
                self.log(f"Pasta selecionada: {caminho} ({len(self.arquivos_para_processar)} arquivos encontrados)")
            
            self.verificar_estado_iniciar()
            
        except Exception as e:
            messagebox.showerror("Erro ao Ler Pasta", f"Não foi possível ler a pasta selecionada:\n{e}")
            self.log(f"ERRO: Falha ao ler pasta {caminho}: {e}")

    def selecionar_planilha_saida(self):
        """Abre um diálogo para SALVAR o arquivo .xlsx"""
        caminho_saida = filedialog.asksaveasfilename(
            title="Salvar planilha como...",
            defaultextension=".xlsx",
            filetypes=[("Planilha Excel", "*.xlsx")]
        )
        
        if not caminho_saida: # Usuário cancelou
            return
            
        self.output_filepath = caminho_saida
        self.lbl_output.config(text=f"Planilha será salva em:\n{self.output_filepath}")
        self.log(f"Planilha de saída definida para: {self.output_filepath}")
        
        self.verificar_estado_iniciar()

    # --- Funções de Ação (V13.0) ---
    def abrir_planilha(self):
        if self.output_filepath and os.path.exists(self.output_filepath):
            try:
                os.startfile(self.output_filepath)
                self.log(f"Abrindo planilha: {self.output_filepath}")
            except Exception as e:
                self.log(f"ERRO: Não foi possível abrir a planilha: {e}")
                messagebox.showerror("Erro ao Abrir", f"Não foi possível abrir o arquivo:\n{e}")
        else:
             self.log("ERRO: Caminho da planilha não definido ou arquivo não existe.")

    def abrir_pasta(self):
        if self.output_filepath:
            pasta = os.path.dirname(self.output_filepath)
            try:
                os.startfile(pasta)
                self.log(f"Abrindo pasta: {pasta}")
            except Exception as e:
                self.log(f"ERRO: Não foi possível abrir a pasta: {e}")
                messagebox.showerror("Erro ao Abrir", f"Não foi possível abrir a pasta:\n{e}")
        else:
            self.log("ERRO: Caminho de saída não definido.")
            
    # --- Funções de Processamento (V14.0 - Cancelamento) ---
    def solicitar_cancelamento(self):
        if messagebox.askyesno("Cancelar Processamento?", "Tem certeza que deseja cancelar o processamento?"):
            self.cancel_processing = True
            self.log("CANCELAMENTO SOLICITADO. Aguardando a finalização do arquivo atual...")
            self.btn_iniciar.config(text="Cancelando...", state="disabled")

    def iniciar_processamento(self):
        if not self.arquivos_para_processar or not self.output_filepath:
            messagebox.showwarning("Atenção", "Por favor, selecione os arquivos de entrada E o local da planilha de saída.")
            return
            
        self.btn_selecionar_entrada.config(state="disabled")
        self.btn_selecionar_saida.config(state="disabled") 
        # (V14.0) Mudar para botão de cancelar
        self.btn_iniciar.config(text="Processando... (Cancelar)", bg="tomato", command=self.solicitar_cancelamento, state="normal")
        
        # (V13.0) Limpar botões de resultado
        self.btn_abrir_planilha.pack_forget()
        self.btn_abrir_pasta.pack_forget()
        self.btn_abrir_planilha.config(state="disabled")
        self.btn_abrir_pasta.config(state="disabled")
        
        self.progress_bar.config(value=0) # Resetar barra
        self.cancel_processing = False # Resetar flag

        self.log(f"\n--- INICIANDO PROCESSAMENTO (V15.0 Híbrido) ---")
        
        thread = threading.Thread(target=self.processar_arquivos_thread, args=(self.arquivos_para_processar, self.output_filepath))
        thread.start()

    def processar_arquivos_thread(self, arquivos_para_processar, output_filepath):
        dados_totais = []
        df_existente = pd.DataFrame()
        arquivos_ja_processados = set()
        
        try:
            # (V13.0) Carregar dados existentes e verificar duplicatas
            if os.path.exists(output_filepath):
                try:
                    self.log(f"Encontrada planilha existente. Carregando dados...")
                    df_existente = pd.read_excel(output_filepath)
                    if 'Arquivo_Origem' in df_existente.columns:
                        arquivos_ja_processados = set(df_existente['Arquivo_Origem'].dropna())
                    
                    self.log(f"Carregados {len(df_existente)} registros existentes.")
                    if arquivos_ja_processados:
                        self.log(f"{len(arquivos_ja_processados)} arquivos na planilha serão ignorados se re-selecionados.")
                        
                except Exception as e:
                    self.log(f"AVISO: Não foi possível ler a planilha existente em {output_filepath}. Ela será sobrescrita. Erro: {e}")
                    df_existente = pd.DataFrame() # Reseta o dataframe
                    arquivos_ja_processados = set() # Reseta o set
        
            self.log(f"Processando {len(arquivos_para_processar)} arquivo(s)...")
            
            total_arquivos = len(arquivos_para_processar)
            self.progress_bar.config(maximum=total_arquivos)
            
            for i, caminho_completo in enumerate(arquivos_para_processar): 
                
                # (V14.0) Verificar cancelamento
                if self.cancel_processing:
                    self.log("--- PROCESSAMENTO CANCELADO PELO USUÁRIO ---")
                    self.finalizar_processamento(sucesso=False, cancelado=True)
                    return
                
                self.progress_bar.config(value=i + 1)
                nome_arquivo = os.path.basename(caminho_completo)
                
                # (V13.0) Checagem de duplicatas
                # (Usamos um nome de arquivo "genérico" para checagem, mesmo que o parse adicione (Digital) ou (OCR) depois)
                if nome_arquivo in arquivos_ja_processados or f"{nome_arquivo} (Digital)" in arquivos_ja_processados or f"{nome_arquivo} (OCR)" in arquivos_ja_processados:
                    self.log(f"Ignorando '{nome_arquivo}' (Já processado anteriormente).")
                    continue
                
                dados = []
                erro = None
                
                self.log(f"Processando '{nome_arquivo}' ({i+1}/{total_arquivos})...")
                if nome_arquivo.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
                    # (V15.0) Chama a função de imagem (que agora é híbrida)
                    dados, erro = extrair_dados_da_imagem(caminho_completo)
                elif nome_arquivo.lower().endswith('.pdf'):
                    # (V15.0) Chama a função de PDF (que agora é híbrida)
                    dados, erro = processar_pdf(caminho_completo)
                else:
                    self.log(f"  > Ignorando arquivo não suportado: '{nome_arquivo}'")
                    continue 

                if erro:
                    self.log(f"  > ERRO ao processar '{nome_arquivo}': {erro}")
                elif dados:
                    dados_totais.extend(dados)
                    self.log(f"  > Sucesso! {len(dados)} registro(s) potencial(is) encontrado(s).")
                else:
                    self.log(f"  > Nenhum dado relevante encontrado em '{nome_arquivo}'.")

            # Filtra dados vazios (caso o parse retorne lista vazia)
            dados_finais = [d for d in dados_totais if d and any(v != 'Não encontrado' for k, v in d.items() if k != 'Arquivo_Origem')]
            
            if dados_finais or not df_existente.empty:
                caminho_planilha = output_filepath
                
                self.log("\nConsolidando dados e atualizando a planilha Excel...")
                try:
                    df_novos = pd.DataFrame(dados_finais)
                    
                    # (V12.0) Concatena o novo com o antigo
                    df_final_combinado = pd.concat([df_existente, df_novos], ignore_index=True)

                    # Reordenar colunas
                    colunas_ordenadas = ['Arquivo_Origem', 'Vencimento', 'Pagador', 'Beneficiário', 'Valor_Documento', 'Codigo_Barras']
                    colunas_finais = [col for col in colunas_ordenadas if col in df_final_combinado.columns]
                    df_sorted = df_final_combinado[colunas_finais]
                    
                    # (V13.0) Remove duplicatas baseado no Arquivo_Origem, mantendo o ÚLTIMO (o mais novo)
                    if 'Arquivo_Origem' in df_sorted.columns:
                         df_sorted.drop_duplicates(subset=['Arquivo_Origem'], keep='last', inplace=True)

                    df_sorted.to_excel(caminho_planilha, index=False)
                    
                    self.log(f"SUCESSO! Planilha atualizada em: {caminho_planilha}")
                    self.log(f"Total de registros na planilha: {len(df_sorted)}")
                    messagebox.showinfo("Processo Concluído", f"Planilha atualizada com sucesso!\n{len(dados_finais)} novos registros adicionados.\nTotal de registros: {len(df_sorted)}\n\nSalvo em:\n{caminho_planilha}")
                    self.finalizar_processamento(sucesso=True)
                    
                except PermissionError:
                    self.log(f"ERRO DE PERMISSÃO AO SALVAR PLANILHA: {caminho_planilha}")
                    messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar a planilha Excel:\n{caminho_planilha}\n\nVerifique se o arquivo não está aberto em outro programa.")
                    self.finalizar_processamento(sucesso=False)
                except Exception as ex_save:
                    self.log(f"ERRO AO SALVAR PLANILE: {ex_save}")
                    messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar a planilha Excel:\n{ex_save}")
                    self.finalizar_processamento(sucesso=False)

            else:
                self.log("\nProcessamento finalizado. Nenhum novo dado de boleto válido foi encontrado.")
                messagebox.showinfo("Processo Concluído", "Nenhum novo dado de boleto válido foi encontrado para adicionar à planilha.")
                self.finalizar_processamento(sucesso=False)
                
        except Exception as e:
            self.log(f"\n--- ERRO CRÍTICO NO PROCESSAMENTO ---")
            self.log(str(e))
            import traceback
            self.log(traceback.format_exc()) # Log completo do erro
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado:\n{e}")
            self.finalizar_processamento(sucesso=False)
            
    def finalizar_processamento(self, sucesso=True, cancelado=False):
        self.btn_selecionar_entrada.config(state="normal")
        self.btn_selecionar_saida.config(state="normal") 
        
        # (V14.0) Resetar o botão Iniciar
        self.btn_iniciar.config(text="3. Iniciar Processamento", bg="lightgray", command=self.iniciar_processamento, state="disabled")
        
        if self.arquivos_para_processar and self.output_filepath:
             self.btn_iniciar.config(state="normal", bg="lawn green")
             
        if sucesso:
            # (V13.0) Mostrar botões de resultado
            self.btn_abrir_planilha.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
            self.btn_abrir_pasta.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)
            self.btn_abrir_planilha.config(state="normal")
            self.btn_abrir_pasta.config(state="normal")
        
        if cancelado:
             self.log("--- PROCESSAMENTO CANCELADO ---")
        else:
             self.log("--- FIM DO PROCESSAMENTO ---")
             
        # Limpa a barra de progresso no final
        self.progress_bar.config(value=0)

# --- Ponto de Entrada Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root
