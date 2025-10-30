# AutoScanExtractor 🤖 (Extrator de Boletos)

> Ferramenta em Python com GUI (Tkinter) que extrai dados-chave (Vencimento, Valor, Pagador) de **boletos bancários** (PDF ou Imagem) e os organiza em uma planilha Excel.

Este projeto foi criado como parte de um portfólio de desenvolvimento, demonstrando habilidades em automação de processos (RPA), arquitetura de software modular, reconhecimento óptico de caracteres (OCR) e desenvolvimento de interfaces gráficas.

![Demonstração do Bot](assets/app.jpg) 

---

## 📖 Sobre o Projeto

Este projeto resolve o problema da digitação manual de boletos em sistemas de controle financeiro. Em vez de um operador digitar "Vencimento", "Valor" e "Código de Barras" de dezenas de PDFs e imagens de boletos, este bot automatiza todo o processo:

1.  O usuário seleciona os arquivos (PDFs ou Imagens) ou uma pasta inteira.
2.  O usuário define onde deseja salvar a planilha de saída.
3.  O bot processa cada arquivo em lote, usando uma **lógica híbrida**:
    * **Se for PDF Digital:** Tenta extrair o texto diretamente, sem OCR (Modo 1 - Regex).
    * **Se for PDF de Imagem ou .jpg/.png:** Aplica pré-processamento (OpenCV) e usa OCR (Tesseract) (Modo 1 - Regex).
    * **Se o Modo 1 falhar:** Ativa um **Modo 2 (Posicional)**, que usa as coordenadas X/Y do texto para encontrar dados que o Regex não pegou (ex: "encontrar a data mais próxima da palavra 'Vencimento'").
4.  Os dados são consolidados em uma única planilha Excel, pronta para uso.

## 🚀 Funcionalidades Principais

* **Interface Gráfica (GUI):** Criada com `Tkinter` e `TTK` para ser moderna e intuitiva.
* **Processamento em Lote:** Processa centenas de arquivos de uma só vez.
* **Suporte a PDF e Imagem:** Processa arquivos `.pdf`, `.png`, `.jpg`, `.jpeg`, e mais.
* **Extração Híbrida (Digital + OCR):** Detecta se um PDF é digital (baseado em texto) ou escaneado (baseado em imagem) e escolhe a melhor estratégia.
* **Lógica Híbrida (Regex + Posicional):** Usa Regex para a extração rápida (Modo 1) e uma lógica de *fallback* baseada em coordenadas (Modo 2) para boletos difíceis.
* **Pré-processamento de Imagem:** Utiliza `OpenCV` para aplicar filtros (binarização, redimensionamento) em imagens antes do OCR, melhorando drasticamente a precisão.
* **Arquitetura Modular (MVC/Serviços):** O código é limpo e separado em responsabilidades (GUI, Lógica de Extração, Processador de Arquivos, Configuração).
* **Empacotamento `.exe`:** Configurado com `PyInstaller` para gerar um executável único que embute o Tesseract e todas as dependências, sem necessidade de instalação.
* **Testes Unitários:** A lógica de extração é coberta por testes `pytest`, garantindo que futuras mudanças não quebrem o código.

## 🛠️ Tecnologias Utilizadas

* **[Python 3](https://www.python.org/)**
* **[Tkinter](https://docs.python.org/3/library/tkinter.html)** - Para a interface gráfica.
* **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)** - A engine principal de reconhecimento de caracteres.
* **[Pytesseract](https://pypi.org/project/pytesseract/)** - O "wrapper" Python para se comunicar com o Tesseract.
* **[Pandas](https://pandas.pydata.org/)** - Para manipulação e exportação dos dados.
* **[Pillow (PIL)](https://python-pillow.org/)** - Para abrir imagens e gerenciar ícones da GUI.
* **[PyMuPDF (fitz)](https://pypi.org/project/PyMuPDF/)** - Para extrair texto e renderizar imagens de arquivos PDF.
* **[OpenCV (opencv-python-headless)](https://pypi.org/project/opencv-python-headless/)** - Para o pré-processamento de imagens.
* **[Numpy](https://numpy.org/)** - Dependência principal do OpenCV.
* **[Openpyxl](https://pypi.org/project/openpyxl/)** - Dependência do Pandas para escrever arquivos `.xlsx`.
* **[PyInstaller](https://pyinstaller.org/)** - Para empacotar a aplicação em um `.exe`.
* **[Pytest](https://pytest.org/)** - Para testes unitários.

---

## 🏁 Como Usar

### 1. Pré-requisitos (Para o Executável `.exe`)

* Nenhum! Basta baixar o `.zip` da seção **[Releases](https://github.com/alessandrolsdev/AutoScanExtractor/releases)** e executar. O Tesseract já está incluído.

### 2. Pré-requisitos (Para Rodar Localmente - Desenvolvimento)

Você **precisa** ter o Tesseract OCR Engine instalado no seu sistema (o script Python "chama" esse programa).

* **Windows:** Baixe e instale [a partir deste link](https://github.com/UB-Mannheim/tesseract/wiki).
    * **Importante:** Durante a instalação, na tela "Choose Components", certifique-se de marcar o suporte ao idioma "Portuguese" (em `Additional language data`).
* **macOS:** `brew install tesseract tesseract-lang`
* **Linux:** `sudo apt-get install tesseract-ocr tesseract-ocr-por`

### 3. Instalação (Desenvolvimento)

1.  Clone o repositório:
    ```bash
    git clone https://github.com/alessandrolsdev/AutoScanExtractor.git
    ```
2.  Navegue até a pasta do projeto:
    ```bash
    cd AutoScanExtractor
    ```
3.  (Recomendado) Crie um ambiente virtual:
    ```bash
    python -m venv venv
    ```
    E ative-o:
    * Windows: `.\venv\Scripts\activate`
    * Mac/Linux: `source venv/bin/activate`
    
4.  Instale as dependências:
    ```bash
    pip install -r requirements.txt
    ```

### 4. Executando o Bot

Com as dependências e o Tesseract instalados, basta executar o script `main.py`:

```bash
python main.py
```
### 5. Gerando o Executável (.exe)

Este projeto está configurado para ser compilado com PyInstaller usando um arquivo .spec que lida com todas as dependências complexas (incluindo o Tesseract).

Garanta que o PyInstaller está instalado:

```bash

pip install pyinstaller
```
Execute o PyInstaller apontando para o arquivo de especificação:

```bash

pyinstaller AutoScanExtractor.spec
```
O executável final e suas dependências estarão na pasta dist/.

### 📁 Estrutura do Projeto

O projeto foi refatorado para seguir padrões de arquitetura limpa, separando responsabilidades:
```bash
/AutoScanExtractor
|
+-- /assets           # Ícones da GUI e imagens do README
+-- /tests            # Testes unitários do Pytest
|   +-- /test_data    # Arquivos PDF/JPG de amostra para os testes
|   +-- test_extraction_logic.py
|
+-- boleto_data.py    # Define a classe de dados `BoletoData` (o modelo)
+-- config.py         # Configuração do Tesseract e constantes
+-- extraction_logic.py # O "cérebro": Classe `BoletoParser` (Modo 1 e Modo 2)
+-- file_processor.py   # Lógica para ler PDFs e Imagens (PyMuPDF, OpenCV)
+-- gui.py            # Todo o código da GUI (Classes App e ExtractorService)
+-- main.py           # Ponto de entrada (inicia o app)
|
+-- AutoScanExtractor.spec # Arquivo de build do PyInstaller
+-- .gitignore        # Ignora arquivos de build, cache e .xlsx
+-- README.md         # Este arquivo
+-- requirements.txt  # Lista de dependências Python
+-- LICENSE           # Licença MIT do projeto
```
📝 Licença
Este projeto está sob a licença MIT.

Feito por **Alessandro Lima da Silva** ([@alessandrolsdev](https://github.com/alessandrolsdev))
