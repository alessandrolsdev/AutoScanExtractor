import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os
import pytesseract
import pandas as pd
from PIL import Image
import re
import threading
import sys # <--- IMPORTADO NOVO

# --- FUNÇÃO HELPER PARA ENCONTRAR ARQUIVOS NO .EXE ---
# Esta função mágica descobre o caminho dos arquivos 
# (tanto no seu PC de dev quanto dentro do .exe compilado)
def resource_path(relative_path):
    """ Pega o caminho absoluto para o recurso, funciona em dev e no PyInstaller """
    try:
        # PyInstaller cria uma pasta temp e guarda o caminho em _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# --- CONFIGURAÇÃO (MODIFICADA PARA O PYINSTALLER) ---

# 1. Aponta para o executável do Tesseract que VAMOS EMPACOTAR
#    (Ele vai procurar por 'tesseract.exe' na mesma pasta que o .exe)
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


# --- LÓGICA DE EXTRAÇÃO (Exatamente como antes) ---

def extrair_dados_da_imagem(caminho_imagem):
    """
    Pega o caminho de uma imagem, extrai o texto com OCR e retorna
    uma lista de dicionários com os dados estruturados.
    """
    try:
        # AQUI USAMOS O 'lang="por"' que depende do 'tessdata_path' que configuramos
        texto_extraido = pytesseract.image_to_string(Image.open(caminho_imagem), lang='por')
        
        dados_da_imagem = []
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
                    
                    dados_da_imagem.append({
                        'Dia': dia_atual,
                        'Refeição': refeicao,
                        'Horário': horario,
                        'Arquivo_Origem': os.path.basename(caminho_imagem) 
                    })
        
        return dados_da_imagem, None # (dados, erro)
        
    except Exception as e:
        return [], str(e)


# --- CLASSE DA APLICAÇÃO (GUI) (Exatamente como antes) ---

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Extrator de Horários v1.0")
        self.root.geometry("600x450") 
        
        self.caminho_pasta = "" 

        self.lbl_title = tk.Label(root, text="AutoScanExtractor", font=("Helvetica", 16, "bold"))
        self.lbl_title.pack(pady=10)

        self.frame_controles = tk.Frame(root, padx=10, pady=10)
        self.frame_controles.pack(fill=tk.X)

        self.btn_selecionar = tk.Button(self.frame_controles, text="1. Selecionar Pasta com Imagens", command=self.selecionar_pasta)
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
        caminho = filedialog.askdirectory(title="Selecione a pasta onde estão as imagens")
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
        
        self.log("\n--- INICIANDO PROCESSAMENTO ---")

        thread = threading.Thread(target=self.processar_arquivos)
        thread.start()

    def processar_arquivos(self):
        dados_totais = []
        formatos_suportados = ('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')
        
        try:
            arquivos_na_pasta = os.listdir(self.caminho_pasta)
            imagens_para_processar = [f for f in arquivos_na_pasta if f.lower().endswith(formatos_suportados)]

            if not imagens_para_processar:
                self.log("AVISO: Nenhuma imagem encontrada na pasta selecionada.")
                self.finalizar_processamento(sucesso=False)
                return

            self.log(f"Encontradas {len(imagens_para_processar)} imagens.")
            
            for nome_arquivo in imagens_para_processar:
                caminho_completo = os.path.join(self.caminho_pasta, nome_arquivo)
                self.log(f"Processando '{nome_arquivo}'...")
                
                dados_imagem, erro = extrair_dados_da_imagem(caminho_completo)
                
                if erro:
                    self.log(f"  > ERRO ao ler '{nome_arquivo}': {erro}")
                elif dados_imagem:
                    dados_totais.extend(dados_imagem)
                    self.log(f"  > Sucesso! {len(dados_imagem)} registros encontrados.")
                else:
                    self.log(f"  > Nenhum dado relevante encontrado em '{nome_arquivo}'.")

            if dados_totais:
                nome_planilha_saida = "dados_consolidados.xlsx"
                caminho_planilha = os.path.join(self.caminho_pasta, nome_planilha_saida)
                
                self.log("\nConsolidando dados e criando planilha Excel...")
                df = pd.DataFrame(dados_totais)
                df.to_excel(caminho_planilha, index=False)
                
                self.log(f"SUCESSO! Planilha criada em: {caminho_planilha}")
                messagebox.showinfo("Processo Concluído", f"Planilha criada com sucesso em:\n{caminho_planilha}")
            else:
                self.log("\nProcessamento finalizado. Nenhum dado foi encontrado em nenhuma imagem.")
                messagebox.showinfo("Processo Concluído", "Nenhum dado foi encontrado para gerar a planilha.")

            self.finalizar_processamento(sucesso=True)

        except Exception as e:
            self.log(f"\n--- ERRO CRÍTICO NO PROCESSAMENTO ---")
            self.log(str(e))
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado:\n{e}")
            self.finalizar_processamento(sucesso=False)

    def finalizar_processamento(self, sucesso=True):
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