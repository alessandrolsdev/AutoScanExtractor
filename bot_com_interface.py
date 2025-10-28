import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import pytesseract
import pandas as pd
from PIL import Image
import re
import threading
import sys
import fitz  # <--- (NOVO) Importamos o PyMuPDF

# --- FUNÇÃO HELPER PARA ENCONTRAR ARQUIVOS NO .EXE ---
# (Exatamente como antes)
def resource_path(relative_path):
    """ Pega o caminho absoluto para o recurso, funciona em dev e no PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- CONFIGURAÇÃO (Exatamente como antes) ---
try:
    tesseract_exe_path = resource_path("tesseract.exe")
    pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path

    # 2. Aponta para a pasta de dados (essencial para o 'por.traineddata')
    #    (Ele vai procurar por uma pasta 'tessdata' ao lado do .exe)
    tessdata_path = resource_path("tessdata")
    os.environ['TESSDATA_PREFIX'] = tessdata_path
except Exception as e:
    # Mostra um erro se não conseguir configurar o Tesseract
    messagebox.showerror("Erro de Inicialização", f"Não foi possível configurar o Tesseract OCR:\n{e}")
    sys.exit(1)


# --- LÓGICA DE EXTRAÇÃO (REATORADA) ---

# (NOVO) - Esta função foi separada da 'extrair_dados_da_imagem'
# Agora ela só tem uma responsabilidade: interpretar o texto.
def parse_ocr_text(texto_extraido, nome_arquivo_origem):
    """Pega o texto cru do OCR e o nome do arquivo, retorna uma lista de dados."""
    dados_encontrados = []
    dia_atual = None
    dias_da_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]

    for linha in texto_extraido.splitlines():
        linha_limpa = linha.strip()
        
        if not linha_limpa:
            continue

        dia_encontrado = False
        for dia in dias_da_semana:
            if linha_limpa.startswith(dia):
                dia_atual = dia
                dia_encontrado = True
                linha_limpa = linha_limpa.replace(dia, "").strip()
                if not linha_limpa:
                    break 
        
        if (not dia_encontrado or (dia_encontrado and linha_limpa)) and dia_atual:
            match_horario = re.search(r'(\d{2}:\d{2})', linha_limpa)
            if match_horario:
                horario = match_horario.group(1)
                refeicao = linha_limpa[:match_horario.start()].strip()
                
                dados_encontrados.append({
                    'Dia': dia_atual,
                    'Refeição': refeicao,
                    'Horário': horario,
                    'Arquivo_Origem': nome_arquivo_origem
                })
    return dados_encontrados

# (MODIFICADO) - Esta função agora só cuida de IMAGENS e chama o parser
def extrair_dados_da_imagem(caminho_imagem):
    """
    Pega o caminho de uma IMAGEM, roda o OCR, e passa o texto para o parser.
    """
    try:
        nome_arquivo = os.path.basename(caminho_imagem)
        img = Image.open(caminho_imagem)
        texto_extraido = pytesseract.image_to_string(img, lang='por')
        
        dados_da_imagem = parse_ocr_text(texto_extraido, nome_arquivo)
        
        return dados_da_imagem, None  # (dados, erro)
        
    except Exception as e:
        return [], str(e)

# (NOVO) - Esta é a nossa nova função para lidar com PDFs
def processar_pdf(caminho_pdf):
    """
    Pega o caminho de um PDF, converte cada página em imagem,
    roda o OCR em cada uma, e passa o texto para o parser.
    """
    dados_do_pdf = []
    nome_arquivo = os.path.basename(caminho_pdf)
    
    try:
        # Abre o documento PDF
        doc = fitz.open(caminho_pdf)
        
        # Itera por cada página do PDF
        for num_pagina, page in enumerate(doc):
            nome_origem = f"{nome_arquivo} (pág. {num_pagina + 1})"
            
            # Converte a página em uma imagem de alta resolução (300 DPI)
            # Isso é crucial para a precisão do Tesseract
            pix = page.get_pixmap(dpi=300)
            
            # Converte os bytes da imagem do fitz para um objeto de imagem PIL
            if pix.alpha:
                img_data = pix.samples
                pil_image = Image.frombytes("RGBA", [pix.width, pix.height], img_data)
            else:
                img_data = pix.samples
                pil_image = Image.frombytes("RGB", [pix.width, pix.height], img_data)

            # Roda o Tesseract OCR na imagem da página (em memória)
            texto_extraido = pytesseract.image_to_string(pil_image, lang='por')
            
            # Usa a MESMA função de parsing que usamos para imagens
            dados_pagina = parse_ocr_text(texto_extraido, nome_origem)
            
            if dados_pagina:
                dados_do_pdf.extend(dados_pagina)
        
        doc.close()
        return dados_do_pdf, None # (dados, erro)

    except Exception as e:
        return [], f"{nome_arquivo}: {str(e)}"


# --- CLASSE DA APLICAÇÃO (GUI) ---

class App:
    # (O __init__ e outras funções da GUI continuam iguais)
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Extrator de Horários v2.0 (com PDF)") # <--- (MODIFICADO) Título
        self.root.geometry("600x450") 
        
        self.caminho_pasta = "" 

        self.lbl_title = tk.Label(root, text="AutoScanExtractor", font=("Helvetica", 16, "bold"))
        self.lbl_title.pack(pady=10)

        self.frame_controles = tk.Frame(root, padx=10, pady=10)
        self.frame_controles.pack(fill=tk.X)

        self.btn_selecionar = tk.Button(self.frame_controles, text="1. Selecionar Pasta com Imagens e PDFs", command=self.selecionar_pasta) # <--- (MODIFICADO) Texto
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
        caminho = filedialog.askdirectory(title="Selecione a pasta com as imagens e PDFs") # <--- (MODIFICADO) Texto
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
        self.log("\n--- INICIANDO PROCESSAMENTO (V2.0) ---")
        
        thread = threading.Thread(target=self.processar_arquivos)
        thread.start()

    # (MODIFICADO) - Esta é a mudança mais importante na classe
    # Agora ela decide qual função de extração chamar
    def processar_arquivos(self):
        """ A função de trabalho que varre a pasta e processa os arquivos. """
        dados_totais = []
        # Adicionamos '.pdf' aos formatos suportados
        formatos_suportados_img = ('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')
        formatos_suportados_pdf = ('.pdf')

        try:
            arquivos_na_pasta = os.listdir(self.caminho_pasta)
            
            # Filtra a lista de arquivos
            arquivos_para_processar = [
                f for f in arquivos_na_pasta 
                if f.lower().endswith(formatos_suportados_img) or f.lower().endswith(formatos_suportados_pdf)
            ]

            if not arquivos_para_processar:
                self.log("AVISO: Nenhum arquivo compatível (.pdf, .png, .jpg...) encontrado.")
                self.finalizar_processamento(sucesso=False)
                return

            self.log(f"Encontrados {len(arquivos_para_processar)} arquivos compatíveis.")
            
            for nome_arquivo in arquivos_para_processar:
                caminho_completo = os.path.join(self.caminho_pasta, nome_arquivo)
                dados = []
                erro = None
                
                self.log(f"Processando '{nome_arquivo}'...")

                # Decide qual função chamar baseado na extensão
                if nome_arquivo.lower().endswith(formatos_suportados_img):
                    dados, erro = extrair_dados_da_imagem(caminho_completo)
                elif nome_arquivo.lower().endswith(formatos_suportados_pdf):
                    dados, erro = processar_pdf(caminho_completo)

                # Loga o resultado
                if erro:
                    self.log(f"  > ERRO ao processar '{nome_arquivo}': {erro}")
                elif dados:
                    dados_totais.extend(dados)
                    self.log(f"  > Sucesso! {len(dados)} registros encontrados.")
                else:
                    self.log(f"  > Nenhum dado relevante encontrado em '{nome_arquivo}'.")

            # Após o loop, salvar a planilha (exatamente como antes)
            if dados_totais:
                nome_planilha_saida = "dados_consolidados.xlsx"
                caminho_planilha = os.path.join(self.caminho_pasta, nome_planilha_saida)
                
                self.log("\nConsolidando dados e criando planilha Excel...")
                df = pd.DataFrame(dados_totais)
                # Ordena os dados (bônus!)
                df_sorted = df.sort_values(by=['Arquivo_Origem', 'Dia'])
                df_sorted.to_excel(caminho_planilha, index=False)
                
                self.log(f"SUCESSO! Planilha criada em: {caminho_planilha}")
                messagebox.showinfo("Processo Concluído", f"Planilha criada com sucesso em:\n{caminho_planilha}")
            else:
                self.log("\nProcessamento finalizado. Nenhum dado foi encontrado em nenhum arquivo.")
                messagebox.showinfo("Processo Concluído", "Nenhum dado foi encontrado para gerar a planilha.")

            self.finalizar_processamento(sucesso=True)

        except Exception as e:
            self.log(f"\n--- ERRO CRÍTICO NO PROCESSAMENTO ---")
            self.log(str(e))
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado:\n{e}")
            self.finalizar_processamento(sucesso=False)

    def finalizar_processamento(self, sucesso=True):
        # (Exatamente como antes)
        self.btn_selecionar.config(state="normal")
        self.btn_iniciar.config(state="normal", text="2. Iniciar Processamento", bg="lawn green" if self.caminho_pasta else "lightgray")
        if not self.caminho_pasta:
            self.btn_iniciar.config(state="disabled")
        self.log("--- FIM DO PROCESSAMENTO ---")

# --- Ponto de Entrada Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()