# -*- coding: utf-8 -*-
"""
boleto_data.py

Modelo de dados do boleto extraído.

Cada campo carrega, além do valor, três metadados que o resto do sistema usa:

    * ``texto_bruto`` — exatamente como apareceu no documento, o que permite
      localizar o campo na imagem (modo de inspeção visual);
    * ``origem`` — de onde o dado veio, o que dá uma noção direta de confiança
      (linha digitável > texto digital > regex > posicional);
    * ``regiao`` — onde o dado está na página, em pixels da imagem renderizada.

Os valores são tipados (``date``, ``Decimal``) em vez de strings: datas
ordenam, valores somam, e campos ausentes são ``None`` — não a string
"Não encontrado", que antes era comparada por igualdade em vários módulos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional


class Origem:
    """De onde veio um campo extraído, da mais confiável para a menos."""

    LINHA_DIGITAVEL = "linha digitável"
    PDF_DIGITAL = "texto digital"
    REGEX = "regex (OCR)"
    POSICIONAL = "posicional (OCR)"

    #: Ordem de precedência: um dado de origem melhor nunca é sobrescrito.
    PRECEDENCIA = {
        LINHA_DIGITAVEL: 4,
        PDF_DIGITAL: 3,
        REGEX: 2,
        POSICIONAL: 1,
    }

    @classmethod
    def peso(cls, origem: Optional[str]) -> int:
        return cls.PRECEDENCIA.get(origem or "", 0)


@dataclass
class Regiao:
    """Retângulo de um campo na página, em pixels da imagem renderizada."""

    x: int
    y: int
    largura: int
    altura: int
    pagina: int = 0


@dataclass
class Campo:
    """Um campo extraído, com valor tipado e rastreabilidade."""

    valor: Any = None
    texto_bruto: Optional[str] = None
    origem: Optional[str] = None
    regiao: Optional[Regiao] = None

    #: True quando a região não é a do próprio dado, e sim a da linha digitável
    #: que o gerou — caso comum quando o campo impresso não é legível no OCR.
    regiao_herdada: bool = False

    @property
    def encontrado(self) -> bool:
        return self.valor is not None

    def definir(self, valor: Any, texto_bruto: Optional[str] = None,
                origem: Optional[str] = None) -> bool:
        """
        Preenche o campo, respeitando a precedência das origens.

        Um dado vindo da linha digitável nunca é sobrescrito por um palpite de
        regex — era exatamente isso que acontecia antes, quando o resultado do
        modo digital era descartado ao cair no OCR.
        """
        if valor is None:
            return False
        if self.encontrado and Origem.peso(origem) <= Origem.peso(self.origem):
            return False
        self.valor = valor
        self.texto_bruto = texto_bruto if texto_bruto is not None else str(valor)
        self.origem = origem
        return True


#: Texto usado nas colunas de texto da planilha quando o dado não foi achado.
TEXTO_NAO_ENCONTRADO = "Não encontrado"


def formatar_moeda(valor: Optional[Decimal]) -> str:
    """
    Formata um valor no padrão brasileiro: ``R$ 1.234,56``.

    Feito na mão porque depender de locale exigiria que o pt_BR estivesse
    instalado na máquina — o que não vale supor em um executável distribuído.
    """
    if valor is None:
        return "—"
    return "R$ " + f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


@dataclass
class BoletoData:
    """Dados extraídos de um boleto."""

    arquivo_origem: str
    vencimento: Campo = field(default_factory=Campo)
    valor_documento: Campo = field(default_factory=Campo)
    beneficiario: Campo = field(default_factory=Campo)
    pagador: Campo = field(default_factory=Campo)
    codigo_barras: Campo = field(default_factory=Campo)

    linha_digitavel_valida: bool = False
    paginas: int = 1

    #: Campos que definem se a extração "deu certo" e disparam os fallbacks.
    CAMPOS_PRINCIPAIS = ("vencimento", "valor_documento", "beneficiario")

    NOMES_LEGIVEIS = {
        "vencimento": "Vencimento",
        "valor_documento": "Valor do Documento",
        "beneficiario": "Beneficiário",
        "pagador": "Pagador",
        "codigo_barras": "Código de Barras",
    }

    # --- Acesso aos campos -------------------------------------------------

    def campos(self) -> Dict[str, Campo]:
        """Todos os campos extraíveis, na ordem de declaração."""
        return {
            nome: getattr(self, nome)
            for nome in ("vencimento", "valor_documento", "beneficiario",
                         "pagador", "codigo_barras")
        }

    def campos_faltantes(self, apenas_principais: bool = True) -> List[str]:
        """Nomes dos campos ainda não preenchidos."""
        alvos = self.CAMPOS_PRINCIPAIS if apenas_principais else tuple(self.campos())
        return [nome for nome in alvos if not getattr(self, nome).encontrado]

    def esta_completo(self) -> bool:
        """True quando todos os campos principais foram encontrados."""
        return not self.campos_faltantes()

    def tem_algum_dado(self) -> bool:
        """True se pelo menos um campo foi extraído."""
        return any(campo.encontrado for campo in self.campos().values())

    # --- Saída -------------------------------------------------------------

    @property
    def status(self) -> str:
        """Resumo legível do que foi ou não encontrado."""
        faltantes = self.campos_faltantes()
        if not faltantes:
            return "OK"
        return "Faltando: " + ", ".join(self.NOMES_LEGIVEIS[nome] for nome in faltantes)

    def to_row(self) -> Dict[str, Any]:
        """
        Converte para uma linha da planilha.

        Datas e valores saem como tipos nativos, para que o Excel consiga
        ordenar, filtrar e somar as colunas.
        """
        origens = {
            self.NOMES_LEGIVEIS[nome]: campo.origem
            for nome, campo in self.campos().items()
            if campo.encontrado and campo.origem
        }
        return {
            "Arquivo_Origem": self.arquivo_origem,
            "Vencimento": self.vencimento.valor,
            "Pagador": self.pagador.valor or TEXTO_NAO_ENCONTRADO,
            "Beneficiário": self.beneficiario.valor or TEXTO_NAO_ENCONTRADO,
            "Valor_Documento": (
                float(self.valor_documento.valor)
                if isinstance(self.valor_documento.valor, Decimal)
                else self.valor_documento.valor
            ),
            "Codigo_Barras": self.codigo_barras.valor or TEXTO_NAO_ENCONTRADO,
            "Codigo_Barras_Valido": "Sim" if self.linha_digitavel_valida else "Não",
            "Status": self.status,
            "Origem_Dados": "; ".join(f"{campo}: {origem}" for campo, origem in origens.items()),
        }

    def resumo(self) -> str:
        """Uma linha de log com o essencial da extração."""
        venc = self.vencimento.valor.strftime("%d/%m/%Y") if isinstance(self.vencimento.valor, date) else "—"
        valor = formatar_moeda(self.valor_documento.valor)
        selo = " [DV ok]" if self.linha_digitavel_valida else ""
        return f"venc: {venc} | valor: {valor}{selo}"


#: Ordem das colunas na planilha de saída.
COLUNAS_PLANILHA = [
    "Arquivo_Origem",
    "Vencimento",
    "Pagador",
    "Beneficiário",
    "Valor_Documento",
    "Codigo_Barras",
    "Codigo_Barras_Valido",
    "Status",
    "Origem_Dados",
]
