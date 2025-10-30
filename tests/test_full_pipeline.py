# -*- coding: utf-8 -*-
"""
tests/test_full_pipeline.py

Testes de integração (end-to-end) para o pipeline de processamento de arquivos.
Estes testes carregam arquivos reais, rodam o pipeline completo de OCR
e verificam o resultado final.
"""

import pytest
import os
import sys
import dataclasses

# --- Configuração de Caminho ---
# Adiciona a pasta raiz do projeto ao sys.path
# Isso permite que o script de teste importe os módulos do projeto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Importações do Projeto ---
import file_processor
from extraction_logic import BoletoParser
from boleto_data import BoletoData

# --- "Fixtures" (Recursos de Teste) ---

@pytest.fixture(scope="module")
def parser_instance():
    """
    Cria uma instância única do BoletoParser que será usada por todos os testes
    neste arquivo. 'scope="module"' faz com que ele seja criado apenas uma vez.
    """
    print("\n[Fixture] Criando instância do BoletoParser...")
    return BoletoParser()

@pytest.fixture(scope="module")
def test_files():
    """
    Fornece os caminhos absolutos para os nossos arquivos de dados de teste.
    """
    # O diretório 'tests/'
    base_dir = os.path.dirname(__file__) 
    # A subpasta 'tests/test_data/'
    data_dir = os.path.join(base_dir, 'test_data')
    
    pdf_path = os.path.join(data_dir, 'teste.pdf')
    jpg_path = os.path.join(data_dir, 'teste.jpg')
    
    # Verifica se os arquivos realmente existem
    if not os.path.exists(pdf_path):
        pytest.fail(f"Arquivo de teste não encontrado: {pdf_path}")
    if not os.path.exists(jpg_path):
        pytest.fail(f"Arquivo de teste não encontrado: {jpg_path}")
        
    return {"pdf": pdf_path, "jpg": jpg_path}


# --- Testes do Pipeline ---

def test_pipeline_de_pdf(parser_instance, test_files):
    """
    Testa o processamento completo de um arquivo PDF.
    Ele roda o PyMuPDF, Tesseract, Modo 1 (Regex) e Modo 2 (Posicional).
    """
    print(f"\n[TESTE] Processando PDF: {test_files['pdf']}")
    
    # Executa a função de mais alto nível (a mesma que a GUI chama)
    try:
        dados = file_processor.processar_pdf(test_files['pdf'], parser_instance)
    except Exception as e:
        # Se *qualquer* exceção ocorrer durante o processamento, o teste falha.
        pytest.fail(f"processar_pdf() levantou uma exceção inesperada: {e}")

    # --- Verificações (Asserts) ---
    
    # 1. Verifica se o resultado é do tipo correto
    assert isinstance(dados, BoletoData), "A função não retornou um objeto BoletoData"
    
    # 2. Verifica se *algum* dado foi extraído
    # (Este é um "smoke test" - prova que não voltou tudo vazio)
    dados_dict = dataclasses.asdict(dados)
    dados_dict.pop('arquivo_origem', None) # Remove o nome do arquivo da verificação
    
    foi_extraido_algo = any(v != "Não encontrado" for v in dados_dict.values())
    assert foi_extraido_algo, "O pipeline rodou, mas não extraiu nenhum dado do PDF de teste."
    
    print(f"[RESULTADO PDF] Venc: {dados.vencimento}, Valor: {dados.valor_documento}")


def test_pipeline_de_imagem(parser_instance, test_files):
    """
    Testa o processamento completo de um arquivo de Imagem (JPG).
    Ele roda o PIL, OpenCV, Tesseract, Modo 1 (Regex) e Modo 2 (Posicional).
    """
    print(f"\n[TESTE] Processando Imagem: {test_files['jpg']}")
    
    # Executa a função de mais alto nível
    try:
        dados = file_processor.extrair_dados_da_imagem(test_files['jpg'], parser_instance)
    except Exception as e:
        pytest.fail(f"extrair_dados_da_imagem() levantou uma exceção inesperada: {e}")

    # --- Verificações (Asserts) ---
    
    # 1. Verifica o tipo
    assert isinstance(dados, BoletoData), "A função não retornou um objeto BoletoData"
    
    # 2. Verifica se algo foi extraído
    dados_dict = dataclasses.asdict(dados)
    dados_dict.pop('arquivo_origem', None)
    
    foi_extraido_algo = any(v != "Não encontrado" for v in dados_dict.values())
    assert foi_extraido_algo, "O pipeline rodou, mas não extraiu nenhum dado da Imagem de teste."
    
    print(f"[RESULTADO IMG] Venc: {dados.vencimento}, Valor: {dados.valor_documento}")