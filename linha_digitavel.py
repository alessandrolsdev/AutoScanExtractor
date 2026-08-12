# -*- coding: utf-8 -*-
"""
linha_digitavel.py

Decodificação e validação da linha digitável / código de barras de boletos.

Este módulo é a "fonte de verdade" do extrator. Diferente do OCR e das regex,
que dependem do layout do boleto, a linha digitável carrega os dados de forma
determinística e *autoverificável*:

    * 3 dígitos verificadores módulo 10 (um por campo);
    * 1 dígito verificador módulo 11 (do código de barras);
    * o fator de vencimento (4 dígitos) codifica a data de vencimento;
    * 10 dígitos codificam o valor do documento em centavos.

Consequências práticas:

    1. Se os dígitos verificadores fecham, vencimento e valor estão corretos —
       não é palpite de regex, é aritmética.
    2. Os DVs permitem *corrigir* erros de OCR: em vez de trocar "O" por "0" às
       cegas, testamos as variantes plausíveis e escolhemos a que valida.

Não depende de nenhuma biblioteca externa nem de OCR: é texto puro entra,
dados estruturados saem.
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# --- Constantes do padrão FEBRABAN ---

TAMANHO_LINHA_BANCARIA = 47
TAMANHO_CODIGO_BARRAS = 44
TAMANHO_LINHA_ARRECADACAO = 48

#: Data base do fator de vencimento. O fator 1000 equivale a 03/07/2000.
DATA_BASE_FATOR = date(1997, 10, 7)

#: O fator de vencimento tem 4 dígitos e estourou em 21/02/2025 (fator 9999).
#: A FEBRABAN determinou o reinício da contagem em 1000 a partir de 22/02/2025.
FATOR_MINIMO = 1000
FATOR_MAXIMO = 9999
DATA_REINICIO_CICLO = date(2025, 2, 22)

#: Valor acima do qual consideramos que o candidato é lixo de OCR, não um boleto.
VALOR_MAXIMO_PLAUSIVEL = Decimal("50000000.00")

#: Janela de datas aceitas ao decodificar o fator de vencimento.
ANOS_TOLERANCIA_VENCIMENTO = 15

# Caracteres que o Tesseract costuma confundir com dígitos.
MAPA_LETRAS_PARA_DIGITOS = {
    "O": "0", "o": "0", "Q": "0", "D": "0", "U": "0",
    "I": "1", "l": "1", "i": "1", "|": "1", "!": "1", "]": "1", "[": "1",
    "Z": "2", "z": "2",
    "A": "4",
    "S": "5", "s": "5", "$": "5",
    "G": "6", "b": "6",
    "T": "7", "?": "7",
    "B": "8", "R": "8",
    "g": "9", "q": "9",
}

# Confusões dígito <-> dígito, usadas na correção guiada por DV.
CONFUSOES_ENTRE_DIGITOS = {
    "0": "689",
    "1": "47",
    "2": "7",
    "3": "89",
    "4": "19",
    "5": "6",
    "6": "058",
    "7": "12",
    "8": "0369",
    "9": "348",
}

#: Teto de tentativas na correção por DV, para não explodir em texto ruidoso.
MAX_TENTATIVAS_CORRECAO = 20000

_CARACTERES_CANDIDATOS = "0-9" + re.escape("".join(MAPA_LETRAS_PARA_DIGITOS))
#: Sequência longa de dígitos (ou confundíveis) com separadores no meio.
REGEX_SEQUENCIA = re.compile(r"[" + _CARACTERES_CANDIDATOS + r"][" + _CARACTERES_CANDIDATOS + r"\s.\-]{38,}")


class LinhaDigitavelInvalida(ValueError):
    """A sequência informada não é uma linha digitável válida."""


@dataclass(frozen=True)
class BoletoDecodificado:
    """Resultado da decodificação de uma linha digitável válida."""

    linha_digitavel: str          # 47 dígitos, sem formatação
    codigo_barras: str            # 44 dígitos
    banco: str
    moeda: str
    vencimento: Optional[date]
    valor: Optional[Decimal]
    tipo: str = "bancario"

    @property
    def linha_formatada(self) -> str:
        """Linha digitável no formato impresso no boleto."""
        return formatar_linha_digitavel(self.linha_digitavel)


# --------------------------------------------------------------------------- #
# Dígitos verificadores
# --------------------------------------------------------------------------- #

def modulo10(bloco: str) -> int:
    """
    Calcula o DV módulo 10 de um bloco de dígitos (campos 1 a 3 da linha).

    Pesos 2 e 1 alternados da direita para a esquerda; produtos com dois
    dígitos são somados algarismo a algarismo.
    """
    soma = 0
    peso = 2
    for caractere in reversed(bloco):
        produto = int(caractere) * peso
        if produto > 9:
            produto -= 9
        soma += produto
        peso = 1 if peso == 2 else 2
    return (10 - (soma % 10)) % 10


def modulo11_codigo_barras(codigo_sem_dv: str) -> int:
    """
    Calcula o DV geral (posição 5) do código de barras.

    Pesos de 2 a 9 ciclando da direita para a esquerda. Resultados 0, 10 e 11
    são convertidos para 1, conforme a especificação FEBRABAN.
    """
    soma = 0
    peso = 2
    for caractere in reversed(codigo_sem_dv):
        soma += int(caractere) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    dv = 11 - resto
    return 1 if dv in (0, 10, 11) else dv


# --------------------------------------------------------------------------- #
# Conversões linha digitável <-> código de barras
# --------------------------------------------------------------------------- #

def linha_para_codigo_barras(linha: str) -> str:
    """
    Converte os 47 dígitos da linha digitável nos 44 do código de barras.

    Layout da linha: campo1(10) campo2(11) campo3(11) dv_geral(1) fator+valor(14).
    """
    if len(linha) != TAMANHO_LINHA_BANCARIA:
        raise LinhaDigitavelInvalida(
            f"Linha digitável precisa ter {TAMANHO_LINHA_BANCARIA} dígitos, recebida com {len(linha)}."
        )
    banco_moeda = linha[0:4]
    dv_geral = linha[32]
    fator_e_valor = linha[33:47]
    campo_livre = linha[4:9] + linha[10:20] + linha[21:31]
    return banco_moeda + dv_geral + fator_e_valor + campo_livre


def codigo_barras_para_linha(codigo: str) -> str:
    """Converte os 44 dígitos do código de barras nos 47 da linha digitável."""
    if len(codigo) != TAMANHO_CODIGO_BARRAS:
        raise LinhaDigitavelInvalida(
            f"Código de barras precisa ter {TAMANHO_CODIGO_BARRAS} dígitos, recebido com {len(codigo)}."
        )
    banco_moeda = codigo[0:4]
    dv_geral = codigo[4]
    fator_e_valor = codigo[5:19]
    campo_livre = codigo[19:44]

    campo1 = banco_moeda + campo_livre[0:5]
    campo2 = campo_livre[5:15]
    campo3 = campo_livre[15:25]

    return (
        campo1 + str(modulo10(campo1))
        + campo2 + str(modulo10(campo2))
        + campo3 + str(modulo10(campo3))
        + dv_geral
        + fator_e_valor
    )


def formatar_linha_digitavel(linha: str) -> str:
    """Formata os 47 dígitos como impresso no boleto."""
    if len(linha) != TAMANHO_LINHA_BANCARIA:
        return linha
    return (
        f"{linha[0:5]}.{linha[5:10]} "
        f"{linha[10:15]}.{linha[15:21]} "
        f"{linha[21:26]}.{linha[26:32]} "
        f"{linha[32]} "
        f"{linha[33:47]}"
    )


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #

def validar_linha_digitavel(linha: str) -> bool:
    """
    Confere os quatro dígitos verificadores de uma linha digitável bancária.

    Retorna False (em vez de levantar) para qualquer entrada malformada, já que
    a função é usada para testar candidatos vindos de OCR.
    """
    if len(linha) != TAMANHO_LINHA_BANCARIA or not linha.isdigit():
        return False

    campo1, dv1 = linha[0:9], linha[9]
    campo2, dv2 = linha[10:20], linha[20]
    campo3, dv3 = linha[21:31], linha[31]

    if modulo10(campo1) != int(dv1):
        return False
    if modulo10(campo2) != int(dv2):
        return False
    if modulo10(campo3) != int(dv3):
        return False

    codigo = linha_para_codigo_barras(linha)
    return modulo11_codigo_barras(codigo[0:4] + codigo[5:44]) == int(codigo[4])


def validar_codigo_barras(codigo: str) -> bool:
    """Confere o DV módulo 11 de um código de barras de 44 dígitos."""
    if len(codigo) != TAMANHO_CODIGO_BARRAS or not codigo.isdigit():
        return False
    return modulo11_codigo_barras(codigo[0:4] + codigo[5:44]) == int(codigo[4])


# --------------------------------------------------------------------------- #
# Decodificação dos dados embutidos
# --------------------------------------------------------------------------- #

def fator_para_data(fator: int, referencia: Optional[date] = None) -> Optional[date]:
    """
    Converte o fator de vencimento na data correspondente.

    O fator estourou em 21/02/2025 (9999) e reiniciou em 1000 no dia seguinte,
    então cada fator admite duas datas possíveis. Escolhemos a mais próxima da
    data de referência (hoje, por padrão), que é o critério que a própria
    FEBRABAN recomenda para desambiguar.
    """
    if fator == 0:
        return None  # boleto sem vencimento definido
    if not FATOR_MINIMO <= fator <= FATOR_MAXIMO:
        return None

    referencia = referencia or date.today()
    candidatos = [
        DATA_BASE_FATOR + timedelta(days=fator),
        DATA_REINICIO_CICLO + timedelta(days=fator - FATOR_MINIMO),
    ]
    return min(candidatos, key=lambda candidata: abs((candidata - referencia).days))


def decodificar(linha_ou_codigo: str, referencia: Optional[date] = None) -> BoletoDecodificado:
    """
    Decodifica uma linha digitável (47) ou código de barras (44) já validado.

    Levanta LinhaDigitavelInvalida se os dígitos verificadores não fecharem.
    """
    digitos = re.sub(r"\D", "", linha_ou_codigo)

    if len(digitos) == TAMANHO_CODIGO_BARRAS:
        if not validar_codigo_barras(digitos):
            raise LinhaDigitavelInvalida("DV do código de barras não confere.")
        linha = codigo_barras_para_linha(digitos)
        codigo = digitos
    elif len(digitos) == TAMANHO_LINHA_BANCARIA:
        if not validar_linha_digitavel(digitos):
            raise LinhaDigitavelInvalida("Dígitos verificadores da linha digitável não conferem.")
        linha = digitos
        codigo = linha_para_codigo_barras(digitos)
    else:
        raise LinhaDigitavelInvalida(
            f"Esperados {TAMANHO_LINHA_BANCARIA} ou {TAMANHO_CODIGO_BARRAS} dígitos, recebidos {len(digitos)}."
        )

    fator = int(codigo[5:9])
    centavos = int(codigo[9:19])

    return BoletoDecodificado(
        linha_digitavel=linha,
        codigo_barras=codigo,
        banco=codigo[0:3],
        moeda=codigo[3],
        vencimento=fator_para_data(fator, referencia),
        valor=(Decimal(centavos) / 100) if centavos > 0 else None,
    )


def _resultado_e_plausivel(decodificado: BoletoDecodificado, referencia: date) -> bool:
    """
    Descarta candidatos que validam por acaso.

    Quatro DVs deixam ~1 em 10.000 sequências aleatórias passar; exigir também
    data e valor plausíveis elimina esses raros falsos positivos.
    """
    # Um "boleto" sem vencimento e sem valor não carrega informação nenhuma —
    # é o formato que uma sequência degenerada (uma fita de zeros do OCR, por
    # exemplo) assume ao passar pelos dígitos verificadores por acidente.
    if decodificado.vencimento is None and decodificado.valor is None:
        return False
    if decodificado.valor is not None and decodificado.valor > VALOR_MAXIMO_PLAUSIVEL:
        return False
    if decodificado.vencimento is not None:
        distancia_anos = abs((decodificado.vencimento - referencia).days) / 365.25
        if distancia_anos > ANOS_TOLERANCIA_VENCIMENTO:
            return False
    return True


# --------------------------------------------------------------------------- #
# Correção de OCR guiada pelos dígitos verificadores
# --------------------------------------------------------------------------- #

def normalizar_confusoes(texto: str) -> str:
    """Troca letras tipicamente confundidas pelo OCR por seus dígitos."""
    return "".join(MAPA_LETRAS_PARA_DIGITOS.get(caractere, caractere) for caractere in texto)


def _variacoes(digitos: str, max_substituicoes: int) -> Iterator[str]:
    """
    Gera variações do candidato trocando dígitos por seus confundíveis.

    Emite primeiro as variações com menos alterações — a correção mais
    conservadora que valida é a que queremos.
    """
    yield digitos
    posicoes = range(len(digitos))
    tentativas = 0

    for quantidade in range(1, max_substituicoes + 1):
        for combinacao in itertools.combinations(posicoes, quantidade):
            alternativas = [CONFUSOES_ENTRE_DIGITOS.get(digitos[posicao], "") for posicao in combinacao]
            if not all(alternativas):
                continue
            for trocas in itertools.product(*alternativas):
                tentativas += 1
                if tentativas > MAX_TENTATIVAS_CORRECAO:
                    logger.debug("Correção por DV interrompida: limite de tentativas atingido.")
                    return
                caracteres = list(digitos)
                for posicao, novo in zip(combinacao, trocas):
                    caracteres[posicao] = novo
                yield "".join(caracteres)


def corrigir_por_dv(digitos: str, max_substituicoes: int = 2) -> Optional[str]:
    """
    Tenta consertar uma linha digitável quebrada pelo OCR usando os DVs.

    Retorna a primeira variação (com o menor número de trocas) cujos quatro
    dígitos verificadores fecham, ou None se nenhuma fechar.
    """
    if len(digitos) != TAMANHO_LINHA_BANCARIA or not digitos.isdigit():
        return None
    for candidato in _variacoes(digitos, max_substituicoes):
        if validar_linha_digitavel(candidato):
            return candidato
    return None


# --------------------------------------------------------------------------- #
# Busca em texto livre de OCR
# --------------------------------------------------------------------------- #

def _janelas_de_digitos(sequencia: str) -> Iterator[str]:
    """Percorre uma sequência longa emitindo todas as janelas de 47 dígitos."""
    for inicio in range(0, len(sequencia) - TAMANHO_LINHA_BANCARIA + 1):
        yield sequencia[inicio:inicio + TAMANHO_LINHA_BANCARIA]


def encontrar_linha_digitavel(
    texto: str,
    referencia: Optional[date] = None,
    tentar_corrigir: bool = True,
) -> Optional[BoletoDecodificado]:
    """
    Procura uma linha digitável válida em texto livre (OCR ou PDF digital).

    A estratégia é: isolar sequências longas de dígitos (aceitando os
    caracteres que o OCR confunde), normalizá-las, e testar cada janela de 47
    dígitos contra os dígitos verificadores. Só é aceito o candidato que
    valida — por isso não há risco de "achar" uma linha digitável onde não há.

    Quando nenhuma janela valida diretamente, tentamos corrigir erros de OCR
    usando os próprios DVs como oráculo (ver corrigir_por_dv).
    """
    if not texto:
        return None

    referencia = referencia or date.today()
    candidatos_normalizados: list[str] = []

    for trecho in REGEX_SEQUENCIA.findall(texto):
        digitos = re.sub(r"[^\d]", "", normalizar_confusoes(trecho))
        if len(digitos) < TAMANHO_LINHA_BANCARIA:
            continue
        candidatos_normalizados.append(digitos)

        for janela in _janelas_de_digitos(digitos):
            if not validar_linha_digitavel(janela):
                continue
            decodificado = decodificar(janela, referencia)
            if _resultado_e_plausivel(decodificado, referencia):
                logger.info("Linha digitável validada pelos DVs: %s", decodificado.linha_formatada)
                return decodificado

    if not tentar_corrigir:
        return None

    # Nenhuma janela fechou: o OCR provavelmente trocou um ou dois dígitos.
    for digitos in candidatos_normalizados:
        for janela in _janelas_de_digitos(digitos):
            corrigida = corrigir_por_dv(janela)
            if corrigida is None:
                continue
            decodificado = decodificar(corrigida, referencia)
            if _resultado_e_plausivel(decodificado, referencia):
                logger.info(
                    "Linha digitável recuperada por correção de OCR: %s (lida como %s)",
                    decodificado.linha_formatada,
                    janela,
                )
                return decodificado

    return None
