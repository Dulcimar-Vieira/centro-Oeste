import os
import json
from datetime import datetime

pasta = 'json_parts'
arquivo_saida = 'merged.json'

if not os.path.exists(pasta):
    print(f"❌ Pasta '{pasta}' não encontrada.")
    exit(1)

arquivos = sorted([
    f for f in os.listdir(pasta)
    if f.startswith('part_') and f.endswith('.json')
], key=lambda x: int(x.split('_')[1].split('.')[0]))

print(f"🔍 {len(arquivos)} arquivos encontrados em '{pasta}'.")

dados_totais = []
erros = 0

for arquivo in arquivos:
    caminho = os.path.join(pasta, arquivo)
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            dados = json.load(f)
            if isinstance(dados, list):
                dados_totais.extend(dados)
                print(f"✅ {arquivo}: {len(dados)} registros adicionados.")
            else:
                print(f"⚠️ {arquivo} não contém uma lista.")
    except Exception as e:
        erros += 1
        print(f"❌ Erro ao processar {arquivo}: {e}")

if dados_totais:
    resultado = {
        "gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_vagas": len(dados_totais),
        "vagas": dados_totais
    }
    with open(arquivo_saida, 'w', encoding='utf-8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    tamanho_mb = os.path.getsize(arquivo_saida) / (1024 * 1024)
    print(f"✅ '{arquivo_saida}' gerado com {len(dados_totais)} vagas.")
    print(f"📄 Tamanho do arquivo final: {tamanho_mb:.2f} MB")
else:
    print("⚠️ Nenhuma vaga válida encontrada. Arquivo não gerado.")

if erros > 0:
    print(f"⚠️ {erros} arquivo(s) apresentaram erro durante a leitura.")
