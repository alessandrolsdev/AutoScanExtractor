# -*- coding: utf-8 -*-
"""
gui.py

Contém toda a lógica da interface gráfica (GUI) com Tkinter.
Inclui a classe 'App' (a janela) e a classe 'ExtractorService'
(que gerencia a thread de processamento).
"""

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import os
import pandas as pd
from PIL import Image, ImageTk
import threading
import sys
import dataclasses # Necessário para converter nosso BoletoData de volta para um dict

# Importações de nossos módulos
from config import resource_path # Importa a função de setup
import file_processor # Importa o módulo que lida com arquivos
from extraction_logic import BoletoParser, ExtractionError, OCRError, LayoutNaoReconhecidoError # Importa o Parser e os Erros

# --- NOVA CLASSE DE SERVIÇO (BOAS PRÁTICAS) ---
class ExtractorService:
    """
    Esta classe cuida de toda a lógica de processamento de arquivos.
    Ela é executada em uma thread separada e se comunica com a GUI
    através de callbacks (on_log, on_progress, on_complete).
    """
    def __init__(self, on_log, on_progress, on_complete):
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_complete = on_complete
        
        self.cancel_processing = False
        self.arquivos_para_processar = []
        self.output_filepath = ""
        
        # O Parser agora é um membro da classe de serviço!
        # Criamos uma instância dele aqui.
        self.parser = BoletoParser() 

    def start_processing(self, arquivos_para_processar, output_filepath):
        """Inicia o processamento em uma nova thread."""
        self.cancel_processing = False
        self.arquivos_para_processar = list(arquivos_para_processar)
        self.output_filepath = output_filepath
        
        thread = threading.Thread(target=self._processar_arquivos_thread)
        thread.daemon = True
        thread.start()

    def request_cancel(self):
        """Sinaliza para a thread de processamento que ela deve parar."""
        self.cancel_processing = True

    def _processar_arquivos_thread(self):
        """
        Função executada na thread separada.
        *** ATUALIZADA PARA USAR O NOVO file_processor E BoletoData ***
        """
        # Agora armazena objetos BoletoData
        dados_totais = [] 
        arquivos_ja_processados = set()

        try:
            # --- Lógica para Anexar Dados (Append) ---
            df_existente = pd.DataFrame()
            if os.path.exists(self.output_filepath):
                try:
                    self.on_log(f"Encontrada planilha existente. Carregando dados...")
                    df_existente = pd.read_excel(self.output_filepath)
                    if 'Arquivo_Origem' in df_existente.columns:
                        arquivos_ja_processados = set(df_existente['Arquivo_Origem'].dropna())
                    self.on_log(f"Carregados {len(df_existente)} registros existentes.")
                    if arquivos_ja_processados:
                        self.on_log(f"{len(arquivos_ja_processados)} arquivos na planilha serão ignorados se re-selecionados.")
                except Exception as e:
                    self.on_log(f"AVISO: Não foi possível ler a planilha existente em '{self.output_filepath}'. Ela pode estar corrompida ou aberta. Uma nova planilha será criada. Erro: {e}")
                    df_existente = pd.DataFrame()
            
            total_arquivos = len(self.arquivos_para_processar)
            self.on_log(f"Processando {total_arquivos} arquivo(s)...")

            arquivos_processados_nesta_sessao = 0
            arquivos_ignorados_duplicados = 0

            for i, caminho_completo in enumerate(self.arquivos_para_processar):
                
                if self.cancel_processing:
                    self.on_log("PROCESSAMENTO CANCELADO PELO USUÁRIO.")
                    self.on_complete(sucesso=False, cancelado=True)
                    return

                nome_arquivo = os.path.basename(caminho_completo)

                # --- Pular Duplicatas ---
                if nome_arquivo in arquivos_ja_processados or f"{nome_arquivo} (Digital)" in arquivos_ja_processados or f"{nome_arquivo} (OCR)" in arquivos_ja_processados:
                    self.on_log(f"Ignorando '{nome_arquivo}' (Já processado).")
                    arquivos_ignorados_duplicados += 1
                    self.on_progress((i + 1) * 100 / total_arquivos)
                    continue
                
                self.on_log(f"Processando '{nome_arquivo}' ({i+1}/{total_arquivos})...")
                
                # --- *** NOVO BLOCO DE LÓGICA *** ---
                try:
                    dados = None
                    # Chama as funções do 'file_processor', passando o parser
                    if nome_arquivo.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
                        dados = file_processor.extrair_dados_da_imagem(caminho_completo, self.parser)
                    elif nome_arquivo.lower().endswith('.pdf'):
                        dados = file_processor.processar_pdf(caminho_completo, self.parser)
                    else:
                        self.on_log(f"  > Ignorando arquivo não suportado: '{nome_arquivo}'")
                        continue

                    # Se 'dados' for retornado, é um objeto BoletoData
                    if dados:
                        dados_totais.append(dados)
                        arquivos_processados_nesta_sessao += 1
                        self.on_log(f"  > Sucesso! (Valor: {dados.valor_documento}, Venc: {dados.vencimento})")
                    else:
                        # Isso não deve acontecer, pois exceções são levantadas, mas é um seguro.
                        self.on_log(f"  > Nenhum dado relevante encontrado em '{nome_arquivo}'.")

                # Captura os erros específicos de extração
                except (ExtractionError, OCRError, LayoutNaoReconhecidoError) as e:
                    self.on_log(f"  > ERRO ao processar '{nome_arquivo}': {e}")
                # Captura erros inesperados do processador
                except Exception as e:
                    self.on_log(f"  > ERRO CRÍTICO INESPERADO em '{nome_arquivo}': {e}")
                    import traceback
                    self.on_log(traceback.format_exc())
                # --- *** FIM DO NOVO BLOCO *** ---

                self.on_progress((i + 1) * 100 / total_arquivos)

            # --- Consolidação e Salvamento no Excel ---
            
            # Filtra apenas os boletos que tiveram dados úteis extraídos
            dados_finais_novos = [
                d for d in dados_totais 
                if any(v != 'Não encontrado' for k, v in dataclasses.asdict(d).items() if k != 'arquivo_origem')
            ]

            if dados_finais_novos or not df_existente.empty:
                caminho_planilha = self.output_filepath
                self.on_log("\nConsolidando dados e atualizando planilha Excel...")
                
                try:
                    # Converte a lista de objetos BoletoData para uma lista de dicts
                    lista_de_dicts_novos = [dataclasses.asdict(d) for d in dados_finais_novos]
                    df_novos = pd.DataFrame(lista_de_dicts_novos)
                    
                    df_final_combinado = pd.concat([df_existente, df_novos], ignore_index=True)

                    # Renomeia colunas de volta para o padrão original da planilha (se necessário)
                    # (O seu já estava bom, mas aqui é onde faríamos)
                    # ex: df_final_combinado = df_final_combinado.rename(columns={'valor_documento': 'Valor_Documento'})
                    colunas_ordenadas = ['arquivo_origem', 'vencimento', 'pagador', 'beneficiario', 'valor_documento', 'codigo_barras']
                    # Garante que os nomes no DF correspondam aos da dataclass
                    colunas_ordenadas_renomeadas = ['Arquivo_Origem', 'Vencimento', 'Pagador', 'Beneficiário', 'Valor_Documento', 'Codigo_Barras']
                    
                    # Renomeia as colunas do DataFrame para o formato "Bonito" da planilha
                    rename_map = dict(zip(colunas_ordenadas, colunas_ordenadas_renomeadas))
                    df_final_combinado = df_final_combinado.rename(columns=rename_map)

                    colunas_existentes = [col for col in colunas_ordenadas_renomeadas if col in df_final_combinado.columns]
                    df_sorted = df_final_combinado[colunas_existentes]

                    if 'Codigo_Barras' in df_sorted.columns:
                        df_sorted = df_sorted.drop_duplicates(subset=['Codigo_Barras'], keep='last')

                    df_sorted.to_excel(caminho_planilha, index=False)

                    total_final = len(df_sorted)
                    novos_adicionados = len(dados_finais_novos)
                    msg_sucesso = (f"SUCESSO! Planilha atualizada em: {caminho_planilha}\n"
                                   f"Total de registros na planilha: {total_final}\n"
                                   f"Novos registros adicionados: {novos_adicionados}\n"
                                   f"Arquivos ignorados (duplicados): {arquivos_ignorados_duplicados}")

                    self.on_log(msg_sucesso)
                    messagebox.showinfo("Processo Concluído", msg_sucesso)
                    self.on_complete(sucesso=True)

                except PermissionError:
                    self.on_log(f"ERRO DE PERMISSÃO AO SALVAR PLANILHA: {caminho_planilha}")
                    messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar a planilha Excel:\n{caminho_planilha}\n\nVerifique se o arquivo não está aberto em outro programa.")
                    self.on_complete(sucesso=False)
                except Exception as ex_save:
                    self.on_log(f"ERRO AO SALVAR PLANILHA: {ex_save}")
                    messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar a planilha Excel:\n{ex_save}")
                    self.on_complete(sucesso=False)

            else:
                self.on_log("\nProcessamento finalizado. Nenhum dado novo foi encontrado em nenhum arquivo.")
                messagebox.showinfo("Processo Concluído", "Nenhum dado novo foi encontrado para adicionar à planilha.")
                self.on_complete(sucesso=False)

        except Exception as e:
            self.on_log(f"\n--- ERRO CRÍTICO NO PROCESSAMENTO ---")
            self.on_log(str(e))
            import traceback
            self.on_log(traceback.format_exc())
            messagebox.showerror("Erro Crítico", f"Ocorreu um erro inesperado:\n{e}")
            self.on_complete(sucesso=False)


# --- CLASSE DA APLICAÇÃO (GUI V23.0 - Com Ícones) ---
class App:
    def __init__(self, root):
        """Construtor da classe App, inicializa a interface gráfica."""
        self.root = root
        self.root.title("AutoScanExtractor V23.0")
        self.root.geometry("650x600")
        self.root.minsize(600, 550)

        try:
            self.root.iconbitmap(resource_path('assets/meu_novo_icone.ico'))
        except Exception as e:
            print(f"Aviso: Não foi possível carregar 'assets/app_icon.ico': {e}")

        self.arquivos_para_processar = []
        self.output_filepath = ""
        self.service = None
        self.show_logs_var = tk.BooleanVar(value=True)

        try:
            self.icon_folder = ImageTk.PhotoImage(Image.open(resource_path("assets/folder.png")).resize((20, 20), Image.LANCZOS))
            self.icon_excel = ImageTk.PhotoImage(Image.open(resource_path("assets/excel_output.png")).resize((20, 20), Image.LANCZOS))
            self.icon_play = ImageTk.PhotoImage(Image.open(resource_path("assets/play_button.png")).resize((20, 20), Image.LANCZOS))
            self.icon_cancel = ImageTk.PhotoImage(Image.open(resource_path("assets/cancel_button.png")).resize((20, 20), Image.LANCZOS))
            self.icon_open_excel = ImageTk.PhotoImage(Image.open(resource_path("assets/open_excel.png")).resize((20, 20), Image.LANCZOS))
            self.icon_open_folder = ImageTk.PhotoImage(Image.open(resource_path("assets/open_folder.png")).resize((20, 20), Image.LANCZOS))
        except Exception as e:
            print(f"Aviso: Não foi possível carregar ícones dos botões. Verifique os arquivos PNG. Erro: {e}")
            self.icon_folder, self.icon_excel, self.icon_play, self.icon_cancel, self.icon_open_excel, self.icon_open_folder = (None,) * 6

        self.style = ttk.Style()
        self.style.configure("Success.TButton", font=("Helvetica", 10, "bold"), background="lawn green", foreground="black")
        self.style.map("Success.TButton", background=[('active', 'lime green')], foreground=[('active', 'black')])
        self.style.configure("Danger.TButton", font=("Helvetica", 10, "bold"), background="tomato", foreground="black")
        self.style.map("Danger.TButton", background=[('active', 'red')], foreground=[('active', 'black')])
        self.style.configure("TButton", font=("Helvetica", 10))
        self.style.configure("TLabel", font=("Helvetica", 10))
        self.style.configure("Bold.TLabel", font=("Helvetica", 10, "bold"))
        self.style.configure("Header.TLabel", font=("Helvetica", 16, "bold"))
        self.style.configure("TCheckbutton", font=("Helvetica", 10))
        self.style.configure("TLabelFrame.Label", font=("Helvetica", 10, "bold"))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1) 

        self.lbl_title = ttk.Label(root, text="AutoScanExtractor", style="Header.TLabel", anchor="center")
        self.lbl_title.grid(row=0, column=0, pady=10, padx=10, sticky="ew")
        
        self.frame_controles = ttk.Frame(root, padding=10)
        self.frame_controles.grid(row=1, column=0, sticky="nsew")
        self.frame_controles.columnconfigure(0, weight=1)
        self.frame_controles.rowconfigure(3, weight=1)

        # --- Passo 1: Seleção de Entrada ---
        self.lf_passo1 = ttk.LabelFrame(self.frame_controles, text="Passo 1: Selecionar Arquivos de Entrada")
        self.lf_passo1.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.lf_passo1.columnconfigure(0, weight=1)
        self.btn_selecionar_entrada = ttk.Button(self.lf_passo1, text=" Selecionar Arquivos ou Pasta", command=self.selecionar_entrada, image=self.icon_folder, compound=tk.LEFT)
        self.btn_selecionar_entrada.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        self.lbl_input = ttk.Label(self.lf_passo1, text="Nenhum arquivo/pasta selecionado.", relief="sunken", anchor="w", padding=5, wraplength=550, justify=tk.LEFT)
        self.lbl_input.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10), ipady=5)

        # --- Passo 2: Seleção de Saída ---
        self.lf_passo2 = ttk.LabelFrame(self.frame_controles, text="Passo 2: Definir Planilha de Saída")
        self.lf_passo2.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.lf_passo2.columnconfigure(0, weight=1)
        self.btn_selecionar_saida = ttk.Button(self.lf_passo2, text=" Definir Local da Planilha (.xlsx)", command=self.selecionar_planilha_saida, image=self.icon_excel, compound=tk.LEFT)
        self.btn_selecionar_saida.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        self.lbl_output = ttk.Label(self.lf_passo2, text="Nenhuma planilha de saída definida.", relief="sunken", anchor="w", padding=5, wraplength=550, justify=tk.LEFT)
        self.lbl_output.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10), ipady=5)

        # --- Passo 3: Iniciar e Progresso ---
        self.lf_passo3 = ttk.LabelFrame(self.frame_controles, text="Passo 3: Processar")
        self.lf_passo3.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.lf_passo3.columnconfigure(0, weight=1)
        self.btn_iniciar = ttk.Button(self.lf_passo3, text=" Iniciar Processamento", command=self.iniciar_processamento, state="disabled", image=self.icon_play, compound=tk.LEFT)
        self.btn_iniciar.grid(row=0, column=0, sticky="ew", padx=10, pady=10, ipady=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.lf_passo3, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

        # --- Log de Atividades (Opcional) ---
        self.frame_log = ttk.Frame(self.frame_controles)
        self.frame_log.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        self.frame_log.columnconfigure(0, weight=1)
        self.frame_log.rowconfigure(1, weight=1)
        self.frame_log_toggle = ttk.Frame(self.frame_log)
        self.frame_log_toggle.grid(row=0, column=0, sticky="ew")
        self.lbl_log = ttk.Label(self.frame_log_toggle, text="Log de Atividades:", style="Bold.TLabel")
        self.lbl_log.pack(side=tk.LEFT, padx=(10, 0))
        self.log_check = ttk.Checkbutton(self.frame_log_toggle, text="Exibir logs detalhados", variable=self.show_logs_var, command=self.toggle_log_visibility)
        self.log_check.pack(side=tk.LEFT, padx=10)
        self.log_area_frame = ttk.Frame(self.frame_log)
        self.log_area_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.log_area_frame.rowconfigure(0, weight=1)
        self.log_area_frame.columnconfigure(0, weight=1)
        self.log_area = scrolledtext.ScrolledText(self.log_area_frame, height=6, state="disabled", font=("Courier New", 9))
        self.log_area.grid(row=0, column=0, sticky="nsew")

        # --- Botões de Resultado ---
        self.frame_resultado = ttk.Frame(self.frame_controles)
        self.frame_resultado.grid(row=4, column=0, sticky="ew", padx=10)
        self.frame_resultado.columnconfigure(0, weight=1)
        self.frame_resultado.columnconfigure(1, weight=1)
        self.btn_abrir_planilha = ttk.Button(self.frame_resultado, text=" Abrir Planilha", state="disabled", command=self.abrir_planilha, image=self.icon_open_excel, compound=tk.LEFT)
        self.btn_abrir_planilha.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_abrir_pasta = ttk.Button(self.frame_resultado, text=" Abrir Pasta de Saída", state="disabled", command=self.abrir_pasta_saida, image=self.icon_open_folder, compound=tk.LEFT)
        self.btn_abrir_pasta.grid(row=0, column=1, sticky="ew", padx=(5, 0))
    
    # --- Métodos de Callback e GUI (praticamente intactos) ---
    
    def log(self, message):
        print(message)
        if self.show_logs_var.get():
            self.log_area.config(state="normal")
            self.log_area.insert(tk.END, message + "\n")
            self.log_area.see(tk.END)
            self.log_area.config(state="disabled")
        self.root.update_idletasks()
        
    def update_progress(self, value):
        self.progress_var.set(value)
        self.root.update_idletasks()

    def toggle_log_visibility(self):
        if self.show_logs_var.get():
            self.log_area_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        else:
            self.log_area_frame.grid_forget()

    def verificar_estado_iniciar(self):
        if self.arquivos_para_processar and self.output_filepath:
            self.btn_iniciar.config(state="normal", style="Success.TButton", image=self.icon_play, text=" Iniciar Processamento")
            self.log("Tudo pronto! Clique em 'Iniciar Processamento'.")
        else:
            self.btn_iniciar.config(state="disabled", style="TButton", image=self.icon_play, text=" Iniciar Processamento")

    def selecionar_entrada(self):
        tipos_arquivo = [
            ("Arquivos Suportados", "*.pdf *.png *.jpg *.jpeg *.tiff *.bmp *.gif"),
            ("Todos os Arquivos", "*.*")
        ]
        arquivos = filedialog.askopenfilenames(title="Selecione um ou mais arquivos", filetypes=tipos_arquivo)
        if arquivos:
            self.arquivos_para_processar = list(arquivos)
            self.lbl_input.config(text=f"{len(self.arquivos_para_processar)} arquivo(s) selecionado(s).")
            self.log(f"{len(self.arquivos_para_processar)} arquivo(s) selecionado(s).")
            for f in self.arquivos_para_processar:
                self.log(f"  > {os.path.basename(f)}")
            self.verificar_estado_iniciar()
            return
        if messagebox.askyesno("Selecionar Pasta", "Nenhum arquivo selecionado. Deseja selecionar uma pasta inteira?"):
            self.selecionar_pasta()
        else:
            self.log("Seleção de entrada cancelada.")

    def selecionar_pasta(self):
        caminho = filedialog.askdirectory(title="Selecione a pasta onde estão os arquivos")
        if not caminho:
            return
        self.arquivos_para_processar = []
        formatos_suportados = ('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif', '.pdf')
        try:
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
        caminho_saida = filedialog.asksaveasfilename(
            title="Salvar planilha como...",
            defaultextension=".xlsx",
            filetypes=[("Planilha Excel", "*.xlsx")]
        )
        if not caminho_saida:
            return
        self.output_filepath = caminho_saida
        self.lbl_output.config(text=f"Planilha será salva em:\n{self.output_filepath}")
        self.log(f"Planilha de saída definida para: {self.output_filepath}")
        self.verificar_estado_iniciar()

    def solicitar_cancelamento(self):
        if self.service and messagebox.askyesno("Cancelar", "Tem certeza que deseja cancelar o processamento?"):
            self.service.request_cancel()
            self.log("CANCELAMENTO SOLICITADO... Aguardando o término do arquivo atual.")
            self.btn_iniciar.config(text=" Cancelando...", state="disabled", style="Danger.TButton", image=self.icon_cancel, compound=tk.LEFT)

    def iniciar_processamento(self):
        if not self.arquivos_para_processar or not self.output_filepath:
            messagebox.showwarning("Atenção", "Por favor, selecione os arquivos de entrada E o local da planilha de saída.")
            return
        
        self.btn_selecionar_entrada.config(state="disabled")
        self.btn_selecionar_saida.config(state="disabled")
        self.btn_iniciar.config(text=" Processando... (Cancelar)", style="Danger.TButton", command=self.solicitar_cancelamento, state="normal", image=self.icon_cancel, compound=tk.LEFT)
        self.btn_abrir_planilha.config(state="disabled")
        self.btn_abrir_pasta.config(state="disabled")
        self.progress_var.set(0)

        self.log(f"\n--- INICIANDO PROCESSAMENTO (V23.0 Híbrido Refatorado) ---")

        self.service = ExtractorService(
            on_log=self.log,
            on_progress=self.update_progress,
            on_complete=self.finalizar_processamento
        )
        self.service.start_processing(self.arquivos_para_processar, self.output_filepath)
        
    def finalizar_processamento(self, sucesso=True, cancelado=False):
        self.btn_selecionar_entrada.config(state="normal")
        self.btn_selecionar_saida.config(state="normal")
        self.btn_iniciar.config(text=" Iniciar Processamento", command=self.iniciar_processamento, image=self.icon_play, compound=tk.LEFT)
        self.verificar_estado_iniciar()

        if sucesso:
            self.btn_abrir_planilha.config(state="normal")
            self.btn_abrir_pasta.config(state="normal")
        if not cancelado:
            self.log("--- FIM DO PROCESSAMENTO ---")

        self.progress_var.set(0)
        self.service = None
        self.root.update_idletasks()

    def abrir_planilha(self):
        if self.output_filepath:
            try:
                os.startfile(self.output_filepath)
                self.log(f"Abrindo planilha: {self.output_filepath}")
            except Exception as e:
                self.log(f"ERRO: Não foi possível abrir a planilha: {e}")
                messagebox.showerror("Erro ao Abrir", f"Não foi possível abrir o arquivo:\n{self.output_filepath}\nVerifique se o programa Excel está instalado.")

    def abrir_pasta_saida(self):
        if self.output_filepath:
            try:
                pasta = os.path.dirname(self.output_filepath)
                os.startfile(pasta)
                self.log(f"Abrindo pasta: {pasta}")
            except Exception as e:
                self.log(f"ERRO: Não foi possível abrir a pasta: {e}")
                messagebox.showerror("Erro ao Abrir", f"Não foi possível abrir a pasta:\n{pasta}")