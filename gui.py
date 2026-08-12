# -*- coding: utf-8 -*-
"""
gui.py

Interface gráfica (Tkinter) do AutoScanExtractor.

Duas mudanças estruturais em relação à versão anterior:

    * **Segurança de thread.** O Tkinter só pode ser tocado pela thread
      principal. Antes, a thread de processamento escrevia direto nos widgets e
      abria caixas de diálogo, o que trava ou derruba a janela em lotes
      grandes. Agora a thread só publica mensagens em uma ``queue.Queue``, que
      a thread principal drena com ``root.after``.

    * **Separação de camadas.** Todo o processamento vive em
      ``ServicoExtracao``; esta janela apenas coleta parâmetros e exibe
      resultados.

Inclui também a janela de inspeção, que mostra a página do boleto com um
retângulo colorido sobre cada dado encontrado.
"""

from __future__ import annotations

import logging
import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List, Optional

from PIL import ImageTk

import file_processor
from config import resource_path, setup_tesseract
from extraction_logic import ExtractionError
from extractor_service import ResumoLote, ServicoExtracao
from planilha import PlanilhaError
from version import __version__
from visualizer import anotar_pagina, montar_legenda, redimensionar_para_caber

logger = logging.getLogger(__name__)

TITULO = f"AutoScanExtractor {__version__}"
INTERVALO_DRENAGEM_MS = 100


def abrir_no_sistema(caminho: str) -> None:
    """
    Abre um arquivo ou pasta no gerenciador padrão do sistema.

    ``os.startfile`` só existe no Windows; usá-lo direto quebrava os botões de
    "Abrir" no Linux e no macOS, apesar de o projeto se dizer multiplataforma.
    """
    sistema = platform.system()
    if sistema == "Windows":
        os.startfile(caminho)  # noqa: S606 - API específica do Windows
    elif sistema == "Darwin":
        subprocess.run(["open", caminho], check=False)
    else:
        subprocess.run(["xdg-open", caminho], check=False)


# --------------------------------------------------------------------------- #
# Janela de inspeção visual
# --------------------------------------------------------------------------- #

class JanelaInspecao(tk.Toplevel):
    """
    Mostra a página do boleto com os campos encontrados destacados.

    Responde à pergunta "de onde esse dado saiu?": cada campo ganha um
    retângulo colorido na imagem e uma entrada na legenda com o valor lido e a
    camada que o produziu (linha digitável, texto digital, regex ou posicional).
    """

    LARGURA_LEGENDA = 340

    def __init__(self, master: tk.Misc, caminho_arquivo: str):
        super().__init__(master)
        self.caminho_arquivo = caminho_arquivo
        self.title(f"Inspeção — {os.path.basename(caminho_arquivo)}")
        self.geometry("1150x780")
        self.minsize(900, 600)

        self.fila: queue.Queue = queue.Queue()
        self.resultado = None
        self.pagina_atual = 0
        self._imagem_tk: Optional[ImageTk.PhotoImage] = None
        self._mostrar_rotulos = tk.BooleanVar(value=True)

        self._montar_widgets()
        self._iniciar_processamento()
        self.after(INTERVALO_DRENAGEM_MS, self._drenar_fila)

    # --- Construção da janela ---------------------------------------------

    def _montar_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        barra = ttk.Frame(self, padding=(10, 8))
        barra.grid(row=0, column=0, sticky="ew")
        self.lbl_status = ttk.Label(barra, text="Processando o documento...", style="Bold.TLabel")
        self.lbl_status.pack(side=tk.LEFT)

        self.frame_paginas = ttk.Frame(barra)
        self.frame_paginas.pack(side=tk.RIGHT)
        ttk.Checkbutton(
            barra, text="Mostrar rótulos", variable=self._mostrar_rotulos,
            command=self._redesenhar,
        ).pack(side=tk.RIGHT, padx=12)

        corpo = ttk.Frame(self)
        corpo.grid(row=1, column=0, sticky="nsew")
        corpo.rowconfigure(0, weight=1)
        corpo.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(corpo, background="#3a3a3a", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _evento: self._redesenhar())

        painel = ttk.Frame(corpo, padding=10, width=self.LARGURA_LEGENDA)
        painel.grid(row=0, column=1, sticky="ns")
        painel.grid_propagate(False)

        ttk.Label(painel, text="Dados encontrados", style="Header.TLabel").pack(anchor="w", pady=(0, 8))
        self.frame_legenda = ttk.Frame(painel)
        self.frame_legenda.pack(fill=tk.BOTH, expand=True, anchor="n")

        ttk.Separator(painel, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        self.lbl_dv = ttk.Label(painel, text="", wraplength=self.LARGURA_LEGENDA - 30, justify=tk.LEFT)
        self.lbl_dv.pack(anchor="w")
        ttk.Button(painel, text="Fechar", command=self.destroy).pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

    # --- Processamento em segundo plano -----------------------------------

    def _iniciar_processamento(self) -> None:
        def trabalhar():
            try:
                resultado = file_processor.processar_arquivo(
                    self.caminho_arquivo, coletar_paginas=True
                )
                self.fila.put(("ok", resultado))
            except ExtractionError as erro:
                self.fila.put(("erro", str(erro)))
            except Exception as erro:  # pragma: no cover - proteção da GUI
                logger.exception("Falha inesperada na inspeção")
                self.fila.put(("erro", f"Erro inesperado: {erro}"))

        threading.Thread(target=trabalhar, daemon=True).start()

    def _drenar_fila(self) -> None:
        try:
            while True:
                tipo, carga = self.fila.get_nowait()
                if tipo == "ok":
                    self.resultado = carga
                    self._ao_concluir()
                elif tipo == "erro":
                    self.lbl_status.config(text="Falha ao processar o documento.")
                    messagebox.showerror("Erro na inspeção", carga, parent=self)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(INTERVALO_DRENAGEM_MS, self._drenar_fila)

    def _ao_concluir(self) -> None:
        dados = self.resultado.dados
        self.lbl_status.config(text=f"{dados.arquivo_origem} — {dados.status}")
        self.lbl_dv.config(
            text=(
                "Linha digitável validada pelos dígitos verificadores: "
                "vencimento e valor vieram do próprio código de barras."
                if dados.linha_digitavel_valida
                else "Linha digitável não validada — os dados vieram de leitura do layout."
            )
        )
        self._montar_seletor_paginas()
        self._montar_legenda()
        self._redesenhar()

    def _montar_seletor_paginas(self) -> None:
        for filho in self.frame_paginas.winfo_children():
            filho.destroy()
        paginas = self.resultado.paginas if self.resultado else []
        if len(paginas) <= 1:
            return
        ttk.Label(self.frame_paginas, text="Página:").pack(side=tk.LEFT, padx=(0, 4))
        for pagina in paginas:
            ttk.Button(
                self.frame_paginas, text=str(pagina.numero + 1), width=3,
                command=lambda numero=pagina.numero: self._ir_para_pagina(numero),
            ).pack(side=tk.LEFT, padx=1)

    def _ir_para_pagina(self, numero: int) -> None:
        self.pagina_atual = numero
        self._redesenhar()

    def _montar_legenda(self) -> None:
        for filho in self.frame_legenda.winfo_children():
            filho.destroy()

        for item in montar_legenda(self.resultado.dados):
            linha = ttk.Frame(self.frame_legenda)
            linha.pack(fill=tk.X, pady=4, anchor="w")

            marcador = tk.Canvas(linha, width=14, height=14, highlightthickness=0)
            marcador.create_rectangle(0, 0, 14, 14, fill=item.cor_hex, outline=item.cor_hex)
            marcador.pack(side=tk.LEFT, padx=(0, 8), anchor="n", pady=2)

            texto = ttk.Frame(linha)
            texto.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ttk.Label(texto, text=item.rotulo, style="Bold.TLabel").pack(anchor="w")
            ttk.Label(
                texto, text=item.valor, wraplength=self.LARGURA_LEGENDA - 70, justify=tk.LEFT
            ).pack(anchor="w")
            ttk.Label(
                texto, text=f"{item.origem} · {item.descricao_posicao}",
                foreground="#666666", wraplength=self.LARGURA_LEGENDA - 70, justify=tk.LEFT,
            ).pack(anchor="w")

    # --- Desenho -----------------------------------------------------------

    def _redesenhar(self) -> None:
        if not self.resultado or not self.resultado.paginas:
            return

        pagina = next(
            (p for p in self.resultado.paginas if p.numero == self.pagina_atual),
            self.resultado.paginas[0],
        )
        anotada = anotar_pagina(
            pagina.imagem, self.resultado.dados,
            pagina=pagina.numero, mostrar_rotulos=self._mostrar_rotulos.get(),
        )

        largura = max(self.canvas.winfo_width(), 50)
        altura = max(self.canvas.winfo_height(), 50)
        exibida, _escala = redimensionar_para_caber(anotada, largura - 16, altura - 16)

        self._imagem_tk = ImageTk.PhotoImage(exibida)
        self.canvas.delete("all")
        self.canvas.create_image(largura // 2, altura // 2, image=self._imagem_tk, anchor="center")


# --------------------------------------------------------------------------- #
# Janela principal
# --------------------------------------------------------------------------- #

class App:
    """Janela principal: seleção de arquivos, lote e acesso à inspeção."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(TITULO)
        self.root.geometry("680x660")
        self.root.minsize(620, 580)

        self.arquivos_para_processar: List[str] = []
        self.output_filepath = ""
        self.fila: queue.Queue = queue.Queue()
        self.cancelar_solicitado = threading.Event()
        self.processando = False
        self.show_logs_var = tk.BooleanVar(value=True)

        self._configurar_estilos()
        self._carregar_icones()
        self._montar_widgets()
        self.root.after(INTERVALO_DRENAGEM_MS, self._drenar_fila)

    # --- Aparência ---------------------------------------------------------

    def _configurar_estilos(self) -> None:
        try:
            self.root.iconbitmap(resource_path("assets/meu_novo_icone.ico"))
        except Exception:
            logger.debug("Ícone da janela não pôde ser carregado.")

        self.style = ttk.Style()
        self.style.configure("Success.TButton", font=("Helvetica", 10, "bold"))
        self.style.configure("Danger.TButton", font=("Helvetica", 10, "bold"))
        self.style.configure("TButton", font=("Helvetica", 10))
        self.style.configure("TLabel", font=("Helvetica", 10))
        self.style.configure("Bold.TLabel", font=("Helvetica", 10, "bold"))
        self.style.configure("Header.TLabel", font=("Helvetica", 13, "bold"))
        self.style.configure("TCheckbutton", font=("Helvetica", 10))
        self.style.configure("TLabelFrame.Label", font=("Helvetica", 10, "bold"))

    def _carregar_icones(self) -> None:
        from PIL import Image

        nomes = {
            "folder": "assets/folder.png",
            "excel": "assets/excel_output.png",
            "play": "assets/play_button.png",
            "cancel": "assets/cancel_button.png",
            "open_excel": "assets/open_excel.png",
            "open_folder": "assets/open_folder.png",
        }
        self.icones = {}
        for chave, caminho in nomes.items():
            try:
                imagem = Image.open(resource_path(caminho)).resize((20, 20), Image.LANCZOS)
                self.icones[chave] = ImageTk.PhotoImage(imagem)
            except Exception:
                self.icones[chave] = None
                logger.debug("Ícone não carregado: %s", caminho)

    # --- Layout ------------------------------------------------------------

    def _montar_widgets(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        ttk.Label(self.root, text="AutoScanExtractor", style="Header.TLabel", anchor="center").grid(
            row=0, column=0, pady=10, padx=10, sticky="ew"
        )

        corpo = ttk.Frame(self.root, padding=10)
        corpo.grid(row=1, column=0, sticky="nsew")
        corpo.columnconfigure(0, weight=1)
        corpo.rowconfigure(4, weight=1)

        # Passo 1
        passo1 = ttk.LabelFrame(corpo, text="Passo 1: Selecionar arquivos de entrada")
        passo1.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        passo1.columnconfigure(0, weight=1)
        ttk.Button(
            passo1, text=" Selecionar arquivos ou pasta", command=self.selecionar_entrada,
            image=self.icones["folder"], compound=tk.LEFT,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        self.lbl_input = ttk.Label(
            passo1, text="Nenhum arquivo/pasta selecionado.", relief="sunken",
            anchor="w", padding=5, wraplength=580, justify=tk.LEFT,
        )
        self.lbl_input.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10), ipady=5)

        # Passo 2
        passo2 = ttk.LabelFrame(corpo, text="Passo 2: Definir planilha de saída")
        passo2.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        passo2.columnconfigure(0, weight=1)
        ttk.Button(
            passo2, text=" Definir local da planilha (.xlsx)", command=self.selecionar_planilha_saida,
            image=self.icones["excel"], compound=tk.LEFT,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        self.lbl_output = ttk.Label(
            passo2, text="Nenhuma planilha de saída definida.", relief="sunken",
            anchor="w", padding=5, wraplength=580, justify=tk.LEFT,
        )
        self.lbl_output.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10), ipady=5)

        # Passo 3
        passo3 = ttk.LabelFrame(corpo, text="Passo 3: Processar")
        passo3.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        passo3.columnconfigure(0, weight=1)
        self.btn_iniciar = ttk.Button(
            passo3, text=" Iniciar processamento", command=self.iniciar_processamento,
            state="disabled", image=self.icones["play"], compound=tk.LEFT,
        )
        self.btn_iniciar.grid(row=0, column=0, sticky="ew", padx=10, pady=10, ipady=5)
        self.progress_var = tk.DoubleVar()
        ttk.Progressbar(passo3, variable=self.progress_var, maximum=100).grid(
            row=1, column=0, sticky="ew", padx=10, pady=(0, 10)
        )

        # Inspeção visual
        inspecao = ttk.LabelFrame(corpo, text="Conferência: ver de onde cada dado foi lido")
        inspecao.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        inspecao.columnconfigure(0, weight=1)
        self.btn_inspecionar = ttk.Button(
            inspecao, text=" Inspecionar um arquivo...", command=self.inspecionar_arquivo,
        )
        self.btn_inspecionar.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        ttk.Label(
            inspecao,
            text="Abre o documento com um retângulo colorido sobre cada campo encontrado.",
            wraplength=580, justify=tk.LEFT, foreground="#555555",
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))

        # Log
        frame_log = ttk.Frame(corpo)
        frame_log.grid(row=4, column=0, sticky="nsew", pady=(0, 10))
        frame_log.columnconfigure(0, weight=1)
        frame_log.rowconfigure(1, weight=1)
        topo_log = ttk.Frame(frame_log)
        topo_log.grid(row=0, column=0, sticky="ew")
        ttk.Label(topo_log, text="Log de atividades:", style="Bold.TLabel").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Checkbutton(
            topo_log, text="Exibir logs detalhados", variable=self.show_logs_var,
            command=self.toggle_log_visibility,
        ).pack(side=tk.LEFT, padx=10)
        self.log_area_frame = ttk.Frame(frame_log)
        self.log_area_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        self.log_area_frame.rowconfigure(0, weight=1)
        self.log_area_frame.columnconfigure(0, weight=1)
        self.log_area = scrolledtext.ScrolledText(
            self.log_area_frame, height=8, state="disabled", font=("Courier New", 9)
        )
        self.log_area.grid(row=0, column=0, sticky="nsew")

        # Resultado
        resultado = ttk.Frame(corpo)
        resultado.grid(row=5, column=0, sticky="ew", padx=10)
        resultado.columnconfigure(0, weight=1)
        resultado.columnconfigure(1, weight=1)
        self.btn_abrir_planilha = ttk.Button(
            resultado, text=" Abrir planilha", state="disabled", command=self.abrir_planilha,
            image=self.icones["open_excel"], compound=tk.LEFT,
        )
        self.btn_abrir_planilha.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_abrir_pasta = ttk.Button(
            resultado, text=" Abrir pasta de saída", state="disabled", command=self.abrir_pasta_saida,
            image=self.icones["open_folder"], compound=tk.LEFT,
        )
        self.btn_abrir_pasta.grid(row=0, column=1, sticky="ew", padx=(5, 0))

    # --- Comunicação entre threads ----------------------------------------

    def log(self, mensagem: str) -> None:
        """Publica uma mensagem de log (seguro a partir de qualquer thread)."""
        self.fila.put(("log", mensagem))

    def _escrever_log(self, mensagem: str) -> None:
        """Escreve no widget — só pode ser chamado pela thread principal."""
        logger.info(mensagem)
        if not self.show_logs_var.get():
            return
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, mensagem + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    def _drenar_fila(self) -> None:
        """Consome as mensagens da thread de processamento na thread da GUI."""
        try:
            while True:
                tipo, carga = self.fila.get_nowait()
                if tipo == "log":
                    self._escrever_log(carga)
                elif tipo == "progresso":
                    self.progress_var.set(carga)
                elif tipo == "concluido":
                    self._ao_concluir(carga)
                elif tipo == "erro":
                    self._ao_falhar(carga)
        except queue.Empty:
            pass
        self.root.after(INTERVALO_DRENAGEM_MS, self._drenar_fila)

    # --- Seleção -----------------------------------------------------------

    def selecionar_entrada(self) -> None:
        tipos = [
            ("Arquivos suportados", "*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.bmp *.gif"),
            ("Todos os arquivos", "*.*"),
        ]
        arquivos = filedialog.askopenfilenames(title="Selecione um ou mais arquivos", filetypes=tipos)
        if arquivos:
            self.arquivos_para_processar = list(arquivos)
            self.lbl_input.config(text=f"{len(arquivos)} arquivo(s) selecionado(s).")
            self.log(f"{len(arquivos)} arquivo(s) selecionado(s).")
            self.verificar_estado_iniciar()
            return

        if messagebox.askyesno("Selecionar pasta", "Nenhum arquivo selecionado. Deseja selecionar uma pasta inteira?"):
            self.selecionar_pasta()

    def selecionar_pasta(self) -> None:
        caminho = filedialog.askdirectory(title="Selecione a pasta com os arquivos")
        if not caminho:
            return
        self.arquivos_para_processar = file_processor.listar_arquivos_suportados([caminho])
        if not self.arquivos_para_processar:
            self.lbl_input.config(text=f"Nenhum arquivo compatível em:\n{caminho}")
            self.log("Nenhum arquivo compatível encontrado na pasta.")
        else:
            quantidade = len(self.arquivos_para_processar)
            self.lbl_input.config(text=f"{quantidade} arquivo(s) na pasta:\n{caminho}")
            self.log(f"Pasta selecionada: {caminho} ({quantidade} arquivo(s)).")
        self.verificar_estado_iniciar()

    def selecionar_planilha_saida(self) -> None:
        caminho = filedialog.asksaveasfilename(
            title="Salvar planilha como...", defaultextension=".xlsx",
            filetypes=[("Planilha Excel", "*.xlsx")],
        )
        if not caminho:
            return
        self.output_filepath = caminho
        self.lbl_output.config(text=f"Planilha: {caminho}")
        self.log(f"Planilha de saída: {caminho}")
        self.verificar_estado_iniciar()

    def verificar_estado_iniciar(self) -> None:
        pronto = bool(self.arquivos_para_processar and self.output_filepath)
        self.btn_iniciar.config(
            state="normal" if pronto else "disabled",
            style="Success.TButton" if pronto else "TButton",
        )

    # --- Inspeção ----------------------------------------------------------

    def inspecionar_arquivo(self) -> None:
        """Abre a janela que mostra onde cada dado está no documento."""
        tipos = [
            ("Arquivos suportados", "*.pdf *.png *.jpg *.jpeg *.tiff *.tif *.bmp *.gif"),
            ("Todos os arquivos", "*.*"),
        ]
        caminho = filedialog.askopenfilename(title="Selecione o arquivo a inspecionar", filetypes=tipos)
        if not caminho:
            return
        if not file_processor.e_suportado(caminho):
            messagebox.showwarning("Formato não suportado", "Selecione um PDF ou uma imagem.")
            return
        self.log(f"Inspecionando '{os.path.basename(caminho)}'...")
        JanelaInspecao(self.root, caminho)

    # --- Processamento -----------------------------------------------------

    def iniciar_processamento(self) -> None:
        if self.processando:
            self.solicitar_cancelamento()
            return
        if not (self.arquivos_para_processar and self.output_filepath):
            messagebox.showwarning("Atenção", "Selecione os arquivos de entrada e a planilha de saída.")
            return

        self.processando = True
        self.cancelar_solicitado.clear()
        self.progress_var.set(0)
        self.btn_iniciar.config(text=" Cancelar", style="Danger.TButton", image=self.icones["cancel"])
        self.btn_inspecionar.config(state="disabled")
        self.btn_abrir_planilha.config(state="disabled")
        self.btn_abrir_pasta.config(state="disabled")
        self.log(f"--- Iniciando processamento ({len(self.arquivos_para_processar)} arquivo(s)) ---")

        threading.Thread(target=self._trabalhar, daemon=True).start()

    def _trabalhar(self) -> None:
        """Executa o lote fora da thread da GUI."""
        servico = ServicoExtracao()
        try:
            resumo = servico.processar_lote(
                self.arquivos_para_processar,
                caminho_planilha=self.output_filepath,
                on_log=self.log,
                on_progress=lambda indice, total, _nome: self.fila.put(
                    ("progresso", indice * 100 / max(total, 1))
                ),
                deve_cancelar=self.cancelar_solicitado.is_set,
            )
            self.fila.put(("concluido", resumo))
        except PlanilhaError as erro:
            self.fila.put(("erro", str(erro)))
        except Exception as erro:  # pragma: no cover - proteção da GUI
            logger.exception("Falha inesperada no lote")
            self.fila.put(("erro", f"Erro inesperado: {erro}"))

    def solicitar_cancelamento(self) -> None:
        if messagebox.askyesno("Cancelar", "Deseja cancelar o processamento?"):
            self.cancelar_solicitado.set()
            self.log("Cancelamento solicitado. Aguardando o término do arquivo atual...")
            self.btn_iniciar.config(text=" Cancelando...", state="disabled")

    def _ao_concluir(self, resumo: ResumoLote) -> None:
        self._restaurar_botoes()
        self._escrever_log("\n" + resumo.texto())

        if resumo.cancelado:
            messagebox.showinfo("Cancelado", "O processamento foi cancelado.")
        elif resumo.resumo_planilha:
            self.btn_abrir_planilha.config(state="normal")
            self.btn_abrir_pasta.config(state="normal")
            messagebox.showinfo("Processo concluído", resumo.texto())
        else:
            messagebox.showinfo("Processo concluído", "Nenhum dado novo foi encontrado.")

    def _ao_falhar(self, mensagem: str) -> None:
        self._restaurar_botoes()
        self._escrever_log(f"ERRO: {mensagem}")
        messagebox.showerror("Erro", mensagem)

    def _restaurar_botoes(self) -> None:
        self.processando = False
        self.progress_var.set(0)
        self.btn_iniciar.config(
            text=" Iniciar processamento", state="normal",
            style="Success.TButton", image=self.icones["play"],
        )
        self.btn_inspecionar.config(state="normal")
        self.verificar_estado_iniciar()

    # --- Ações de resultado -------------------------------------------------

    def toggle_log_visibility(self) -> None:
        if self.show_logs_var.get():
            self.log_area_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        else:
            self.log_area_frame.grid_forget()

    def abrir_planilha(self) -> None:
        self._abrir(self.output_filepath, "a planilha")

    def abrir_pasta_saida(self) -> None:
        self._abrir(os.path.dirname(os.path.abspath(self.output_filepath)), "a pasta")

    def _abrir(self, caminho: str, descricao: str) -> None:
        if not caminho:
            return
        try:
            abrir_no_sistema(caminho)
        except Exception as erro:
            messagebox.showerror("Erro ao abrir", f"Não foi possível abrir {descricao}:\n{erro}")


# --------------------------------------------------------------------------- #
# Ponto de entrada da GUI
# --------------------------------------------------------------------------- #

def iniciar_gui() -> int:
    """Cria a janela principal e entra no laço de eventos. Devolve o código de saída."""
    root = tk.Tk()
    root.withdraw()

    try:
        setup_tesseract()
    except Exception as erro:
        messagebox.showerror("Tesseract não encontrado", str(erro))
        logger.error("%s", erro)
        root.destroy()
        return 1

    root.deiconify()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    from config import configurar_logging

    configurar_logging()
    sys.exit(iniciar_gui())
