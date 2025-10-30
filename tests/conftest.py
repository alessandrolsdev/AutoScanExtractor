# -*- coding: utf-8 -*-
"""
tests/conftest.py

Este arquivo de configuração especial do Pytest define fixtures
que são usadas globalmente por todos os testes.
"""

import pytest
import sys
import os

# Adiciona o diretório raiz (um nível acima da pasta 'tests') ao path do Python.
# Isso permite que os testes importem os módulos do seu projeto, como o 'config'.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Agora podemos importar do seu código-fonte
from config import setup_tesseract

@pytest.fixture(scope="session", autouse=True)
def setup_global_tesseract(request):
    """
    Esta fixture roda automaticamente (autouse=True) uma vez por
    sessão de teste (scope="session").
    
    Ela chama a função setup_tesseract() para garantir que o Pytesseract
    saiba onde encontrar o tesseract.exe ANTES que qualquer teste
    que precise dele seja executado.
    """
    print("\n[Pytest Setup] Configurando Tesseract para a sessão de teste...")
    setup_tesseract()
    print("[Pytest Setup] Tesseract configurado com sucesso.")