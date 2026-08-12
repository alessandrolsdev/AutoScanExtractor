# -*- coding: utf-8 -*-
"""
visualizer.py

Desenho das anotações do modo de inspeção.

Recebe a página renderizada e os dados extraídos e devolve uma imagem com um
retângulo colorido sobre cada campo encontrado, identificando *onde* no boleto
cada informação foi lida. É o mesmo código usado pela janela de inspeção da
GUI e pela opção ``--anotar`` da linha de comando — o que torna o recurso
testável sem abrir nenhuma interface gráfica.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from boleto_data import BoletoData

logger = logging.getLogger(__name__)

#: Cor de cada campo, em RGB. Escolhidas para se distinguirem sobre papel branco.
CORES_CAMPOS: Dict[str, Tuple[int, int, int]] = {
    "vencimento": (0, 122, 204),       # azul
    "valor_documento": (0, 153, 68),   # verde
    "beneficiario": (204, 51, 153),    # magenta
    "pagador": (230, 126, 0),          # laranja
    "codigo_barras": (140, 60, 200),   # roxo
}

COR_TEXTO_ROTULO = (255, 255, 255)
ESPESSURA_BORDA = 4
MARGEM_ROTULO = 6

_CAMINHOS_FONTE = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


@dataclass
class ItemLegenda:
    """Uma entrada da legenda mostrada ao lado da imagem anotada."""

    campo: str
    rotulo: str
    cor: Tuple[int, int, int]
    valor: str
    origem: str
    localizado: bool
    posicao_herdada: bool = False

    @property
    def cor_hex(self) -> str:
        return "#{:02x}{:02x}{:02x}".format(*self.cor)

    @property
    def descricao_posicao(self) -> str:
        """Explica ao usuário o que a caixa desenhada representa."""
        if not self.localizado:
            return "sem posição na página"
        if self.posicao_herdada:
            return "marcado sobre a linha digitável (origem do dado)"
        return "marcado no documento"


def _carregar_fonte(tamanho: int) -> ImageFont.ImageFont:
    """Melhor fonte disponível no sistema, com queda para a embutida do PIL."""
    for caminho in _CAMINHOS_FONTE:
        if os.path.isfile(caminho):
            try:
                return ImageFont.truetype(caminho, tamanho)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:  # Pillow < 10.1 não aceita "size"
        return ImageFont.load_default()


def formatar_valor_campo(nome: str, valor) -> str:
    """Formata o valor de um campo para exibição."""
    if valor is None:
        return "não encontrado"
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, Decimal):
        inteiro = f"{valor:,.2f}"
        return "R$ " + inteiro.replace(",", "@").replace(".", ",").replace("@", ".")
    return str(valor)


def montar_legenda(dados: BoletoData) -> List[ItemLegenda]:
    """Monta a legenda com valor, origem e se o campo pôde ser localizado."""
    itens = []
    for nome, campo in dados.campos().items():
        itens.append(
            ItemLegenda(
                campo=nome,
                rotulo=dados.NOMES_LEGIVEIS[nome],
                cor=CORES_CAMPOS.get(nome, (120, 120, 120)),
                valor=formatar_valor_campo(nome, campo.valor),
                origem=campo.origem or "—",
                localizado=campo.regiao is not None,
                posicao_herdada=campo.regiao_herdada,
            )
        )
    return itens


def anotar_pagina(
    imagem: Image.Image,
    dados: BoletoData,
    pagina: int = 0,
    mostrar_rotulos: bool = True,
) -> Image.Image:
    """
    Devolve uma cópia da página com os campos encontrados destacados.

    Campos sem região (não localizados na imagem) simplesmente não são
    desenhados — aparecem apenas na legenda, com a indicação de que o valor foi
    extraído mas não pôde ser apontado na página.
    """
    anotada = imagem.convert("RGB").copy()
    desenho = ImageDraw.Draw(anotada)

    # A fonte acompanha o tamanho da página para o rótulo ficar legível em
    # qualquer resolução de renderização.
    tamanho_fonte = max(14, int(anotada.width / 60))
    fonte = _carregar_fonte(tamanho_fonte)

    # Campos que herdaram a região da linha digitável são desenhados
    # ligeiramente maiores a cada um, para que as caixas fiquem aninhadas e
    # visíveis em vez de exatamente sobrepostas.
    herdados = 0

    for nome, campo in dados.campos().items():
        regiao = campo.regiao
        if regiao is None or regiao.pagina != pagina:
            continue

        cor = CORES_CAMPOS.get(nome, (120, 120, 120))
        if campo.regiao_herdada:
            herdados += 1
            margem = ESPESSURA_BORDA + herdados * 7
            espessura = 2
        else:
            margem = ESPESSURA_BORDA
            espessura = ESPESSURA_BORDA

        caixa = (
            max(0, regiao.x - margem),
            max(0, regiao.y - margem),
            min(anotada.width, regiao.x + regiao.largura + margem),
            min(anotada.height, regiao.y + regiao.altura + margem),
        )
        desenho.rectangle(caixa, outline=cor, width=espessura)

        if not mostrar_rotulos:
            continue

        rotulo = dados.NOMES_LEGIVEIS[nome]
        esquerda, topo, direita, base = desenho.textbbox((0, 0), rotulo, font=fonte)
        largura_rotulo = direita - esquerda + 2 * MARGEM_ROTULO
        altura_rotulo = base - topo + 2 * MARGEM_ROTULO

        # Acima da caixa; se não couber, desenha abaixo.
        y_rotulo = caixa[1] - altura_rotulo
        if y_rotulo < 0:
            y_rotulo = caixa[3]
        x_rotulo = min(caixa[0], anotada.width - largura_rotulo)

        desenho.rectangle(
            (x_rotulo, y_rotulo, x_rotulo + largura_rotulo, y_rotulo + altura_rotulo),
            fill=cor,
        )
        desenho.text(
            (x_rotulo + MARGEM_ROTULO, y_rotulo + MARGEM_ROTULO - topo),
            rotulo,
            fill=COR_TEXTO_ROTULO,
            font=fonte,
        )

    return anotada


def salvar_anotacao(
    imagem: Image.Image,
    dados: BoletoData,
    caminho_saida: str,
    pagina: int = 0,
) -> str:
    """Anota a página e grava em disco. Devolve o caminho gravado."""
    anotada = anotar_pagina(imagem, dados, pagina=pagina)
    pasta = os.path.dirname(os.path.abspath(caminho_saida))
    os.makedirs(pasta, exist_ok=True)
    anotada.save(caminho_saida)
    logger.info("Imagem anotada salva em %s", caminho_saida)
    return caminho_saida


def redimensionar_para_caber(
    imagem: Image.Image, largura_max: int, altura_max: int
) -> Tuple[Image.Image, float]:
    """
    Reduz a imagem para caber na área disponível, preservando a proporção.

    Devolve ``(imagem, escala)`` — a escala é necessária para converter cliques
    e coordenadas entre a imagem exibida e a original.
    """
    if imagem.width <= 0 or imagem.height <= 0:
        return imagem, 1.0
    escala = min(largura_max / imagem.width, altura_max / imagem.height, 1.0)
    if escala >= 1.0:
        return imagem, 1.0
    novo_tamanho = (max(1, int(imagem.width * escala)), max(1, int(imagem.height * escala)))
    return imagem.resize(novo_tamanho, Image.LANCZOS), escala


def descrever_extracao(dados: BoletoData) -> str:
    """Resumo textual da inspeção, usado na CLI e no log da GUI."""
    linhas = [f"Arquivo: {dados.arquivo_origem}"]
    if dados.linha_digitavel_valida:
        linhas.append("Linha digitável: válida (dígitos verificadores conferem)")
    else:
        linhas.append("Linha digitável: não validada")

    for item in montar_legenda(dados):
        marcador = "✓" if item.valor != "não encontrado" else "✗"
        posicao = "" if (item.localizado and not item.posicao_herdada) else f"  → {item.descricao_posicao}"
        linhas.append(f"  {marcador} {item.rotulo}: {item.valor}  [{item.origem}]{posicao}")
    return "\n".join(linhas)


def pagina_com_campos(resultado_paginas: List, dados: BoletoData) -> Optional[int]:
    """Índice da primeira página que tem algum campo localizado."""
    paginas_com_regiao = {
        campo.regiao.pagina for campo in dados.campos().values() if campo.regiao is not None
    }
    if not paginas_com_regiao:
        return 0 if resultado_paginas else None
    return min(paginas_com_regiao)
