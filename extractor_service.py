# -*- coding: utf-8 -*-
"""
extractor_service.py

Processamento em lote, sem nenhuma dependência de interface gráfica.

Antes essa lógica morava dentro da GUI e abria caixas de diálogo do Tkinter no
meio do laço, o que a tornava impossível de testar e de usar em automação.
Aqui ela é uma função pura de entrada/saída com callbacks opcionais: a GUI
passa callbacks que atualizam a janela, a CLI passa callbacks que imprimem no
terminal, e os testes não passam nenhum.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

import planilha
from boleto_data import BoletoData
from extraction_logic import BoletoParser, ExtractionError
from file_processor import processar_arquivo

logger = logging.getLogger(__name__)

Callback = Optional[Callable[[str], None]]
CallbackProgresso = Optional[Callable[[int, int, str], None]]


@dataclass
class FalhaArquivo:
    """Um arquivo que não pôde ser processado."""

    arquivo: str
    motivo: str


@dataclass
class ResumoLote:
    """Resultado consolidado de um lote."""

    processados: List[BoletoData] = field(default_factory=list)
    falhas: List[FalhaArquivo] = field(default_factory=list)
    ignorados: List[str] = field(default_factory=list)
    cancelado: bool = False
    resumo_planilha: Optional[planilha.ResumoPlanilha] = None

    @property
    def total_sucesso(self) -> int:
        return len(self.processados)

    @property
    def completos(self) -> int:
        """Boletos em que todos os campos principais foram encontrados."""
        return sum(1 for boleto in self.processados if boleto.esta_completo())

    @property
    def com_dv_valido(self) -> int:
        """Boletos cuja linha digitável foi validada pelos dígitos verificadores."""
        return sum(1 for boleto in self.processados if boleto.linha_digitavel_valida)

    def texto(self) -> str:
        """Resumo legível do lote."""
        linhas = [
            f"Arquivos processados com sucesso: {self.total_sucesso}",
            f"  com todos os campos principais: {self.completos}",
            f"  com linha digitável validada:   {self.com_dv_valido}",
        ]
        if self.ignorados:
            linhas.append(f"Ignorados (já na planilha): {len(self.ignorados)}")
        if self.falhas:
            linhas.append(f"Falhas: {len(self.falhas)}")
            linhas.extend(f"  - {falha.arquivo}: {falha.motivo}" for falha in self.falhas)
        if self.resumo_planilha:
            linhas.append("")
            linhas.append(str(self.resumo_planilha))
        return "\n".join(linhas)


class ServicoExtracao:
    """Executa a extração de uma lista de arquivos e grava a planilha."""

    def __init__(self, parser: Optional[BoletoParser] = None):
        self.parser = parser or BoletoParser()

    def processar_lote(
        self,
        arquivos: Sequence[str],
        caminho_planilha: Optional[str] = None,
        on_log: Callback = None,
        on_progress: CallbackProgresso = None,
        deve_cancelar: Optional[Callable[[], bool]] = None,
        pular_ja_processados: bool = True,
    ) -> ResumoLote:
        """
        Processa os arquivos e, se ``caminho_planilha`` for informado, grava.

        ``deve_cancelar`` é consultado a cada arquivo, o que permite à GUI
        interromper o lote sem matar a thread no meio de uma escrita.
        """
        registrar = on_log or (lambda mensagem: None)
        deve_cancelar = deve_cancelar or (lambda: False)
        resumo = ResumoLote()

        existente = planilha.carregar_existente(caminho_planilha) if caminho_planilha else None
        ja_processados = (
            planilha.arquivos_ja_processados(existente)
            if pular_ja_processados and existente is not None and not existente.empty
            else set()
        )
        if ja_processados:
            registrar(f"{len(ja_processados)} arquivo(s) já constam na planilha e serão ignorados.")

        total = len(arquivos)
        registrar(f"Processando {total} arquivo(s)...")

        for indice, caminho in enumerate(arquivos, start=1):
            if deve_cancelar():
                resumo.cancelado = True
                registrar("Processamento cancelado.")
                break

            nome = os.path.basename(caminho)

            if nome in ja_processados:
                resumo.ignorados.append(nome)
                registrar(f"[{indice}/{total}] {nome}: ignorado (já processado).")
                if on_progress:
                    on_progress(indice, total, nome)
                continue

            registrar(f"[{indice}/{total}] {nome}...")
            try:
                resultado = processar_arquivo(caminho, self.parser)
                dados = resultado.dados
                resumo.processados.append(dados)
                registrar(f"    {dados.resumo()}")
                if not dados.esta_completo():
                    registrar(f"    atenção: {dados.status}")
            except ExtractionError as erro:
                resumo.falhas.append(FalhaArquivo(nome, str(erro)))
                registrar(f"    ERRO: {erro}")
            except Exception as erro:  # falha inesperada não derruba o lote
                logger.exception("Erro inesperado ao processar %s", nome)
                resumo.falhas.append(FalhaArquivo(nome, f"erro inesperado: {erro}"))
                registrar(f"    ERRO INESPERADO: {erro}")

            if on_progress:
                on_progress(indice, total, nome)

        if caminho_planilha and (resumo.processados or (existente is not None and not existente.empty)):
            registrar("Consolidando planilha...")
            resumo.resumo_planilha = planilha.salvar(
                caminho_planilha,
                resumo.processados,
                existente=existente,
                arquivos_ignorados=len(resumo.ignorados),
            )
        elif caminho_planilha:
            registrar("Nenhum dado novo para gravar na planilha.")

        return resumo
