# -*- coding: utf-8 -*-
"""
tests/test_extraction_logic.py

Testes unitários para a classe BoletoParser.
"""

# 1. Importa a biblioteca de teste
import pytest

# 2. Importa a classe que queremos testar
# (Como estamos na pasta 'tests', precisamos dizer ao Python para olhar um nível acima '..')
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from extraction_logic import BoletoParser


# 3. Criamos uma instância "dummy" do nosso Parser para os testes
# Não precisamos de um texto real no __init__, pois vamos testar métodos individuais.
@pytest.fixture
def parser():
    """Cria uma instância reutilizável do BoletoParser para todos os testes."""
    return BoletoParser()


# 4. Escrevemos nossa primeira função de teste
# O nome DEVE começar com "test_"
def test_extrair_vencimento_regex_contexto_simples(parser):
    """
    Testa o "caminho feliz" (happy path) da extração de vencimento.
    """
    print("Executando: test_extrair_vencimento_regex_contexto_simples")
    
    # Texto de exemplo que simula um OCR
    texto_de_teste = """
    Pagador: Sr. Ninguém
    Beneficiário: Empresa Fictícia
    Vencimento: 01/01/2025
    Valor: R$ 100,00
    """
    
    # Chama o método que queremos testar
    # (Sim, podemos testar métodos "privados" com _ no pytest)
    data_encontrada = parser._extrair_vencimento_regex_contexto(texto_de_teste)
    
    # A MÁGICA: Verificamos se o resultado é o que esperamos.
    assert data_encontrada == "01/01/2025"

def test_extrair_vencimento_regex_contexto_fallback_proximidade(parser):
    """
    Testa o seu "Fallback 1", que procura pela palavra 'venc' perto de uma data.
    """
    print("Executando: test_extrair_vencimento_regex_contexto_fallback_proximidade")
    
    texto_de_teste = """
    Documento emitido em 10/12/2024
    ...
    Algum texto aleatório
    Data de venc. 15/02/2025
    ...
    """
    
    data_encontrada = parser._extrair_vencimento_regex_contexto(texto_de_teste)
    
    # Verifica se ele ignorou 10/12/2024 e pegou a data correta
    assert data_encontrada == "15/02/2025"

def test_extrair_vencimento_regex_contexto_fallback_data_recente(parser):
    """
    Testa o seu "Fallback 2", que pega a data mais recente se
    nenhuma estiver perto da palavra 'venc'.
    """
    print("Executando: test_extrair_vencimento_regex_contexto_fallback_data_recente")
    
    texto_de_teste = """
    Data Emissão: 01/12/2024
    Data Documento: 05/12/2024
    Data Limite: 25/12/2024
    """
    
    data_encontrada = parser._extrair_vencimento_regex_contexto(texto_de_teste)
    
    # Verifica se ele pegou a data mais recente (25/12/2024)
    assert data_encontrada == "25/12/2024"

def test_extrair_vencimento_regex_contexto_falha(parser):
    """
    Testa o que acontece se nenhuma data for encontrada.
    """
    print("Executando: test_extrair_vencimento_regex_contexto_falha")
    
    texto_de_teste = "Isso é apenas um texto aleatório sem nenhuma data."
    
    data_encontrada = parser._extrair_vencimento_regex_contexto(texto_de_teste)
    
    # Verifica se o método retorna None (como ele deve fazer)
    assert data_encontrada is None