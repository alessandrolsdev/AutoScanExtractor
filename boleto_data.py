# -*- coding: utf-8 -*-
"""
boleto_data.py

Define o modelo de dados (dataclass) para armazenar as informações
extraídas de um boleto.
"""

import dataclasses

@dataclasses.dataclass
class BoletoData:
    """
    Classe de dados para armazenar os resultados da extração do boleto.
    Substitui o uso de dicionários soltos, garantindo uma estrutura
    de dados consistente e autodocumentada.
    """
    arquivo_origem: str
    vencimento: str = "Não encontrado"
    valor_documento: str = "Não encontrado"
    beneficiario: str = "Não encontrado"
    pagador: str = "Não encontrado"
    codigo_barras: str = "Não encontrado"