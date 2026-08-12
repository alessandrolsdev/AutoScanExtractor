# -*- coding: utf-8 -*-
"""
tests/conftest.py

Fixtures compartilhadas pela suíte.

O ``sys.path`` não é mais manipulado aqui: o ``pyproject.toml`` define
``pythonpath = ["."]`` para o pytest, o que resolve os imports do projeto sem
gambiarra em cada arquivo de teste.
"""

import os
from datetime import date
from decimal import Decimal

import pytest

import linha_digitavel as ld
from config import setup_tesseract

DIRETORIO_DADOS = os.path.join(os.path.dirname(__file__), "test_data")


@pytest.fixture(scope="session", autouse=True)
def tesseract_configurado():
    """Localiza o Tesseract uma única vez para toda a sessão de testes."""
    setup_tesseract()


@pytest.fixture(scope="session")
def parser():
    """Instância reutilizável do parser."""
    from extraction_logic import BoletoParser

    return BoletoParser()


@pytest.fixture(scope="session")
def arquivos_teste():
    """Caminhos das amostras reais versionadas no repositório."""
    caminhos = {
        "pdf": os.path.join(DIRETORIO_DADOS, "teste.pdf"),
        "jpg": os.path.join(DIRETORIO_DADOS, "teste.jpg"),
    }
    for tipo, caminho in caminhos.items():
        if not os.path.exists(caminho):
            pytest.fail(f"Arquivo de teste ausente ({tipo}): {caminho}")
    return caminhos


def gerar_linha_digitavel(
    venc: date = date(2026, 9, 15),
    valor: Decimal = Decimal("1234.56"),
    banco: str = "341",
    campo_livre: str = "1790001043510049102015000",
) -> str:
    """
    Monta uma linha digitável válida para os testes.

    Gerar em vez de embutir uma constante garante que o teste exercite a
    aritmética real dos dígitos verificadores, e não uma string decorada.
    """
    fator = (venc - ld.DATA_REINICIO_CICLO).days + ld.FATOR_MINIMO
    centavos = int(valor * 100)
    sem_dv = f"{banco}9{fator:04d}{centavos:010d}{campo_livre}"
    dv = ld.modulo11_codigo_barras(sem_dv)
    codigo = f"{banco}9{dv}{fator:04d}{centavos:010d}{campo_livre}"
    return ld.codigo_barras_para_linha(codigo)


@pytest.fixture
def boleto_digital(tmp_path):
    """
    Cria um PDF **com camada de texto** — o caso que não era testado.

    A ausência exata deste cenário na suíte permitiu que um ``NameError`` no
    caminho de PDF digital sobrevivesse: a única amostra versionada é um PDF
    escaneado, que nunca entra nesse ramo do código.
    """
    import fitz

    venc = date(2026, 3, 10)
    valor = Decimal("2500.00")
    linha = ld.formatar_linha_digitavel(gerar_linha_digitavel(venc=venc, valor=valor))

    texto = (
        "BANCO DE TESTES S/A            001-9\n"
        f"{linha}\n"
        "Local de Pagamento: pagável em qualquer banco\n"
        "Vencimento: 10/03/2026\n"
        "Beneficiário: EMPRESA EXEMPLO LTDA CNPJ 12.345.678/0001-90\n"
        "Agência/Código do Beneficiário: 1234 / 567890-1\n"
        "Data do Documento: 01/03/2026\n"
        "(=) Valor do Documento    2.500,00\n"
        "Pagador: JOAO DA SILVA CPF: 123.456.789-00\n"
        "Rua das Flores, 100 - Centro\n"
    )

    caminho = tmp_path / "boleto_digital.pdf"
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_text((50, 60), texto, fontsize=11, fontname="helv")
    documento.save(str(caminho))
    documento.close()

    return {
        "caminho": str(caminho),
        "vencimento": venc,
        "valor": valor,
        "linha_digitavel": linha,
    }
