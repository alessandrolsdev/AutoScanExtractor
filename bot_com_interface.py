import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import pytesseract
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

# --- CONFIGURAÇÃO (MODO DE COMPILAÇÃO) ---
try:
    # Aponta para o Tesseract que será empacotado DENTRO do .exe
    tesseract_exe_path = resource_path("tesseract.exe")
    pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
    # Aponta para a pasta de dados DENTRO do .exe
    tessdata_path = resource_path("tessdata")
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

# --- FUNÇÃO DE VALIDAÇÃO (V5.1 - Simples) ---
def is_valid_candidate(text):
    """Verificação básica se o texto não é obviamente lixo (V5.1)"""
    if not text: return False
    text = text.strip()
    if len(text) <= 3: return False
    if re.fullmatch(r"[\d\s\.\/\-\,\—]+", text): return False
    lixo = ["NOSSO NÚMERO", "AGÊNCIA", "CÓDIGO BENEFICIÁRIO", "VENCIMENTO", "RECIBO DO PAGADOR", "AUTENTICAÇÃO MECANICA", "VALOR"]
    if any(k in text.upper() for k in lixo): return False
    return True

# --- LÓGICA DE EXTRAÇÃO ---

# (V5.6 / V5.1 Híbrido) - Sem Debug
def parse_boleto_text(texto_extraido, nome_arquivo_origem):
    """
    Pega o texto cru do OCR de um boleto e o nome do arquivo,
    retorna uma lista com um dicionário de dados do boleto (V5.6).
    """
    dados_encontrados = {
        'Arquivo_Origem': nome_arquivo_origem,
        'Vencimento': 'Não encontrado',
        'Beneficiário': 'Não encontrado',
        'Pagador': 'Não encontrado',
        'Codigo_Barras': 'Não encontrado'
    }

    texto_trabalho = texto_extraido
    match_codigo = None

    # 1. Regex para Código de Barras (PRIORIDADE 1 - CASCATA V4.0)
    match_codigo = re.search( r"(\d{5}\.\d{5}\s+\d{10}\.\d{6}\s+\d{5}\.\d{6}\s+\d\s+\d{14})", texto_trabalho )
    if not match_codigo: match_codigo = re.search( r"([\dO]{9}[\.\s]?[\dO][\s\n]+[\dO]{10}[\.\s]?[\dO][\s\n]+[\dO]{10}[\.\s]?[\dO][\s\n]+[\dO][\s\n]+[\dO]{14})", texto_trabalho, re.IGNORECASE )
    if not match_codigo: match_codigo = re.search( r"([\dO]{5}[^\d\n]?[\dO]{5}[\s\n]+[\dO]{5}[^\d\n]?[\dO]{6}[\s\n]+[\dO]{5}[^\d\n]?[\dO]{6}[\s\n]+[\dO][\s\n]+[\dO]{14})", texto_trabalho, re.IGNORECASE )
    # Adiciona regex flexível V8.0 como fallback final
    if not match_codigo:
        match_codigo_flex = re.search( r"(\d{5})\D?(\d{5})\D?(\d{5})\D?(\d{6})\D?(\d{5})\D?(\d{6})\D?(\d)\D?(\d{14})", texto_trabalho)
        if match_codigo_flex:
            groups = match_codigo_flex.groups()
            codigo_formatado = f"{groups[0]}.{groups[1]} {groups[2]}.{groups[3]} {groups[4]}.{groups[5]} {groups[6]} {groups[7]}"
            dados_encontrados['Codigo_Barras'] = codigo_formatado

    if match_codigo and dados_encontrados['Codigo_Barras'] == 'Não encontrado':
        codigo_limpo = re.sub(r"[\s\n]+", " ", match_codigo.group(1))
        dados_encontrados['Codigo_Barras'] = codigo_limpo.replace("O", "0").replace("o", "0")

    # 2. Regex para Data de Vencimento (PRIORIDADE 2 - Mantido)
    match_vencimento = re.search(r"Vencimento[\s\n]*(\d{2}/\d{2}/\d{4})", texto_trabalho, re.IGNORECASE)
    if match_vencimento: dados_encontrados['Vencimento'] = match_vencimento.group(1)

    # 3. Regex para Beneficiário (PRIORIDADE 3 - "Bottom-Up" via CNPJ Refinado + Fallbacks)
    match_linha_cnpj = re.search(r"^\s*(.*?CNPJ\s*\d{2}[\.\s]?\d{3}[\.\s]?\d{3}/\d{4}[\-\s]?\d{2}.*)$", texto_trabalho, re.MULTILINE | re.IGNORECASE)
    if match_linha_cnpj:
        linha_completa = match_linha_cnpj.group(1).strip()
        match_nome_mesma_linha = re.search(r"^([^\n]+?)\s*CNPJ", linha_completa, re.IGNORECASE)
        if match_nome_mesma_linha and is_valid_candidate(match_nome_mesma_linha.group(1)):
             dados_encontrados['Beneficiário'] = match_nome_mesma_linha.group(1).strip()
        else:
            pos_inicio_linha_cnpj = match_linha_cnpj.start()
            texto_antes = texto_trabalho[:pos_inicio_linha_cnpj].strip()
            linhas_antes = texto_antes.split('\n')
            if linhas_antes and linhas_antes[-1].strip():
                linha_anterior = linhas_antes[-1].strip()
                if is_valid_candidate(linha_anterior):
                     dados_encontrados['Beneficiário'] = linha_anterior

    # Fallback 1 para Beneficiário (procura na linha SEGUINTE)
    if dados_encontrados['Beneficiário'] == 'Não encontrado':
         match_empresa = re.search(r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Beneficiário\s*\n\s*([^\n]+)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
         if match_empresa and is_valid_candidate(match_empresa.group(1)):
             nome_beneficiario_fallback = match_empresa.group(1).strip()
             if "CNPJ" not in nome_beneficiario_fallback.upper():
                 dados_encontrados['Beneficiário'] = nome_beneficiario_fallback

    # Fallback 2 para Beneficiário (procura na MESMA linha)
    if dados_encontrados['Beneficiário'] == 'Não encontrado':
        match_empresa = re.search(r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Beneficiário\s+([^\n]+)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        if match_empresa:
             nome_beneficiario_fallback = match_empresa.group(1).strip()
             if "CNPJ" not in nome_beneficiario_fallback.upper() and is_valid_candidate(nome_beneficiario_fallback):
                  dados_encontrados['Beneficiário'] = nome_beneficiario_fallback
             elif nome_beneficiario_fallback and "CNPJ" in nome_beneficiario_fallback.upper():
                 nome_sem_cnpj = re.sub(r'\s*CNPJ.*$', '', nome_beneficiario_fallback, flags=re.IGNORECASE).strip()
                 if is_valid_candidate(nome_sem_cnpj):
                     dados_encontrados['Beneficiário'] = nome_sem_cnpj


    # 4. Regex para Pagador (PRIORIDADE 4 - "Bottom-Up" via CPF + Fallback)
    match_cpf = re.search(r"CPF[:\s]*(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?\d{2})", texto_trabalho, re.MULTILINE | re.IGNORECASE)
    pagador_encontrado = False
    if match_cpf:
        pos_cpf = match_cpf.start()
        texto_antes_cpf_mesma_linha = texto_trabalho[:pos_cpf].split('\n')[-1]
        match_pagador_mesma_linha = re.search(r"Pagador:?\s+(.+)", texto_antes_cpf_mesma_linha, re.IGNORECASE)
        if match_pagador_mesma_linha and is_valid_candidate(match_pagador_mesma_linha.group(1)):
            dados_encontrados['Pagador'] = match_pagador_mesma_linha.group(1).strip()
            pagador_encontrado = True
        else:
             texto_antes_cpf = texto_trabalho[:pos_cpf].strip()
             linhas_antes = texto_antes_cpf.split('\n')
             if len(linhas_antes) > 0:
                 linha_anterior = linhas_antes[-1].strip()
                 if len(linhas_antes) > 1 and re.search(r"Pagador", linhas_antes[-2], re.IGNORECASE):
                      if is_valid_candidate(linha_anterior):
                           dados_encontrados['Pagador'] = linha_anterior
                           pagador_encontrado = True
                           
    if not pagador_encontrado:
        match_pagador = re.search(r"^\s*Pagador:?\s+([^\n]+?)(?=\s*CPF|$)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        if not match_pagador: match_pagador = re.search(r"^\s*Pagador\s*\n\s*([^\n]+?)(?=\s*CPF|$)", texto_trabalho, re.MULTILINE | re.IGNORECASE)
        if match_pagador:
             nome_pagador_bruto = match_pagador.group(1).strip()
             if is_valid_candidate(nome_pagador_bruto):
                 dados_encontrados['Pagador'] = nome_pagador_bruto
    
    # Filtro Final para Pagador
    if dados_encontrados['Pagador'] != 'Não encontrado':
        dados_encontrados['Pagador'] = re.sub(r'\s*-\s*$', '', dados_encontrados['Pagador']).strip()


    if any(v != 'Não encontrado' for k, v in dados_encontrados.items() if k != 'Arquivo_Origem'):
        return [dados_encontrados]
    else:
        return []

# --- Funções processar_pdf e extrair_dados_da_imagem (sem mudanças) ---
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
            dados_pagina = parse_boleto_text(texto_digital_completo, f"{nome_arquivo} (Digital)")
            if dados_pagina: dados_digital.extend(dados_pagina)

        # Verifica se o modo digital encontrou dados SUFICIENTES
        if any(d['Pagador'] != 'Não encontrado' or d['Beneficiário'] != 'Não encontrado' for d in dados_digital):
            doc.close()
            return dados_digital, None
        else:
             dados_do_pdf = [] # Limpa a lista para o modo OCR


        # Se não achou texto digital útil, parte para OCR página a página
        doc.close() # Fecha e reabre para segurança
        doc = fitz.open(caminho_pdf)
        texto_completo_ocr = ""
        for num_pagina, page in enumerate(doc):
            try:
                pix = page.get_pixmap(dpi=300)
                samples = pix.samples
                mode = "RGB"
                if pix.alpha: mode = "RGBA"
                img = Image.frombytes(mode, [pix.width, pix.height], samples)
                if img.mode == 'RGBA': img = img.convert('RGB')

                img_processada = preprocessar_imagem_para_ocr(img)
                texto_ocr_pagina = pytesseract.image_to_string(img_processada, lang='por')
                texto_completo_ocr += texto_ocr_pagina + "\n\n"
            except Exception as page_e:
                print(f"--- ERRO (V5.6): Erro ao processar página {num_pagina+1}: {page_e} ---")
                continue

        doc.close()

        if texto_completo_ocr.strip():
             dados_pagina_ocr = parse_boleto_text(texto_completo_ocr, f"{nome_arquivo} (OCR)")
             if dados_pagina_ocr: dados_do_pdf.extend(dados_pagina_ocr)

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
        texto_extraido = pytesseract.image_to_string(img_processada, lang='por')
        dados_da_imagem = parse_boleto_text(texto_extraido.strip(), nome_arquivo)
        if dados_da_imagem: return dados_da_imagem, None
        else: return [], None
    except Exception as e: return [], str(e)

# --- CLASSE DA APLICAÇÃO (GUI) ---
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Extrator v5.6 (Final)") # <--- Título V5.6
        self.root.geometry("600x450")
        self.caminho_pasta = ""
        self.lbl_title = tk.Label(root, text="AutoScanExtractor", font=("Helvetica", 16, "bold"))
        self.lbl_title.pack(pady=10)
        self.frame_controles = tk.Frame(root, padx=10, pady=10)
        self.frame_controles.pack(fill=tk.X)
        self.btn_selecionar = tk.Button(self.frame_controles, text="1. Selecionar Pasta com Imagens e PDFs", command=self.selecionar_pasta)
        self.btn_selecionar.pack(fill=tk.X, pady=5)
        self.lbl_pasta = tk.Label(self.frame_controles, text="Nenhuma pasta selecionada.", bg="white", relief="sunken", anchor="w", padx=5)
        self.lbl_pasta.pack(fill=tk.X, pady=2)
        self.btn_iniciar = tk.Button(self.frame_controles, text="2. Iniciar Processamento", command=self.iniciar_processamento, state="disabled", bg="lightgray")
        self.btn_iniciar.pack(fill=tk.X, pady=10)
        self.frame_log = tk.Frame(root, padx=10, pady=10)
        self.frame_log.pack(fill=tk.BOTH, expand=True)
        self.lbl_log = tk.Label(self.frame_log, text="Log de Atividades:", font=("Helvetica", 10, "bold"))
        self.lbl_log.pack(anchor="w")
        self.log_area = scrolledtext.ScrolledText(self.frame_log, height=10, state="disabled")
        self.log_area.pack(fill=tk.BOTH, expand=True)
    def log(self, message):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")
        self.root.update_idletasks()
    def selecionar_pasta(self):
        caminho = filedialog.askdirectory(title="Selecione a pasta com as imagens e PDFs")
        if caminho:
            self.caminho_pasta = caminho
            self.lbl_pasta.config(text=f"Pasta: {self.caminho_pasta}")
            self.btn_iniciar.config(state="normal", bg="lawn green")
            self.log(f"Pasta selecionada: {self.caminho_pasta}")
    def iniciar_processamento(self):
        if not self.caminho_pasta:
            messagebox.showwarning("Atenção", "Por favor, selecione uma pasta primeiro.")
            return
        self.btn_selecionar.config(state="disabled")
        self.btn_iniciar.config(state="disabled", text="Processando...", bg="lightgray")
        self.log("\n--- INICIANDO PROCESSAMENTO (V5.6 Final) ---") # <--- Log V5.6
        thread = threading.Thread(target=self.processar_arquivos)
        thread.start()
    def processar_arquivos(self):
        dados_totais = []
        formatos_suportados_img = ('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')
        formatos_suportados_pdf = ('.pdf')
        try:
            arquivos_na_pasta = os.listdir(self.caminho_pasta)
            arquivos_para_processar = [ f for f in arquivos_na_pasta if (f.lower().endswith(formatos_suportados_img) or f.lower().endswith(formatos_suportados_pdf)) and not f.startswith('~$') ]
            if not arquivos_para_processar:
                self.log("AVISO: Nenhum arquivo compatível (.pdf, .png, .jpg...) encontrado.")
                self.finalizar_processamento(sucesso=False)
                return
            self.log(f"Encontrados {len(arquivos_para_processar)} arquivos compatíveis.")
            for nome_arquivo in arquivos_para_processar: # Itera apenas nos arquivos filtrados
                caminho_completo = os.path.join(self.caminho_pasta, nome_arquivo)
                dados = []
                erro = None
                self.log(f"Processando '{nome_arquivo}'...")
                if nome_arquivo.lower().endswith(formatos_suportados_img): dados, erro = extrair_dados_da_imagem(caminho_completo)
                elif nome_arquivo.lower().endswith(formatos_suportados_pdf): dados, erro = processar_pdf(caminho_completo)
                if erro: self.log(f"  > ERRO ao processar '{nome_arquivo}': {erro}")
                elif dados:
                    dados_totais.extend(dados)
                    self.log(f"  > Sucesso! {len(dados)} registro(s) potencial(is) encontrado(s).")
                else: self.log(f"  > Nenhum dado relevante encontrado em '{nome_arquivo}'.")
            dados_finais = [d for d in dados_totais if any(v != 'Não encontrado' for k, v in d.items() if k != 'Arquivo_Origem')]
            if dados_finais:
                nome_planilha_saida = "dados_boletos_consolidados.xlsx"
                caminho_planilha = os.path.join(self.caminho_pasta, nome_planilha_saida)
                self.log("\nConsolidando dados e criando planilha Excel...")
                try:
                    df = pd.DataFrame(dados_finais)
                    colunas_ordenadas = ['Arquivo_Origem', 'Vencimento', 'Pagador', 'Beneficiário', 'Codigo_Barras']
                    colunas_finais = [col for col in colunas_ordenadas if col in df.columns]
                    df_sorted = df[colunas_finais]
                    df_sorted.to_excel(caminho_planilha, index=False)
                    self.log(f"SUCESSO! Planilha criada em: {caminho_planilha}")
                    messagebox.showinfo("Processo Concluído", f"Planilha criada com sucesso em:\n{caminho_planilha}")
                    self.finalizar_processamento(sucesso=True)
                except Exception as ex_save:
                     self.log(f"ERRO AO SALVAR PLANILHA: {ex_save}")
                     messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar a planilha Excel:\n{ex_save}")
                     self.finalizar_processamento(sucesso=False)

            else:
                self.log("\nProcessamento finalizado. Nenhum dado de boleto válido foi encontrado em nenhum arquivo.")
                messagebox.showinfo("Processo Concluído", "Nenhum dado de boleto válido foi encontrado para gerar a planilha.")
                self.finalizar_processamento(sucesso=False)
        except Exception as e:
            self.log(f"\n--- ERRO CRÍTICO NO PROCESSAMENTO ---")
            self.log(str(e))
            import traceback
            self.log(traceback.format_exc()) # Log completo do erro
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado:\n{e}")
            self.finalizar_processamento(sucesso=False)
    def finalizar_processamento(self, sucesso=True):
        self.btn_selecionar.config(state="normal")
        self.btn_iniciar.config(state="normal", text="2. Iniciar Processamento", bg="lawn green" if self.caminho_pasta else "lightgray")
        if not self.caminho_pasta: self.btn_iniciar.config(state="disabled")
        self.log("--- FIM DO PROCESSAMENTO ---")
# --- Ponto de Entrada Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()