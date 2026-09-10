#!/usr/bin/env python3
# coding: utf-8

import requests
import gzip
import xml.etree.ElementTree as ET
import io
import json
import os
import hashlib
import re
from datetime import datetime

# ==========================================
# CONFIG
# ==========================================

FEED_URL = "https://feeds.whatjobs.com/sinerj/sinerj_pt_BR.xml.gz"

# Cidades RJ
CIDADES_RJ = [
    "rio de janeiro",
    "niteroi",
    "duque de caxias",
    "nova iguacu",
    "sao goncalo"
]

# Keywords
KEYWORDS = []

# Pasta de saída
OUTPUT_FOLDER = "json_parts"

# ==========================================
# LIMITES
# ==========================================

# vagas por arquivo
MAX_JOBS_PER_FILE = 1000

# quantidade máxima de arquivos
MAX_FILES = 5

# ==========================================
# CRIAR PASTA
# ==========================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ==========================================
# FUNÇÕES
# ==========================================

def normalize(text):
    if not text:
        return ""
    return text.strip().lower()


def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_company(company):
    if not company or not company.strip():
        return "Confidencial"

    return company.strip()


def normalize_salary(text):
    if not text:
        return "A Combinar"

    text = re.sub(r"\s+", " ", text).strip()

    return text


def generate_hash(title, company, city, url):
    base = f"{title}-{company}-{city}-{url}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def is_valid_keyword(text):
    return True


# ==========================================
# DOWNLOAD FEED
# ==========================================

print("📥 Baixando feed...")

try:

    response = requests.get(
        FEED_URL,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=60
    )

except requests.RequestException as e:

    print(f"Erro ao baixar feed: {e}")
    exit()

if response.status_code != 200:

    print(f"Erro HTTP: {response.status_code}")
    exit()

# ==========================================
# PROCESSAMENTO
# ==========================================

jobs = []
file_count = 1
seen_urls = set()

stop_processing = False

with gzip.open(
    io.BytesIO(response.content),
    "rt",
    encoding="utf-8"
) as f:

    for event, elem in ET.iterparse(f, events=("end",)):

        if stop_processing:
            break

        if elem.tag != "job":
            continue

        title = elem.findtext("title", "").strip()
        description = elem.findtext("description", "").strip()

        company = normalize_company(
            elem.findtext("company/name", "")
        )

        job_type = elem.findtext("jobType", "").strip()
        url = elem.findtext("urlDeeplink", "").strip()
        salary = elem.findtext("salary", "").strip()

        # ==========================================
        # LOCALIZAÇÃO
        # ==========================================

        location_elem = elem.find("locations/location")

        city = ""
        state = ""

        if location_elem is not None:

            city = location_elem.findtext(
                "city",
                ""
            ).strip()

            state = location_elem.findtext(
                "state",
                ""
            ).strip()

        # ==========================================
        # VALIDAÇÃO
        # ==========================================

        if not city or not state or not title or not url:
            elem.clear()
            continue

        city_lower = normalize(city)

        # ==========================================
        # FILTRO RJ
        # ==========================================

        if city_lower not in CIDADES_RJ:
            elem.clear()
            continue

        # ==========================================
        # FILTRO KEYWORDS
        # ==========================================

        content_text = f"{title} {description}"

        if not is_valid_keyword(content_text):
            elem.clear()
            continue

        # ==========================================
        # REMOVER DUPLICADOS
        # ==========================================

        if url in seen_urls:
            elem.clear()
            continue

        seen_urls.add(url)

        # ==========================================
        # LIMPEZA
        # ==========================================

        description = clean_html(description)
        salary = normalize_salary(salary)

        # ==========================================
        # HASH
        # ==========================================

        hash_unico = generate_hash(
            title,
            company,
            city,
            url
        )

        # ==========================================
        # JSON
        # ==========================================

        jobs.append({

            "title": title,
            "description": description,
            "company": company,
            "city": city,
            "state": state,

            "salary": salary if salary else "A Combinar",

            "tipo": (
                job_type
                if job_type
                else "Nao informado"
            ),

            "origem": "WhatJobs",

            "url": url,

            "data_publicacao": (
                datetime.utcnow().isoformat()
            ),

            "hash_unico": hash_unico

        })

        elem.clear()

        # ==========================================
        # LIMITE POR ARQUIVO
        # ==========================================

        if len(jobs) >= MAX_JOBS_PER_FILE:

            json_path = os.path.join(
                OUTPUT_FOLDER,
                f"part_{file_count}.json"
            )

            with open(
                json_path,
                "w",
                encoding="utf-8"
            ) as json_file:

                json.dump(
                    jobs,
                    json_file,
                    ensure_ascii=False,
                    indent=2
                )

            print(f"✅ {json_path} gerado")

            jobs = []
            file_count += 1

            # ==========================================
            # LIMITE TOTAL DE ARQUIVOS
            # ==========================================

            if file_count > MAX_FILES:

                print(
                    "⛔ Limite máximo de arquivos atingido"
                )

                stop_processing = True
                break

# ==========================================
# SALVAR RESTANTE
# ==========================================

if jobs and file_count <= MAX_FILES:

    json_path = os.path.join(
        OUTPUT_FOLDER,
        f"part_{file_count}.json"
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as json_file:

        json.dump(
            jobs,
            json_file,
            ensure_ascii=False,
            indent=2
        )

    print(f"✅ {json_path} gerado")

# ==========================================
# FINAL
# ==========================================

print("📦 Processamento finalizado")
print(f"📁 Arquivos gerados: {file_count}")
