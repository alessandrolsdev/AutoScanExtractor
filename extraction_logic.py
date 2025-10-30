# -*- coding: utf-8 -*-
"""
extraction_logic.py

Contém a classe principal 'BoletoParser' e todas as sub-funções
de extração de dados (Modo 1 - Regex e Modo 2 - Posicional).

Este módulo não sabe sobre arquivos, PDFs ou GUIs. Ele apenas
recebe texto ou dados posicionais e retorna dados estruturados.
"""

import re
import math
import pandas as pd
from pytesseract import Output
import pytesseract
from PIL.Image import Image # Usado para Type Hinting
import dataclasses

# Importações de nossos módulos
from boleto_data import BoletoData

from config import DEFAULT_LANG, OCR_CONF_THRESHOLD, VALOR_MAX_DISTANCE

# --- Definição de Exceções Customizadas ---
class ExtractionError(Exception):
    """Erro base para falhas de extração."""
    pass

class OCRError(ExtractionError):
    """Falha ao rodar o Tesseract."""
    pass

class LayoutNaoReconhecidoError(ExtractionError):
    """Não foi possível encontrar os campos principais (ex: Modo 1 e 2 falharam)."""
    pass


class BoletoParser:
    """
    Classe que encapsula toda a lógica de extração de dados de boletos.
    Combina as abordagens de Regex (Modo 1) e Posicional (Modo 2).
    """

    # --- MODO 1: LÓGICA DE REGEX (Seu 'parse_boleto_text') ---
    
    def parse_modo1_regex(self, texto_extraido: str, nome_arquivo_origem: str) -> BoletoData:
        """
        MODO 1: Extração baseada em Expressões Regulares (Regex) aplicadas ao texto completo extraído.
        """
        print(f"\n--- DEBUG (V21.0): Iniciando parse (MODO 1 - REGEX) para {nome_arquivo_origem} ---")

        # Usa o BoletoData em vez de um dicionário
        dados_encontrados = BoletoData(arquivo_origem=nome_arquivo_origem)
        texto_trabalho = texto_extraido
        match_codigo = None

        # --- 1. Regex para Código de Barras ---
        print("--- DEBUG (V21.0): Tentando encontrar Código de Barras...")
        match_codigo = re.search( r"(\d{5}\.[_O\d]{5}\s+[_O\d]{5}\.[_O\d]{6}\s+[_O\d]{5}\.[_O\d]{6}\s+[_O\d]\s+[_O\d]{14})", texto_trabalho )
        if not match_codigo: match_codigo = re.search( r"([\dO]{9}[\.\s]?[\dO][\s\n]+[\dO]{10}[\.\s]?[\dO][\s\n]+[\dO]{10}[\.\s]?[\dO][\s\n]+[\dO][\s\n]+[\dO]{14})", texto_trabalho, re.IGNORECASE )
        if not match_codigo: match_codigo = re.search( r"([\dO]{5}[^\d\n]?[\dO]{5}[\s\n]+[\dO]{5}[^\d\n]?[\dO]{6}[\s\n]+[\dO]{5}[^\d\n]?[\dO]{6}[\s\n]+[\dO][\s\n]+[\dO]{14})", texto_trabalho, re.IGNORECASE )
        if not match_codigo:
            match_codigo_flex = re.search( r"(\d{5})\D?(\d{5})\D?(\d{5})\D?(\d{6})\D?(\d{5})\D?(\d{6})\D?(\d)\D?(\d{14})", texto_trabalho)
            if match_codigo_flex:
                groups = match_codigo_flex.groups()
                codigo_formatado = f"{groups[0]}.{groups[1]} {groups[2]}.{groups[3]} {groups[4]}.{groups[5]} {groups[6]} {groups[7]}"
                dados_encontrados.codigo_barras = codigo_formatado
                print(f"--- DEBUG (V21.0): Código de Barras encontrado (Flex): {dados_encontrados.codigo_barras}")

        if match_codigo and dados_encontrados.codigo_barras == 'Não encontrado':
            codigo_limpo = re.sub(r"[\s\n]+", " ", match_codigo.group(1))
            dados_encontrados.codigo_barras = codigo_limpo.replace("O", "0").replace("o", "0").replace("_", "0")
            print(f"--- DEBUG (V2V21.0): Código de Barras encontrado (Cascata): {dados_encontrados.codigo_barras}")
        if dados_encontrados.codigo_barras == 'Não encontrado':
            print("--- DEBUG (V21.0): Código de Barras NÃO encontrado.")

        # --- 2. Regex para Data de Vencimento ---
        print("--- DEBUG (V21.0): Tentando encontrar Vencimento (Regex Direto)...")
        match_vencimento = re.search(r"Venciment[o|a|u][\s\n]*([\dOS]{2}/[\dOS]{2}/[\dOS]{4})", texto_trabalho, re.IGNORECASE)
        if match_vencimento:
            vencimento_sujo = match_vencimento.group(1)
            dados_encontrados.vencimento = vencimento_sujo.replace("O", "0").replace("S", "5")
            print(f"--- DEBUG (V21.0): Vencimento encontrado (Regex Direto): {dados_encontrados.vencimento}")
        else:
            print("--- DEBUG (V21.0): Vencimento NÃO encontrado (Regex Direto).")
            # Usa o método privado da classe
            venc_contexto = self._extrair_vencimento_regex_contexto(texto_trabalho)
            if venc_contexto:
                dados_encontrados.vencimento = venc_contexto.replace("O", "0").replace("S", "5")
                print(f"--- DEBUG (V21.0): Vencimento encontrado (Regex Contexto): {dados_encontrados.vencimento}")

        # --- 3. Regex para Beneficiário ---
        print("--- DEBUG (V21.0): Tentando encontrar Beneficiário (via Número CNPJ)...")
        match_linha_cnpj = re.search(r"^\s*(.*?CNPJ\s*\d{2}[\.\s]?\d{3}[\.\s]?\d{3}/\d{4}[\-\s]?\d{2}.*)$", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        beneficiario_encontrado = False
        if match_linha_cnpj:
            print("--- DEBUG (V21.0): Encontrou linha com CNPJ.")
            linha_completa = match_linha_cnpj.group(1).strip()
            match_nome_mesma_linha = re.search(r"^([^\n]+?)\s*CNPJ", linha_completa, re.IGNORECASE)
            # Usa o método privado da classe
            if match_nome_mesma_linha and self._is_valid_candidate(match_nome_mesma_linha.group(1)):
                    dados_encontrados.beneficiario = match_nome_mesma_linha.group(1).strip()
                    beneficiario_encontrado = True
                    print(f"--- DEBUG (V21.0): Beneficiário encontrado (mesma linha CNPJ): {dados_encontrados.beneficiario}")
            else:
                print("--- DEBUG (V21.0): Não encontrou nome na mesma linha do CNPJ. Tentando linha anterior...")
                pos_inicio_linha_cnpj = match_linha_cnpj.start()
                texto_antes = texto_trabalho[:pos_inicio_linha_cnpj].strip()
                linhas_antes = texto_antes.split('\n')
                if linhas_antes and linhas_antes[-1].strip():
                    linha_anterior = linhas_antes[-1].strip()
                    if self._is_valid_candidate(linha_anterior):
                            dados_encontrados.beneficiario = linha_anterior
                            beneficiario_encontrado = True
                            print(f"--- DEBUG (V21.0): Beneficiário encontrado (linha anterior CNPJ): {dados_encontrados.beneficiario}")
                    else:
                            print(f"--- DEBUG (V21.0): Candidato (linha anterior CNPJ) REJEITADO pela validação: '{linha_anterior}'")
        else:
            print("--- DEBUG (V21.0): Não encontrou linha com CNPJ.")

        if not beneficiario_encontrado:
            print("--- DEBUG (V21.0): Tentando fallback 1 (Mesma Linha)...")
            match_empresa = re.search(r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Benefici[á|a|o]rio[^\w\n]*([^\n]+)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
            if match_empresa:
                nome_bruto = match_empresa.group(1).strip()
                nome_sem_cnpj = re.sub(r'\s*CNPJ.*$', '', nome_bruto, flags=re.IGNORECASE).strip()
                if self._is_valid_candidate(nome_sem_cnpj):
                    dados_encontrados.beneficiario = nome_sem_cnpj
                    beneficiario_encontrado = True
                    print(f"--- DEBUG (V21.0): Beneficiário encontrado (Fallback 1 - Mesma Linha): {dados_encontrados.beneficiario}")
                else:
                    print(f"--- DEBUG (V21.0): Candidato (Fallback 1) REJEITADO: '{nome_sem_cnpj}'")

        if not beneficiario_encontrado:
            print("--- DEBUG (V21.0): Tentando fallback 2 (Próxima Linha)...")
            match_empresa = re.search(r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Benefici[á|a|o]rio\s*\n\s*([^\n]+)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
            if match_empresa:
                nome_bruto = match_empresa.group(1).strip()
                if "CNPJ" not in nome_bruto.upper() and self._is_valid_candidate(nome_bruto):
                    dados_encontrados.beneficiario = nome_bruto
                    beneficiario_encontrado = True
                    print(f"--- DEBUG (V21.0): Beneficiário encontrado (Fallback 2 - Próxima Linha): {dados_encontrados.beneficiario}")
                else:
                    print(f"--- DEBUG (V21.0): Candidato (Fallback 2) REJEITADO: '{nome_bruto}'")

        if not beneficiario_encontrado:
                print("--- DEBUG (V21.0): Beneficiário NÃO encontrado após todas as tentativas.")

        # --- 4. Regex para Pagador ---
        print("--- DEBUG (V21.0): Tentando encontrar Pagador (via CPF)...")
        match_cpf = re.search(r"CPF[:\s]*(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?\d{2})", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        pagador_encontrado = False
        if match_cpf:
            print(f"--- DEBUG (V21.0): Encontrou padrão numérico CPF: '{match_cpf.group(1)}'")
            pos_cpf = match_cpf.start()
            inicio_linha_cpf = texto_trabalho.rfind('\n', 0, pos_cpf) + 1
            texto_antes_cpf = texto_trabalho[inicio_linha_cpf:pos_cpf].strip()
            match_pagador_mesma_linha = re.search(r"Pagador:?\s+(.+)", texto_antes_cpf, re.IGNORECASE)
            if match_pagador_mesma_linha and self._is_valid_candidate(match_pagador_mesma_linha.group(1)):
                dados_encontrados.pagador = match_pagador_mesma_linha.group(1).strip()
                pagador_encontrado = True
                print(f"--- DEBUG (V2V21.0): Pagador encontrado (mesma linha CPF): {dados_encontrados.pagador}")
            else:
                print("--- DEBUG (V21.0): Não encontrou Pagador na mesma linha do CPF. Tentando linha anterior...")
                texto_antes_cpf = texto_trabalho[:pos_cpf].strip()
                linhas_antes = texto_antes_cpf.split('\n')
                if len(linhas_antes) > 0:
                    linha_anterior = linhas_antes[-1].strip()
                    if len(linhas_antes) > 1 and re.search(r"Pagador", linhas_antes[-2], re.IGNORECASE):
                            if self._is_valid_candidate(linha_anterior):
                                dados_encontrados.pagador = linha_anterior
                                pagador_encontrado = True
                                print(f"--- DEBUG (V21.0): Pagador encontrado (linha anterior CPF): {dados_encontrados.pagador}")
                            else: print(f"--- DEBUG (V21.0): Candidato (linha anterior CPF) REJEITADO: '{linha_anterior}'")
                else: print("--- DEBUG (V21.0): Não encontrou linha anterior ao CPF.")
        else:
            print("--- DEBUG (V21.0): Não encontrou padrão numérico do CPF.")

        if not pagador_encontrado:
            print("--- DEBUG (V21.0): Tentando fallback do Pagador...")
            match_pagador = re.search(r"^\s*Pagador:?\s+([^\n]+?)(?=\s*CPF|$)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
            if not match_pagador: match_pagador = re.search(r"^\s*Pagador\s*\n\s*([^\n]+?)(?=\s*CPF|$)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
            if match_pagador:
                    nome_pagador_bruto = match_pagador.group(1).strip()
                    if self._is_valid_candidate(nome_pagador_bruto):
                        dados_encontrados.pagador = nome_pagador_bruto
                        pagador_encontrado = True
                        print(f"--- DEBUG (V21.0): Pagador encontrado (fallback): {dados_encontrados.pagador}")
                    else: print(f"--- DEBUG (V21.0): Candidato (fallback) REJEITADO: '{nome_pagador_bruto}'")

        if dados_encontrados.pagador != 'Não encontrado':
            dados_encontrados.pagador = re.sub(r'\s*-\s*$', '', dados_encontrados.pagador).strip()
        if not pagador_encontrado:
            print("--- DEBUG (V21.0): Pagador NÃO encontrado após todas as tentativas.")

        # --- 5. Regex para Valor do Documento ---
        print("--- DEBUG (V21.0): Tentando encontrar Valor do Documento...")
        valor_encontrado = None
        regex_valor = r"([ \d\.]*,\d{2})"
        regex_lixo = r"[^\n\d]*" 
        
        match_valor = re.search(r"(?:=\)\s*)?Valor (?:do )?Documento" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
        if match_valor:
            valor_encontrado = match_valor.group(1)
            print("--- DEBUG (V21.0): Valor encontrado (T1 - Mesma linha):", valor_encontrado)

        if not valor_encontrado:
            match_valor = re.search(r"=\)\s*Valor\s*(?:do )?Documento\s*\n" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
            if match_valor:
                valor_encontrado = match_valor.group(1)
                print("--- DEBUG (V21.0): Valor encontrado (T2 - Fallback = Valor):", valor_encontrado)

        if not valor_encontrado:
            match_valor = re.search(r"Valor (?:do )?Documento\s*\n" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
            if match_valor:
                valor_encontrado = match_valor.group(1)
                print("--- DEBUG (V21.0): Valor encontrado (T3 - Rótulo/Valor linhas dif):", valor_encontrado)

        if not valor_encontrado:
            match_valor = re.search(r"Valor Cobrado" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
            if match_valor:
                valor_encontrado = match_valor.group(1)
                print("--- DEBUG (V21.0): Valor encontrado (T4 - Valor Cobrado):", valor_encontrado)

        if not valor_encontrado:
            match_valor = re.search(r"Valor Cobrado\s*\n" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE)
            if match_valor:
                valor_encontrado = match_valor.group(1)
                print("--- DEBUG (V21.0): Valor encontrado (T5 - Valor Cobrado linha dif):", valor_encontrado)

        if not valor_encontrado:
            match_valor = re.search(r"^\s*Valor\s+" + regex_lixo + regex_valor, texto_trabalho, re.IGNORECASE | re.MULTILINE)
            if match_valor:
                valor_encontrado = match_valor.group(1)
                print("--- DEBUG (V21.0): Valor encontrado (T6 - Apenas Valor):", valor_encontrado)

        if valor_encontrado:
            valor_limpo = valor_encontrado.strip()
            valor_limpo = re.sub(r'\s', '', valor_limpo)
            dados_encontrados.valor_documento = valor_limpo
            print(f"--- DEBUG (V21.0): Valor final limpo: {valor_limpo}")
        else:
            print("--- DEBUG (V21.0): Valor NÃO encontrado após todas as tentativas.")

        print(f"--- DEBUG (V21.0): Parse (MODO 1) finalizado para {nome_arquivo_origem}. ---")
        return dados_encontrados


    # --- MODO 2: LÓGICA POSICIONAL (Seu 'parse_boleto_data_posicional') ---
    
    def parse_modo2_posicional(self, pil_image_processada: Image, dados_atuais: BoletoData) -> BoletoData:
        """
        MODO 2: Extração baseada na POSIÇÃO das palavras na imagem.
        Usado como fallback para PREENCHER campos que o Modo 1 (Regex) não encontrou.
        Recebe o objeto BoletoData e o atualiza.
        """
        
        # Verifica quais campos estão faltando
        campos_faltantes = {
            k: v for k, v in dataclasses.asdict(dados_atuais).items() 
            if v == 'Não encontrado' and k in ['vencimento', 'beneficiario', 'valor_documento']
        }
        # Converte chaves para os nomes de atributo (ex: 'valor_documento' -> 'Valor_Documento')
        # Esta é uma parte "feia" da fusão...
        mapa_campos = {
            'vencimento': 'Vencimento',
            'valor_documento': 'Valor_Documento',
            'beneficiario': 'Beneficiário'
        }
        campos_faltantes_orig = {mapa_campos[k]:v for k,v in campos_faltantes.items() if k in mapa_campos}
        
        if not campos_faltantes_orig:
            print(f"--- DEBUG (V21.0): Modo 2 (Posicional) não necessário. Todos os campos principais encontrados.")
            return dados_atuais # Retorna os dados originais, nada a fazer

        print(f"--- DEBUG (V21.0): Iniciando (MODO 2 - POSICIONAL) para campos faltantes: {list(campos_faltantes_orig.keys())} ---")

        try:
            # 1. Obter o DataFrame posicional (o "data") do Tesseract
            data = pytesseract.image_to_data(pil_image_processada, lang=DEFAULT_LANG, output_type=Output.DATAFRAME)

            # --- Limpeza inicial do DataFrame ---
            data = data[data.conf > OCR_CONF_THRESHOLD] # Usa constante do config
            data = data.dropna(subset=['text'])
            data['text'] = data['text'].astype(str).str.strip()
            data = data[data.text != '']

            # 2. Inicializar listas de keywords e candidatos
            keywords = {
                'beneficiario': [],
                'valor': []
            }
            candidates_valor = []

            regex_valor = re.compile(r"^([\d\.OSBl]*[,][\dOS]{2})$")

            # --- Mapeamento de Keywords e Candidatos ---
            for index, row in data.iterrows():
                text = row['text']
                x, y, w, h = row['left'], row['top'], row['width'], row['height']
                pos = (x + w // 2, y + h // 2)
                text_upper = text.upper()

                if 'BENEFICI' in text_upper:
                    keywords['beneficiario'].append((x, y, w, h))
                if 'VALOR' in text_upper or 'DOCUMENTO' in text_upper or 'COBRADO' in text_upper:
                    keywords['valor'].append(pos)
                if regex_valor.match(text):
                    candidates_valor.append({'text': text, 'pos': pos})

            # --- 3. Lógica de Fusão de Valor (V20.0) ---
            print("--- DEBUG (V21.0): Iniciando lógica de fusão para Valor...")
            regex_pre_virgula = re.compile(r"^[\d\.]+$")
            regex_pos_virgula = re.compile(r"^\d{2}$")

            for i in range(len(data) - 1):
                row1 = data.iloc[i]
                row2 = data.iloc[i+1]
                text1, text2 = row1['text'], row2['text']

                if regex_pre_virgula.match(text1) and regex_pos_virgula.match(text2):
                    y1, h1 = row1['top'], row1['height']
                    y2, h2 = row2['top'], row2['height']
                    x1, w1 = row1['left'], row1['width']
                    x2 = row2['left']
                    y_meio1, y_meio2 = y1 + h1 / 2, y2 + h2 / 2

                    if (abs(y_meio1 - y_meio2) < 10) and (x2 > (x1 + w1)) and ((x2 - (x1+w1)) < 50):
                        fused_text = f"{text1},{text2}"
                        fused_pos = ( (x1 + x2) // 2, (y1 + y2) // 2 )
                        candidates_valor.append({'text': fused_text, 'pos': fused_pos})
                        print(f"--- DEBUG (V21.0): Fusão ACEITA! Criado novo candidato: '{fused_text}'")

            # --- PROCESSA CAMPOS FALTANTES ---

            # 1. Processa Vencimento (V21.0 - Usando suas funções avançadas)
            if 'Vencimento' in campos_faltantes_orig:
                print("--- DEBUG (V21.0): Processando Vencimento (Com suas funções avançadas)...")
                venc_encontrado = self._detectar_vencimento_avancado(data) # Usa método privado
                
                if venc_encontrado and venc_encontrado != 'Não encontrado':
                    dados_atuais.vencimento = self._clean_data(venc_encontrado) # Usa método privado
                    print(f"--- DEBUG (V21.0): Vencimento ACEITO (Avançado): {dados_atuais.vencimento}")
                else:
                    print("--- DEBUG (V21.0): Vencimento (Avançado) - Suas funções não encontraram (Provável falha do OCR).")

            # 2. Processa Valor (ESTRATÉGIA V20.0 - DISTÂNCIA + FUSÃO)
            if 'Valor_Documento' in campos_faltantes_orig:
                print("--- DEBUG (V21.0): Processando Valor (Estratégia 'Distância')...")

                if not keywords['valor']:
                    print("--- DEBUG (V21.0): Valor (Posicional - Distance) - Nenhuma keyword 'Valor' foi lida.")
                elif not candidates_valor:
                    print("--- DEBUG (V21.0): Valor (Posicional - Distance) - Nenhum candidato (normal ou fundido) foi encontrado.")
                else:
                    valor_encontrado = self._find_closest(keywords['valor'], candidates_valor, VALOR_MAX_DISTANCE) # Usa método privado

                    if valor_encontrado:
                        valor_limpo = re.sub(r'\s', '', valor_encontrado)
                        dados_atuais.valor_documento = self._clean_data(valor_limpo) # Usa método privado
                        print(f"--- DEBUG (V21.0): Valor ACEITO (Posicional - Distance): {dados_atuais.valor_documento}")
                    else:
                        print("--- DEBUG (V21.0): Valor (Posicional - Distance) - Nenhuma keyword 'Valor' estava próxima de um candidato.")

            # 3. Processa Beneficiário (ESTRATÉGIA V16.0 - LAYOUT)
            if 'Beneficiário' in campos_faltantes_orig and keywords['beneficiario']:
                print(f"--- DEBUG (V21.0): Processando Beneficiário (Estratégia 'Layout V16'). {len(keywords['beneficiario'])} palavras-chave encontradas.")
                beneficiario_final_encontrado = False

                for i, (x_key, y_key, w_key, h_key) in enumerate(keywords['beneficiario']):
                    if beneficiario_final_encontrado: break
                    print(f"--- DEBUG (V21.0): Testando palavra-chave Beneficiário #{i+1}...")
                    nome_encontrado_bruto = None

                    # TENTATIVA 1: MESMA LINHA
                    linha_beneficiario = []
                    y_meio_key, x_fim_key = y_key + h_key / 2, x_key + w_key
                    y_tolerancia = 20

                    for index, row in data.iterrows():
                        x_row, y_row, h_row = row['left'], row['top'], row['height']
                        y_meio_row = y_row + h_row / 2
                        if (abs(y_meio_row - y_meio_key) < y_tolerancia) and (x_row > x_fim_key):
                            linha_beneficiario.append({'x': x_row, 'text': row['text']})

                    if linha_beneficiario:
                        linha_beneficiario.sort(key=lambda item: item['x'])
                        nome_encontrado_bruto = " ".join([item['text'] for item in linha_beneficiario])
                        print(f"--- DEBUG (V21.0): Beneficiário (Layout) - Teste #{i+1} 'Mesma Linha' encontrou: '{nome_encontrado_bruto}'")
                    else:
                        print(f"--- DEBUG (V21.0): Beneficiário (Layout) - Teste #{i+1} 'Mesma Linha' falhou. Tentando 'Linha Abaixo'...")
                        # TENTATIVA 2: LINHA ABAIXO
                        linha_abaixo = []
                        x_meio_key, y_fim_key = x_key + w_key / 2, y_key + h_key
                        x_tolerancia_abaixo = 150

                        for index, row in data.iterrows():
                            x_row, y_row, w_row, h_row = row['left'], row['top'], row['width'], row['height']
                            x_meio_row = x_row + w_row / 2
                            if (y_row > y_fim_key) and (abs(x_meio_row - x_meio_key) < x_tolerancia_abaixo):
                                linha_abaixo.append({'y': y_row, 'x': x_row, 'text': row['text']})

                        if linha_abaixo:
                            linha_abaixo.sort(key=lambda item: (item['y'], item['x']))
                            linha_y_proxima = linha_abaixo[0]['y']
                            palavras_da_linha = []
                            for item in linha_abaixo:
                                if abs(item['y'] - linha_y_proxima) < y_tolerancia:
                                    palavras_da_linha.append(item)
                                else:
                                    break
                            palavras_da_linha.sort(key=lambda item: item['x'])
                            nome_encontrado_bruto = " ".join([item['text'] for item in palavras_da_linha])
                            print(f"--- DEBUG (V21.0): Beneficiário (Layout) - Teste #{i+1} 'Linha Abaixo' encontrou: '{nome_encontrado_bruto}'")
                        else:
                            print("--- DEBUG (V21.0): Beneficiário (Layout) - Teste #{i+1} 'Linha Abaixo' falhou.")

                    # VALIDAÇÃO FINAL (após T1 ou T2)
                    if nome_encontrado_bruto:
                        nome_sem_cnpj = re.sub(r'\s*CNPJ.*$', '', nome_encontrado_bruto, flags=re.IGNORECASE).strip()
                        if self._is_valid_candidate(nome_sem_cnpj): # Usa método privado
                            dados_atuais.beneficiario = nome_sem_cnpj
                            beneficiario_final_encontrado = True
                            print(f"--- DEBUG (V21.0): Beneficiário ACEITO (Layout) no Teste #{i+1}: {dados_atuais.beneficiario}")
                        else:
                            print(f"--- DEBUG (V21.0): Beneficiário REJEITADO (Layout) no Teste #{i+1} pela validação: '{nome_encontrado_bruto}'")
                
                if not beneficiario_final_encontrado:
                    print("--- DEBUG (V21.0): Beneficiário (Layout) - Nenhuma palavra-chave produziu um resultado válido.")

        except Exception as e:
            # Captura erros inesperados durante o Modo 2
            print(f"--- ERRO (V21.0): Falha no Modo Posicional: {e} ---")
            import traceback
            print(traceback.format_exc()) # Imprime o stack trace completo para depuração

        # Retorna o objeto BoletoData ATUALIZADO
        return dados_atuais

    # --- FUNÇÕES HELPER (Agora são métodos privados da classe) ---

    def _extrair_vencimento_regex_contexto(self, ocr_text):
        """ Tenta extrair a data de vencimento do texto completo usando Regex com contexto. (V21.0) """
        padroes_contexto = [
            r'vencimento\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
            r'venc\.?\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
            r'vencto\.?\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})'
        ]
        for padrao in padroes_contexto:
            m = re.search(padrao, ocr_text, flags=re.IGNORECASE)
            if m:
                return m.group(1)

        datas = re.findall(r'\b\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\b', ocr_text)
        if datas:
            for data in datas:
                idx = ocr_text.find(data)
                trecho_antes = ocr_text[max(0, idx-25):idx].lower()
                if "venc" in trecho_antes:
                    return data
            try:
                datas_normalizadas = []
                for d in datas:
                    partes = re.split(r'[\/\-\.]', d)
                    if len(partes[2]) == 2: partes[2] = "20" + partes[2]
                    if len(partes[0]) == 1: partes[0] = "0" + partes[0]
                    if len(partes[1]) == 1: partes[1] = "0" + partes[1]
                    datas_normalizadas.append( ( (partes[2], partes[1], partes[0]), d ) )
                if datas_normalizadas:
                    datas_normalizadas.sort(key=lambda x: x[0], reverse=True)
                    return datas_normalizadas[0][1]
            except Exception as e:
                print(f"--- DEBUG (V21.0): Erro ao ordenar datas: {e}. Retornando a última encontrada.")
                return datas[-1]
        return None

    def _extrair_vencimento_posicional(self, df):
        """ Tenta extrair a data de vencimento usando a posição das palavras no DataFrame do Tesseract. (V21.0) """
        df['text'] = df['text'].astype(str).str.strip()
        df_filtrado = df[df['text'].str.len() > 0]
        df_venc = df_filtrado[df_filtrado['text'].str.contains('venc', case=False, na=False)]
        if df_venc.empty:
            return None
        
        resultados = []
        for _, row in df_venc.iterrows():
            y_ref, x_ref = row['top'], row['left']
            proximos = df_filtrado[
                (df_filtrado['top'] >= y_ref - 10) & 
                (df_filtrado['top'] <= y_ref + 50) & 
                (df_filtrado['left'] > x_ref)
            ]
            for _, p in proximos.iterrows():
                texto = str(p['text'])
                m = re.search(r'\b\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\b', texto)
                if m:
                    resultados.append(m.group(0))
        
        if resultados:
            try:
                datas_normalizadas = []
                for d in resultados:
                    partes = re.split(r'[\/\-\.]', d)
                    if len(partes[2]) == 2: partes[2] = "20" + partes[2]
                    if len(partes[0]) == 1: partes[0] = "0" + partes[0]
                    if len(partes[1]) == 1: partes[1] = "0" + partes[1]
                    datas_normalizadas.append( ( (partes[2], partes[1], partes[0]), d ) )
                if datas_normalizadas:
                    datas_normalizadas.sort(key=lambda x: x[0], reverse=True)
                    return datas_normalizadas[0][1]
            except Exception:
                return resultados[0]
        return None

    def _detectar_vencimento_avancado(self, df):
        """ Orquestra a detecção de vencimento, posicional e depois regex. (V2A21.0) """
        venc = self._extrair_vencimento_posicional(df)
        if venc:
            print(f"--- DEBUG (V21.0): Vencimento encontrado por POSIÇÃO: {venc}")
            return venc
        
        texto_completo = " ".join(df['text'].astype(str).tolist())
        venc = self._extrair_vencimento_regex_contexto(texto_completo)
        if venc:
            print(f"--- DEBUG (V21.0): Vencimento encontrado por CONTEXTO: {venc}")
            return venc
        
        print("--- DEBUG (V21.0): Nenhum vencimento encontrado pelas funções avançadas.")
        return "Não encontrado"

    def _is_valid_candidate(self, text):
        """ Verifica se um texto extraído parece ser um nome válido. (V5.1) """
        if not text: return False
        text = text.strip()
        if len(text) <= 3:
            return False
        if re.fullmatch(r"[\d\s\.\/\-\,\—]+", text):
            return False
        lixo_sem_valor = ["NOSSO NÚMERO", "AGÊNCIA", "CÓDIGO BENEFICIÁRIO", "VENCIMENTO", "RECIBO DO PAGADOR", "AUTENTICAÇÃO MECANICA"]
        if any(k in text.upper() for k in lixo_sem_valor):
            return False
        return True

    def _find_closest(self, keyword_pos_list, candidates_list, max_dist_threshold):
        """ FUNÇÃO HELPER: ACHAR MAIS PRÓXIMO (V20.0) """
        if not keyword_pos_list or not candidates_list: return None
        closest_candidate = None
        min_dist = float('inf')

        for key_pos in keyword_pos_list:
            for candidate in candidates_list:
                dist = math.sqrt((candidate['pos'][0] - key_pos[0])**2 + (candidate['pos'][1] - key_pos[1])**2)
                if dist < min_dist:
                    min_dist = dist
                    closest_candidate = candidate['text']
        
        if min_dist < max_dist_threshold: # Usa constante do config
            return closest_candidate
        return None

    def _clean_data(self, text_sujo):
        """ FUNÇÃO HELPER: LIMPEZA (V19.0) """
        text_sujo = text_sujo.replace("/", "-").replace(".", "-")
        return text_sujo.replace("O", "0").replace("S", "5").replace("B", "8").replace("l", "1")