import pytesseract
import pandas as pd
from PIL import Image
import re  # Importamos a biblioteca de Expressões Regulares (Regex)

# --- CONFIGURAÇÃO ---
# Apontamos para o executável do Tesseract
# Certifique-se de que este caminho está correto para o seu computador
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Nome do arquivo de imagem (deve estar na mesma pasta)
nome_imagem = 'horarios.png'
# Nome da planilha que será criada
nome_planilha_saida = 'horarios_extraidos.xlsx'

# --- 1. LEITURA DA IMAGEM E EXTRAÇÃO DO TEXTO (OCR) ---
try:
    print(f"Lendo a imagem '{nome_imagem}'...")
    imagem = Image.open(nome_imagem)
    # lang='por' é essencial para reconhecer o idioma português
    texto_extraido = pytesseract.image_to_string(imagem, lang='por')
    print("Texto extraído com sucesso.")

except FileNotFoundError:
    print(f"ERRO: A imagem '{nome_imagem}' não foi encontrada.")
    print("Verifique se ela está na mesma pasta que o script 'extrator.py'.")
    exit() # Encerra o script
except pytesseract.TesseractNotFoundError:
    print("\nERRO: O Tesseract OCR não foi encontrado.")
    print("Verifique se o caminho em 'pytesseract.tesseract_cmd' está correto.")
    exit() # Encerra o script
except Exception as e:
    print(f"ERRO inesperado ao ler a imagem ou extrair o texto: {e}")
    exit() # Encerra o script


# --- PASSO DE DEBUG: MOSTRAR O TEXTO EXTRAÍDO ---
print("\n--- INÍCIO DO TEXTO EXTRAÍDO (DEBUG) ---")
print(texto_extraido)
print("--- FIM DO TEXTO EXTRAÍDO (DEBUG) ---\n")
# -------------------------------------------------


# --- 2. PROCESSAMENTO E ESTRUTURAÇÃO DOS DADOS ---
print("Processando o texto e procurando padrões...")

dados_planilha = [] # Lista para guardar nossos dados organizados
dia_atual = None
dias_da_semana = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]

# Divide o texto extraído em uma lista de linhas
linhas = texto_extraido.splitlines()

for linha in linhas:
    linha_limpa = linha.strip() # Remove espaços em branco do início e fim
    
    # Ignora linhas que estão vazias
    if not linha_limpa:
        continue

    # Verifica se a linha começa com um dia da semana
    # Usamos .startswith() para verificar o início da linha
    dia_encontrado = False
    for dia in dias_da_semana:
        if linha_limpa.startswith(dia):
            dia_atual = dia
            dia_encontrado = True
            
            # Remove o dia da semana da linha para processar o resto
            # Ex: "Segunda-feira Café da Manhã 08:00" vira "Café da Manhã 08:00"
            linha_limpa = linha_limpa.replace(dia, "").strip() 
            
            # Se a linha SÓ tinha o dia da semana, pulamos para a próxima
            if not linha_limpa:
                break 

    # Se a linha não era um dia da semana, OU se era um dia E tinha mais texto:
    if (not dia_encontrado or (dia_encontrado and linha_limpa)) and dia_atual:
        # Agora, procuramos pelo horário no formato HH:MM (ex: 08:00)
        # re.search() encontra um padrão dentro da string
        # r'(\d{2}:\d{2})' significa: 
        #   \d{2} -> exatamente 2 dígitos numéricos
        #   :     -> o caractere de dois pontos
        #   \d{2} -> exatamente 2 dígitos numéricos
        match_horario = re.search(r'(\d{2}:\d{2})', linha_limpa)
        
        if match_horario:
            # Se achamos um horário:
            horario = match_horario.group(1) # Pega o texto encontrado (ex: "08:00")
            
            # A refeição é todo o texto que veio ANTES do horário
            posicao_horario = match_horario.start() # Onde o horário começa
            refeicao = linha_limpa[:posicao_horario].strip() # Pega tudo antes
            
            # Adiciona os dados encontrados à nossa lista
            dados_planilha.append({
                'Dia': dia_atual,
                'Refeição': refeicao,
                'Horário': horario
            })
            print(f"  > Dado encontrado: Dia={dia_atual}, Refeição={refeicao}, Horário={horario}")

# --- 3. CRIAÇÃO DA PLANILHA EXCEL ---
if dados_planilha:
    print("\nQuase pronto! Criando a planilha Excel...")
    
    # Converte nossa lista de dados em um DataFrame do Pandas (basicamente uma tabela)
    df = pd.DataFrame(dados_planilha)
    
    # Salva o DataFrame em um arquivo Excel
    # index=False remove a coluna de índice (0, 1, 2, 3...) da planilha
    df.to_excel(nome_planilha_saida, index=False)
    
    print(f"\nSUCESSO! A planilha '{nome_planilha_saida}' foi criada na mesma pasta.")
else:
    print("\nAVISO: Processamento concluído, mas nenhum dado foi estruturado.")
    print("Verifique se o texto extraído no Passo 1 estava correto.")