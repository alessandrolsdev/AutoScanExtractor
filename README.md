# AutoScanExtractor 🤖 (Extrator de Boletos)

> Ferramenta em Python que extrai **vencimento, valor, beneficiário, pagador e código de barras** de boletos bancários (PDF ou imagem) e os organiza em uma planilha Excel — pela interface gráfica ou pela linha de comando.

Este projeto foi criado como parte de um portfólio de desenvolvimento, demonstrando automação de processos (RPA), arquitetura modular, OCR e interfaces gráficas.

![Demonstração do Bot](assets/app.jpg)

---

## 📖 Sobre o Projeto

Digitar boleto a boleto em uma planilha é trabalho manual, lento e sujeito a erro. Este projeto automatiza o processo: você aponta os arquivos, ele devolve a planilha preenchida.

### A ideia central: o boleto se autoverifica

A maior parte dos extratores de boleto tenta adivinhar onde os dados estão no layout — e cada banco desenha o seu do seu jeito. Só que **a linha digitável já carrega vencimento e valor de forma determinística**, protegida por quatro dígitos verificadores:

| Trecho do código de barras | O que é |
|---|---|
| dígitos 6 a 9 | **fator de vencimento** — dias desde 07/10/1997 |
| dígitos 10 a 19 | **valor do documento**, em centavos |
| 3 DVs módulo 10 + 1 DV módulo 11 | conferência da leitura |

Por isso a extração acontece em camadas, da mais confiável para a menos:

1. **Linha digitável** — se os DVs fecham, vencimento e valor saem por aritmética, não por palpite. Os próprios DVs também servem de corretor de OCR: lendo `O` no lugar de `0`, o programa testa as variantes e fica com a que fecha a conta.
2. **Texto digital do PDF** — quando existe camada de texto, é lida direto, sem OCR.
3. **Regex sobre o texto** — resolve beneficiário e pagador, que a linha digitável não carrega.
4. **Posicional** — usa as coordenadas X/Y das palavras para achar o que a regex não achou, por proximidade dos rótulos.

Uma camada nunca sobrescreve o resultado de outra mais confiável.

## 🚀 Funcionalidades

* **Interface gráfica** em Tkinter, com processamento em lote e barra de progresso.
* **Linha de comando** para automação e uso em servidor — o mesmo motor da GUI.
* **Modo de inspeção visual**: abre o boleto com um retângulo colorido sobre cada dado encontrado, mostrando **de onde** cada informação foi lida.
* **PDF e imagem**: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.gif`.
* **Validação por dígito verificador**, com correção de erros de OCR guiada pelos DVs.
* **Planilha tipada**: vencimento sai como data e valor como número — dá para ordenar, filtrar e somar direto no Excel.
* **Rastreabilidade**: cada linha registra a origem de cada dado e o que ficou faltando.

## 🖼️ Modo de inspeção

Serve para responder "de onde saiu esse número?" antes de confiar na planilha.

```bash
autoscan inspecionar boleto.pdf
```

```
Arquivo: boleto.pdf
Linha digitável: válida (dígitos verificadores conferem)
  ✓ Vencimento: 17/11/2025  [linha digitável]
  ✓ Valor do Documento: R$ 535,71  [linha digitável]
  ✓ Beneficiário: Sociedade de Ensino Superior Estacio de Sa  [regex (OCR)]
  ✓ Pagador: ALESSANDRO LIMA DA SILVA  [regex (OCR)]
  ✓ Código de Barras: 03399.00672 41210.101527 30991.101012 6 12680000053571  [linha digitável]

Imagem anotada: boleto_anotado.png
```

Na interface gráfica, o mesmo recurso está no botão **"Inspecionar um arquivo..."**, que abre a página com as marcações e uma legenda lateral com valor, origem e posição de cada campo.

Quando um dado vem da linha digitável mas o campo impresso não é legível no OCR, a marcação é feita sobre a própria linha digitável — que é, de fato, de onde o dado veio.

---

## 🏁 Como usar

### 1. Executável do Windows (sem instalar nada)

Baixe o `.zip` em **[Releases](https://github.com/alessandrolsdev/auto-scan-extractor/releases)** e extraia. O Tesseract já vem embutido.

* **Interface gráfica:** abra `AutoScanExtractor.exe` com dois cliques.
* **Linha de comando:** o mesmo executável aceita argumentos.

```cmd
AutoScanExtractor.exe extrair -e C:\boletos -s planilha.xlsx
AutoScanExtractor.exe inspecionar boleto.pdf
```

### 2. Rodando a partir do código

Você precisa do **Tesseract OCR** instalado:

* **Windows:** [instalador da UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) — marque o idioma "Portuguese" em *Additional language data*.
* **macOS:** `brew install tesseract tesseract-lang`
* **Linux:** `sudo apt-get install tesseract-ocr tesseract-ocr-por`

```bash
git clone https://github.com/alessandrolsdev/auto-scan-extractor.git
cd auto-scan-extractor
python -m venv venv && source venv/bin/activate    # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
```

Se o Tesseract estiver em um caminho fora do comum, aponte a variável `TESSERACT_CMD` para o executável — ela tem prioridade sobre a busca automática.

---

## 💻 Linha de comando

```bash
python main.py                                      # abre a interface gráfica
python main.py extrair -e boletos/ -s planilha.xlsx # processa uma pasta
python main.py extrair -e a.pdf b.jpg -s saida.xlsx # processa arquivos avulsos
python main.py extrair -e boletos/ -r              # inclui subpastas
python main.py inspecionar boleto.pdf              # mostra onde cada dado está
```

Instalando o pacote (`pip install -e .`), o comando `autoscan` fica disponível direto no terminal.

| Comando | O que faz |
|---|---|
| `extrair` | processa arquivos/pastas em lote e grava a planilha |
| `inspecionar` | analisa um arquivo e gera a imagem anotada |
| `gui` | abre a interface gráfica |

Opções úteis de `extrair`: `-r/--recursivo`, `--sem-planilha` (só imprime), `--reprocessar` (ignora o controle de duplicados), `-v/--verboso`.

O código de saída é `0` em caso de sucesso e `1` em caso de falha, o que permite encadear o comando em scripts.

## 📊 A planilha de saída

| Coluna | Conteúdo |
|---|---|
| `Arquivo_Origem` | nome do arquivo processado |
| `Vencimento` | data (tipo data no Excel) |
| `Pagador`, `Beneficiário` | nomes extraídos |
| `Valor_Documento` | número (somável no Excel) |
| `Codigo_Barras` | linha digitável formatada |
| `Codigo_Barras_Valido` | se os dígitos verificadores fecharam |
| `Status` | `OK` ou o que ficou faltando |
| `Origem_Dados` | de qual camada veio cada campo |

Reprocessar a mesma pasta não duplica registros: arquivos já presentes são ignorados, e boletos com o mesmo código de barras válido são consolidados.

---

## 🧪 Testes

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

A suíte cobre a aritmética dos dígitos verificadores, a decodificação do fator de vencimento (inclusive o reinício da contagem em fevereiro de 2025), a conversão de tipos, a consolidação da planilha e o pipeline completo com os boletos reais em `tests/test_data` — com os valores esperados afirmados explicitamente, não apenas "extraiu alguma coisa".

## 🛠️ Estrutura

```
+-- assets/                 # ícones e imagens
+-- tests/                  # suíte pytest + amostras reais
|
+-- linha_digitavel.py      # DVs, fator de vencimento, correção de OCR
+-- boleto_data.py          # modelo de dados tipado, com origem e posição
+-- extraction_logic.py     # BoletoParser: regex + posicional + localização
+-- file_processor.py       # leitura de PDF/imagem e orquestração das camadas
+-- planilha.py             # consolidação e escrita do Excel
+-- extractor_service.py    # processamento em lote (sem GUI)
+-- visualizer.py           # desenho das anotações do modo de inspeção
+-- gui.py                  # interface Tkinter
+-- cli.py                  # linha de comando
+-- main.py                 # ponto de entrada
|
+-- AutoScanExtractor.spec  # build do PyInstaller
+-- pyproject.toml          # dependências, pytest e ruff
```

O motor de extração não conhece Tkinter, e a GUI não conhece regex: dá para usar o projeto como biblioteca, na linha de comando ou pela janela, sem duplicar lógica.

## 📦 Gerando o executável

```bash
pip install -r requirements-dev.txt
pyinstaller AutoScanExtractor.spec
```

O executável sai em `dist/`. Para embutir o Tesseract e deixar o `.exe` autossuficiente, defina `TESSERACT_DIR` antes de compilar:

```cmd
set TESSERACT_DIR=C:\Program Files\Tesseract-OCR
pyinstaller AutoScanExtractor.spec
```

O workflow `.github/workflows/release.yml` faz exatamente isso ao receber uma tag `v*`: compila no Windows, roda a suíte de testes lá, e publica o `.zip` na página de Releases.

## 🧰 Tecnologias

Python 3 · Tkinter · Tesseract OCR (via Pytesseract) · PyMuPDF · OpenCV · Pillow · Pandas · Openpyxl · PyInstaller · Pytest · Ruff

## 📝 Licença

MIT. Feito por **Alessandro Lima da Silva** ([@alessandrolsdev](https://github.com/alessandrolsdev))
