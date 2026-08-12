# -*- coding: utf-8 -*-
"""
extraction_logic.py

A classe ``BoletoParser`` e a estratégia de extração em três camadas.

Ordem de tentativa (da mais confiável para a menos):

    0. **Linha digitável** — se os dígitos verificadores fecham, vencimento e
       valor vêm da aritmética do próprio boleto, não de palpite de layout.
    1. **Regex** sobre o texto (digital ou OCR) — resolve beneficiário, pagador
       e os campos que a linha digitável não carrega.
    2. **Posicional** — usa as coordenadas X/Y das palavras para achar o que a
       regex não achou, por proximidade dos rótulos.

Uma camada nunca sobrescreve o resultado de outra mais confiável: quem decide
é ``Campo.definir``, pela precedência declarada em ``Origem``.

Este módulo não conhece arquivos, PDFs nem GUI: recebe texto ou dados
posicionais e devolve dados estruturados.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd

import linha_digitavel as ld
from boleto_data import BoletoData, Campo, Origem, Regiao
from config import ANO_MAXIMO_PLAUSIVEL, ANO_MINIMO_PLAUSIVEL, OCR_CONF_THRESHOLD, VALOR_MAX_DISTANCE

logger = logging.getLogger(__name__)


# --- Exceções ---------------------------------------------------------------

class ExtractionError(Exception):
    """Erro base para falhas de extração."""


class OCRError(ExtractionError):
    """Falha ao rodar o Tesseract."""


class LayoutNaoReconhecidoError(ExtractionError):
    """Não foi possível encontrar nenhum campo no documento."""


# --- Palavra posicionada (abstração comum a OCR e PDF digital) --------------

class Palavra:
    """
    Uma palavra com posição na página.

    Serve tanto para as palavras do Tesseract quanto para as do texto digital
    do PDF, o que permite que a localização visual dos campos funcione nos
    dois modos com o mesmo código.
    """

    __slots__ = ("texto", "x", "y", "largura", "altura", "pagina")

    def __init__(self, texto: str, x: int, y: int, largura: int, altura: int, pagina: int = 0):
        self.texto = texto
        self.x = int(x)
        self.y = int(y)
        self.largura = int(largura)
        self.altura = int(altura)
        self.pagina = pagina

    @property
    def centro(self) -> Tuple[int, int]:
        return (self.x + self.largura // 2, self.y + self.altura // 2)

    def regiao(self) -> Regiao:
        return Regiao(self.x, self.y, self.largura, self.altura, self.pagina)

    def __repr__(self) -> str:  # pragma: no cover - only for debugging
        return f"Palavra({self.texto!r}, {self.x}, {self.y})"


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação — para comparar textos de OCR."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def unir_regioes(palavras: Sequence[Palavra]) -> Optional[Regiao]:
    """Retângulo que envolve todas as palavras informadas."""
    if not palavras:
        return None
    esquerda = min(p.x for p in palavras)
    topo = min(p.y for p in palavras)
    direita = max(p.x + p.largura for p in palavras)
    base = max(p.y + p.altura for p in palavras)
    return Regiao(esquerda, topo, direita - esquerda, base - topo, palavras[0].pagina)


def _mais_proxima_do_rotulo(
    ocorrencias: Sequence[Regiao],
    palavras: Sequence[Palavra],
    palavras_chave: Sequence[str],
) -> Regiao:
    """Entre várias ocorrências do mesmo texto, escolhe a mais perto do rótulo."""
    if len(ocorrencias) == 1 or not palavras_chave:
        return ocorrencias[0]

    rotulos = [
        p for p in palavras
        if any(chave in _normalizar(p.texto) for chave in palavras_chave)
    ]
    if not rotulos:
        return ocorrencias[0]

    def distancia_ao_rotulo(regiao: Regiao) -> float:
        centro = (regiao.x + regiao.largura / 2, regiao.y + regiao.altura / 2)
        return min(math.dist(centro, rotulo.centro) for rotulo in rotulos)

    return min(ocorrencias, key=distancia_ao_rotulo)


def localizar_texto(
    palavras: Sequence[Palavra],
    alvo: str,
    max_palavras: int = 8,
    perto_de: Sequence[str] = (),
) -> Optional[Regiao]:
    """
    Acha onde um texto extraído aparece entre as palavras da página.

    Testa sequências consecutivas de palavras e devolve a região da que
    corresponde ao alvo normalizado. É assim que o modo de inspeção consegue
    desenhar a caixa mesmo para campos achados por regex, que por natureza não
    têm coordenadas.

    ``perto_de`` lista palavras-chave do rótulo do campo. Um mesmo valor
    costuma aparecer várias vezes no boleto (um total repetido no resumo e no
    campo próprio); havendo empate, vence a ocorrência mais próxima do rótulo.
    """
    alvo_normalizado = _normalizar(alvo)
    if not alvo_normalizado or not palavras:
        return None

    ocorrencias: List[Regiao] = []
    for inicio in range(len(palavras)):
        acumulado = ""
        for fim in range(inicio, min(inicio + max_palavras, len(palavras))):
            acumulado += _normalizar(palavras[fim].texto)
            if not acumulado:
                continue
            if acumulado == alvo_normalizado:
                ocorrencias.append(unir_regioes(palavras[inicio:fim + 1]))
                break
            if len(acumulado) >= len(alvo_normalizado):
                break

    if ocorrencias:
        return _mais_proxima_do_rotulo(ocorrencias, palavras, perto_de)
    # Segunda passada, mais tolerante: aceita uma palavra que contenha o alvo.
    #
    # O limite de comprimento importa: "106,00" está contido no fim da própria
    # linha digitável ("...83100000010600"), e sem essa guarda o valor seria
    # apontado no código de barras em vez de no campo "Valor do Documento".
    limite = len(alvo_normalizado) * 2
    melhor: Optional[Palavra] = None
    for palavra in palavras:
        normalizada = _normalizar(palavra.texto)
        if alvo_normalizado not in normalizada or len(normalizada) > limite:
            continue
        if melhor is None or len(normalizada) < len(_normalizar(melhor.texto)):
            melhor = palavra
    return melhor.regiao() if melhor else None


# --- Parser -----------------------------------------------------------------

class BoletoParser:
    """Extrai os dados de um boleto a partir de texto e/ou palavras posicionadas."""

    # Rótulos de valor, do mais específico para o mais genérico.
    _REGEX_LIXO = r"[^\n\d]*"
    _REGEX_VALOR = r"([ \d\.]*,\d{2})"
    PADROES_VALOR = (
        r"(?:=\)\s*)?Valor (?:do )?Documento" + _REGEX_LIXO + _REGEX_VALOR,
        r"=\)\s*Valor\s*(?:do )?Documento\s*\n" + _REGEX_LIXO + _REGEX_VALOR,
        r"Valor (?:do )?Documento\s*\n" + _REGEX_LIXO + _REGEX_VALOR,
        r"Valor Cobrado" + _REGEX_LIXO + _REGEX_VALOR,
        r"Valor Cobrado\s*\n" + _REGEX_LIXO + _REGEX_VALOR,
        r"^\s*Valor\s+" + _REGEX_LIXO + _REGEX_VALOR,
    )

    PADROES_VENCIMENTO_CONTEXTO = (
        r"vencimento\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"venc\.?\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"vencto\.?\s*[:\-]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
    )

    REGEX_DATA = re.compile(r"\b\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}\b")

    #: Rótulo que às vezes vem colado ao nome capturado.
    REGEX_ROTULO_INICIAL = re.compile(
        # "nome" fica de fora de propósito: é palavra comum demais e chegaria a
        # cortar o início de razões sociais legítimas.
        r"^\s*(?:benefici[áao]rio|cedente|pagador|sacado)\s*[:\-–—]?\s*", re.IGNORECASE
    )

    #: Fragmentos do rótulo de cada campo, usados para desempatar a localização
    #: visual quando o mesmo texto aparece em mais de um lugar do boleto.
    ROTULOS_POR_CAMPO = {
        "vencimento": ("venc",),
        "valor_documento": ("valor", "documento"),
        "beneficiario": ("benefici",),
        "pagador": ("pagador",),
    }

    LIXO_SEM_VALOR = (
        "NOSSO NÚMERO", "AGÊNCIA", "CÓDIGO BENEFICIÁRIO", "VENCIMENTO",
        "RECIBO DO PAGADOR", "AUTENTICAÇÃO MECANICA",
    )

    # ------------------------------------------------------------------ #
    # Camada 0 + 1: linha digitável e regex sobre texto
    # ------------------------------------------------------------------ #

    def extrair_de_texto(
        self,
        texto: str,
        dados: BoletoData,
        origem: str = Origem.REGEX,
        referencia: Optional[date] = None,
    ) -> BoletoData:
        """
        Aplica a linha digitável e depois as regex sobre um texto.

        ``origem`` distingue texto digital de texto de OCR, para que o dado
        digital (mais confiável) não seja sobrescrito pelo do OCR depois.
        """
        if not texto:
            return dados

        self._extrair_linha_digitavel(texto, dados, referencia)
        self._extrair_vencimento(texto, dados, origem)
        self._extrair_valor(texto, dados, origem)
        self._extrair_beneficiario(texto, dados, origem)
        self._extrair_pagador(texto, dados, origem)
        return dados

    def _extrair_linha_digitavel(
        self, texto: str, dados: BoletoData, referencia: Optional[date] = None
    ) -> None:
        """Camada 0: dados autoverificados pelos dígitos verificadores."""
        if dados.linha_digitavel_valida:
            return

        decodificado = ld.encontrar_linha_digitavel(texto, referencia=referencia)
        if decodificado is None:
            logger.debug("Nenhuma linha digitável válida no texto.")
            return

        dados.linha_digitavel_valida = True
        dados.codigo_barras.definir(
            decodificado.linha_formatada,
            texto_bruto=decodificado.linha_formatada,
            origem=Origem.LINHA_DIGITAVEL,
        )
        if decodificado.vencimento:
            dados.vencimento.definir(
                decodificado.vencimento,
                texto_bruto=decodificado.vencimento.strftime("%d/%m/%Y"),
                origem=Origem.LINHA_DIGITAVEL,
            )
        if decodificado.valor:
            dados.valor_documento.definir(
                decodificado.valor,
                texto_bruto=f"{decodificado.valor:.2f}".replace(".", ","),
                origem=Origem.LINHA_DIGITAVEL,
            )
        logger.info(
            "Linha digitável validada (banco %s): vencimento=%s valor=%s",
            decodificado.banco, decodificado.vencimento, decodificado.valor,
        )

    # --- Vencimento --------------------------------------------------------

    def _extrair_vencimento(self, texto: str, dados: BoletoData, origem: str) -> None:
        if dados.vencimento.encontrado:
            return

        match = re.search(
            r"Venciment[oau][\s\n]*([\dOS]{2}/[\dOS]{2}/[\dOS]{4})", texto, re.IGNORECASE
        )
        bruto = match.group(1) if match else self._extrair_vencimento_regex_contexto(texto)
        if not bruto:
            logger.debug("Vencimento não encontrado por regex.")
            return

        data = self._parse_data(bruto)
        if data and dados.vencimento.definir(data, texto_bruto=bruto, origem=origem):
            logger.info("Vencimento por regex: %s", data)

    def _extrair_vencimento_regex_contexto(self, ocr_text: str) -> Optional[str]:
        """
        Procura a data de vencimento pelo contexto ao redor.

        Ordem: rótulo explícito ("Vencimento: dd/mm/aaaa"), depois qualquer
        data precedida de "venc" nos 25 caracteres anteriores e, por último,
        a data mais distante no futuro entre as encontradas.
        """
        if not ocr_text:
            return None

        for padrao in self.PADROES_VENCIMENTO_CONTEXTO:
            match = re.search(padrao, ocr_text, flags=re.IGNORECASE)
            if match:
                return match.group(1)

        datas = self.REGEX_DATA.findall(ocr_text)
        if not datas:
            return None

        for bruto in datas:
            indice = ocr_text.find(bruto)
            if "venc" in ocr_text[max(0, indice - 25):indice].lower():
                return bruto

        datadas = [(self._parse_data(bruto), bruto) for bruto in datas]
        validas = [(data, bruto) for data, bruto in datadas if data]
        if not validas:
            return None
        return max(validas, key=lambda item: item[0])[1]

    def _parse_data(self, bruto: Optional[str]) -> Optional[date]:
        """
        Converte um texto em data, corrigindo confusões de OCR e validando.

        Rejeita datas impossíveis (32/13/2025) e fora de uma janela plausível,
        que antes entravam na planilha como string sem nenhuma checagem.
        """
        if not bruto:
            return None
        limpo = bruto.strip().translate(str.maketrans("OoSsIl|B", "00551118"))
        partes = re.split(r"[\/\-\.]", limpo)
        if len(partes) != 3:
            return None
        try:
            dia, mes, ano = (int(parte) for parte in partes)
        except ValueError:
            return None
        if ano < 100:
            ano += 2000
        if not ANO_MINIMO_PLAUSIVEL <= ano <= ANO_MAXIMO_PLAUSIVEL:
            return None
        try:
            return date(ano, mes, dia)
        except ValueError:
            logger.debug("Data inválida descartada: %s", bruto)
            return None

    # --- Valor -------------------------------------------------------------

    def _extrair_valor(self, texto: str, dados: BoletoData, origem: str) -> None:
        if dados.valor_documento.encontrado:
            return
        for indice, padrao in enumerate(self.PADROES_VALOR, start=1):
            match = re.search(padrao, texto, re.IGNORECASE | re.MULTILINE)
            if not match:
                continue
            bruto = match.group(1)
            valor = self._parse_valor(bruto)
            if valor and dados.valor_documento.definir(valor, texto_bruto=bruto.strip(), origem=origem):
                logger.info("Valor por regex (padrão %d): %s", indice, valor)
                return
        logger.debug("Valor não encontrado por regex.")

    def _parse_valor(self, bruto: Optional[str]) -> Optional[Decimal]:
        """
        Converte "1.234,56" em Decimal("1234.56").

        O separador de milhar é removido em vez de virar hífen — antes,
        ``_clean_data`` trocava "." por "-" e corrompia todo valor acima de mil.
        """
        if not bruto:
            return None
        limpo = re.sub(r"[^\d,.]", "", bruto.translate(str.maketrans("OoSsIl|B", "00551118")))
        limpo = limpo.replace(".", "").replace(",", ".")
        if not limpo or limpo.count(".") > 1:
            return None
        try:
            valor = Decimal(limpo)
        except InvalidOperation:
            return None
        if valor <= 0 or valor > ld.VALOR_MAXIMO_PLAUSIVEL:
            return None
        return valor

    # --- Beneficiário ------------------------------------------------------

    def _extrair_beneficiario(self, texto: str, dados: BoletoData, origem: str) -> None:
        if dados.beneficiario.encontrado:
            return

        # 1) Nome na mesma linha de um CNPJ, ou na linha imediatamente acima.
        match_cnpj = re.search(
            r"^\s*(.*?CNPJ\s*\d{2}[\.\s]?\d{3}[\.\s]?\d{3}/\d{4}[\-\s]?\d{2}.*)$",
            texto, re.MULTILINE | re.IGNORECASE,
        )
        if match_cnpj:
            linha = match_cnpj.group(1).strip()
            match_nome = re.search(r"^([^\n]+?)\s*CNPJ", linha, re.IGNORECASE)
            if match_nome and self._is_valid_candidate(match_nome.group(1)):
                self._definir_nome(dados.beneficiario, match_nome.group(1), origem, "mesma linha do CNPJ")
                return
            anteriores = texto[:match_cnpj.start()].strip().split("\n")
            if anteriores and anteriores[-1].strip() and self._is_valid_candidate(anteriores[-1]):
                self._definir_nome(dados.beneficiario, anteriores[-1], origem, "linha anterior ao CNPJ")
                return

        # 2) Rótulo "Beneficiário" na mesma linha.
        match = re.search(
            r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Benefici[áao]rio[^\w\n]*([^\n]+)",
            texto, re.MULTILINE | re.IGNORECASE,
        )
        if match:
            nome = re.sub(r"\s*CNPJ.*$", "", match.group(1).strip(), flags=re.IGNORECASE).strip()
            if self._is_valid_candidate(nome):
                self._definir_nome(dados.beneficiario, nome, origem, "rótulo na mesma linha")
                return

        # 3) Rótulo "Beneficiário" com o nome na linha de baixo.
        match = re.search(
            r"(?<!CÓDIGO\s)(?<!Agência\s/\sCódigo\s)Benefici[áao]rio\s*\n\s*([^\n]+)",
            texto, re.MULTILINE | re.IGNORECASE,
        )
        if match:
            nome = match.group(1).strip()
            if "CNPJ" not in nome.upper() and self._is_valid_candidate(nome):
                self._definir_nome(dados.beneficiario, nome, origem, "rótulo na linha seguinte")
                return

        logger.debug("Beneficiário não encontrado por regex.")

    # --- Pagador -----------------------------------------------------------

    def _extrair_pagador(self, texto: str, dados: BoletoData, origem: str) -> None:
        if dados.pagador.encontrado:
            return

        match_cpf = re.search(
            r"CPF[:\s]*(\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[\-\s]?\d{2})",
            texto, re.MULTILINE | re.IGNORECASE,
        )
        if match_cpf:
            posicao = match_cpf.start()
            inicio_linha = texto.rfind("\n", 0, posicao) + 1
            antes_na_linha = texto[inicio_linha:posicao].strip()
            match_nome = re.search(r"Pagador:?\s+(.+)", antes_na_linha, re.IGNORECASE)
            if match_nome and self._is_valid_candidate(match_nome.group(1)):
                self._definir_nome(dados.pagador, match_nome.group(1), origem, "mesma linha do CPF")
                return
            linhas = texto[:posicao].strip().split("\n")
            if len(linhas) > 1 and re.search(r"Pagador", linhas[-2], re.IGNORECASE):
                if self._is_valid_candidate(linhas[-1]):
                    self._definir_nome(dados.pagador, linhas[-1], origem, "linha anterior ao CPF")
                    return

        for padrao in (
            r"^\s*Pagador:?\s+([^\n]+?)(?=\s*CPF|$)",
            r"^\s*Pagador\s*\n\s*([^\n]+?)(?=\s*CPF|$)",
        ):
            match = re.search(padrao, texto, re.MULTILINE | re.IGNORECASE)
            if match and self._is_valid_candidate(match.group(1)):
                self._definir_nome(dados.pagador, match.group(1), origem, "rótulo Pagador")
                return

        logger.debug("Pagador não encontrado por regex.")

    def _definir_nome(self, campo: Campo, bruto: str, origem: str, como: str) -> None:
        """Limpa e grava um campo de nome (beneficiário/pagador)."""
        # Quando o nome e o rótulo estão na mesma linha, a captura pelo CNPJ/CPF
        # arrasta o rótulo junto ("Beneficiário: EMPRESA X").
        nome = self.REGEX_ROTULO_INICIAL.sub("", bruto.strip())
        # Boletos costumam separar o nome do que vem depois com traço ou
        # travessão; o OCR arrasta esse separador para dentro do nome.
        nome = re.sub(r"[\s\-–—:;,.]+$", "", nome).strip()
        nome = re.sub(r"\s{2,}", " ", nome)
        if campo.definir(nome, texto_bruto=nome, origem=origem):
            logger.info("Nome encontrado (%s): %s", como, nome)

    def _is_valid_candidate(self, texto: Optional[str]) -> bool:
        """Descarta candidatos a nome que são claramente rótulo ou ruído."""
        if not texto:
            return False
        texto = texto.strip()
        if len(texto) <= 3:
            return False
        if re.fullmatch(r"[\d\s\.\/\-\,\—]+", texto):
            return False
        return not any(lixo in texto.upper() for lixo in self.LIXO_SEM_VALOR)

    # ------------------------------------------------------------------ #
    # Camada 2: posicional
    # ------------------------------------------------------------------ #

    def extrair_posicional(self, palavras: Sequence[Palavra], dados: BoletoData) -> BoletoData:
        """
        Preenche os campos que faltaram usando as coordenadas das palavras.

        Recebe as palavras já extraídas do Tesseract (uma única passada de OCR
        alimenta tanto esta camada quanto a de regex).
        """
        faltantes = dados.campos_faltantes()
        if not faltantes:
            logger.debug("Modo posicional dispensado: campos principais já preenchidos.")
            return dados
        if not palavras:
            return dados

        logger.info("Modo posicional para: %s", ", ".join(faltantes))

        if "vencimento" in faltantes:
            self._posicional_vencimento(palavras, dados)
        if "valor_documento" in faltantes:
            self._posicional_valor(palavras, dados)
        if "beneficiario" in faltantes:
            self._posicional_beneficiario(palavras, dados)
        return dados

    def _posicional_vencimento(self, palavras: Sequence[Palavra], dados: BoletoData) -> None:
        """Procura uma data à direita (ou logo abaixo) de um rótulo 'Venc'."""
        rotulos = [p for p in palavras if "venc" in _normalizar(p.texto)]
        candidatas: List[Tuple[date, Palavra]] = []

        for rotulo in rotulos:
            for palavra in palavras:
                perto_na_vertical = rotulo.y - 10 <= palavra.y <= rotulo.y + 50
                a_direita = palavra.x > rotulo.x
                if not (perto_na_vertical and a_direita):
                    continue
                match = self.REGEX_DATA.search(palavra.texto)
                if match:
                    data = self._parse_data(match.group(0))
                    if data:
                        candidatas.append((data, palavra))

        if not candidatas:
            return
        data, palavra = max(candidatas, key=lambda item: item[0])
        if dados.vencimento.definir(data, texto_bruto=palavra.texto, origem=Origem.POSICIONAL):
            dados.vencimento.regiao = palavra.regiao()
            logger.info("Vencimento posicional: %s", data)

    def _posicional_valor(self, palavras: Sequence[Palavra], dados: BoletoData) -> None:
        """
        Acha o valor pelo candidato numérico mais próximo de um rótulo de valor.

        Inclui a "fusão" de valores que o OCR quebrou em duas palavras
        ("1.234" + "56" lado a lado viram "1.234,56").
        """
        regex_candidato = re.compile(r"^([\d\.OSBl]*[,][\dOS]{2})$")
        rotulos = [
            p.centro for p in palavras
            if any(chave in _normalizar(p.texto) for chave in ("valor", "documento", "cobrado"))
        ]
        candidatos: List[Tuple[str, Tuple[int, int], Regiao]] = [
            (p.texto, p.centro, p.regiao()) for p in palavras if regex_candidato.match(p.texto)
        ]
        candidatos.extend(self._fundir_valores_quebrados(palavras))

        if not rotulos or not candidatos:
            logger.debug("Valor posicional: sem rótulo ou sem candidato.")
            return

        melhor, menor_distancia = None, float("inf")
        for rotulo in rotulos:
            for texto, centro, regiao in candidatos:
                distancia = math.dist(centro, rotulo)
                if distancia < menor_distancia:
                    menor_distancia, melhor = distancia, (texto, regiao)

        if melhor is None or menor_distancia >= VALOR_MAX_DISTANCE:
            return
        texto, regiao = melhor
        valor = self._parse_valor(texto)
        if valor and dados.valor_documento.definir(valor, texto_bruto=texto, origem=Origem.POSICIONAL):
            dados.valor_documento.regiao = regiao
            logger.info("Valor posicional: %s (distância %.0f px)", valor, menor_distancia)

    def _fundir_valores_quebrados(
        self, palavras: Sequence[Palavra]
    ) -> List[Tuple[str, Tuple[int, int], Regiao]]:
        """Junta pares de palavras vizinhas que formam um valor com centavos."""
        regex_inteiro = re.compile(r"^[\d\.]+$")
        regex_centavos = re.compile(r"^\d{2}$")
        fundidos = []

        for atual, seguinte in zip(palavras, palavras[1:]):
            if not (regex_inteiro.match(atual.texto) and regex_centavos.match(seguinte.texto)):
                continue
            mesma_linha = abs((atual.y + atual.altura / 2) - (seguinte.y + seguinte.altura / 2)) < 10
            fim_atual = atual.x + atual.largura
            adjacentes = fim_atual < seguinte.x < fim_atual + 50
            if mesma_linha and adjacentes:
                regiao = unir_regioes([atual, seguinte])
                texto = f"{atual.texto},{seguinte.texto}"
                fundidos.append((texto, (regiao.x + regiao.largura // 2, regiao.y + regiao.altura // 2), regiao))
                logger.debug("Valor reconstruído a partir de duas palavras: %s", texto)
        return fundidos

    def _posicional_beneficiario(self, palavras: Sequence[Palavra], dados: BoletoData) -> None:
        """Lê o texto à direita do rótulo 'Beneficiário' ou na linha de baixo."""
        rotulos = [p for p in palavras if "benefici" in _normalizar(p.texto)]
        tolerancia_y = 20

        for rotulo in rotulos:
            meio_y = rotulo.y + rotulo.altura / 2
            fim_x = rotulo.x + rotulo.largura

            mesma_linha = [
                p for p in palavras
                if abs((p.y + p.altura / 2) - meio_y) < tolerancia_y and p.x > fim_x
            ]
            selecionadas = sorted(mesma_linha, key=lambda p: p.x)

            if not selecionadas:
                abaixo = [
                    p for p in palavras
                    if p.y > rotulo.y + rotulo.altura
                    and abs((p.x + p.largura / 2) - (rotulo.x + rotulo.largura / 2)) < 150
                ]
                if not abaixo:
                    continue
                abaixo.sort(key=lambda p: (p.y, p.x))
                primeira_linha_y = abaixo[0].y
                selecionadas = sorted(
                    [p for p in abaixo if abs(p.y - primeira_linha_y) < tolerancia_y],
                    key=lambda p: p.x,
                )

            if not selecionadas:
                continue

            bruto = " ".join(p.texto for p in selecionadas)
            nome = re.sub(r"\s*CNPJ.*$", "", bruto, flags=re.IGNORECASE).strip()
            if self._is_valid_candidate(nome):
                if dados.beneficiario.definir(nome, texto_bruto=nome, origem=Origem.POSICIONAL):
                    dados.beneficiario.regiao = unir_regioes(selecionadas)
                    logger.info("Beneficiário posicional: %s", nome)
                return

    # ------------------------------------------------------------------ #
    # Localização visual dos campos
    # ------------------------------------------------------------------ #

    def localizar_campos(self, palavras: Sequence[Palavra], dados: BoletoData) -> BoletoData:
        """
        Preenche a ``regiao`` dos campos que ainda não têm coordenadas.

        É o que permite ao modo de inspeção desenhar a caixa também sobre
        campos achados por regex ou pela linha digitável.
        """
        for nome, campo in dados.campos().items():
            if campo.encontrado and campo.regiao is None and campo.texto_bruto:
                campo.regiao = localizar_texto(
                    palavras, campo.texto_bruto, perto_de=self.ROTULOS_POR_CAMPO.get(nome, ())
                )

        # Vencimento e valor vindos da linha digitável muitas vezes não existem
        # como texto legível na página (o OCR falha justamente no campo impresso
        # que o código de barras já informa). Nesses casos apontamos para a
        # linha digitável, que é de onde o dado realmente veio.
        regiao_codigo = dados.codigo_barras.regiao
        if regiao_codigo is not None:
            for nome in ("vencimento", "valor_documento"):
                campo = getattr(dados, nome)
                if campo.encontrado and campo.regiao is None and campo.origem == Origem.LINHA_DIGITAVEL:
                    campo.regiao = regiao_codigo
                    campo.regiao_herdada = True
        return dados


# --- Conversões de fontes de palavras --------------------------------------

def palavras_do_dataframe(data: pd.DataFrame, pagina: int = 0, escala: float = 1.0) -> List[Palavra]:
    """
    Converte o DataFrame do ``pytesseract`` em palavras posicionadas.

    ``escala`` reduz as coordenadas do espaço da imagem pré-processada (que é
    ampliada antes do OCR) para o da imagem original exibida ao usuário.
    """
    if data is None or data.empty:
        return []
    filtrado = data.dropna(subset=["text"]).copy()
    filtrado["text"] = filtrado["text"].astype(str).str.strip()
    filtrado = filtrado[filtrado["text"] != ""]
    if "conf" in filtrado.columns:
        filtrado = filtrado[pd.to_numeric(filtrado["conf"], errors="coerce") > OCR_CONF_THRESHOLD]
    fator = 1.0 / escala if escala else 1.0
    return [
        Palavra(
            linha["text"],
            linha["left"] * fator, linha["top"] * fator,
            linha["width"] * fator, linha["height"] * fator,
            pagina,
        )
        for _, linha in filtrado.iterrows()
    ]


def texto_do_dataframe(data: pd.DataFrame) -> str:
    """
    Reconstrói o texto corrido a partir do DataFrame do Tesseract.

    Reagrupar por bloco/parágrafo/linha reproduz o que ``image_to_string``
    devolveria — o que evita rodar o OCR duas vezes sobre a mesma imagem.
    As regex dependem das quebras de linha, então elas são preservadas.
    """
    if data is None or data.empty:
        return ""
    filtrado = data.dropna(subset=["text"]).copy()
    filtrado["text"] = filtrado["text"].astype(str)
    filtrado = filtrado[filtrado["text"].str.strip() != ""]
    if filtrado.empty:
        return ""

    chaves = [c for c in ("page_num", "block_num", "par_num", "line_num") if c in filtrado.columns]
    if not chaves:
        return " ".join(filtrado["text"])

    linhas = []
    for _, grupo in filtrado.groupby(chaves, sort=True):
        if "word_num" in grupo.columns:
            grupo = grupo.sort_values("word_num")
        linhas.append(" ".join(grupo["text"].tolist()).strip())
    return "\n".join(linha for linha in linhas if linha)


def palavras_do_pdf(palavras_fitz: Iterable, escala: float, pagina: int = 0) -> List[Palavra]:
    """
    Converte as palavras do PyMuPDF (``page.get_text("words")``) para pixels.

    O PDF trabalha em pontos e a imagem renderizada em pixels; ``escala`` é a
    razão entre os dois, para que as caixas caiam no lugar certo na imagem.
    """
    convertidas = []
    for entrada in palavras_fitz:
        x0, y0, x1, y1, texto = entrada[0], entrada[1], entrada[2], entrada[3], entrada[4]
        convertidas.append(
            Palavra(
                texto,
                int(x0 * escala), int(y0 * escala),
                int((x1 - x0) * escala), int((y1 - y0) * escala),
                pagina,
            )
        )
    return convertidas
