#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import gzip, hashlib, io, json, os, random, re
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import requests

FEED_URL = "https://feeds.whatjobs.com/sinerj/sinerj_pt_BR.xml.gz"
OUTPUT_FOLDER = "json_parts"
STATE_FILE = "daily_jobs_state.json"
MAX_JOBS_PER_DAY = 1000
TIMEZONE = ZoneInfo("America/Sao_Paulo")

# Validação conservadora de salário: não confundir números de benefícios com remuneração.
MONEY_NUMBER = (
    r"(?:"
    r"\d{1,3}(?:\.\d{3})+(?:,\d{2})?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{2})?"
    r"|\d+(?:,\d{2}|\.\d{2})?"
    r")"
    r"(?:\s*(?:mil|k)\b)?"
)
SALARY_AMOUNT_RE = re.compile(
    rf"\b(?:faixa salarial|piso salarial|sal[aá]rios?|remunera[cç][aã]o|proventos)\b"
    rf"(?:\s+(?:fixo|base|mensal(?:\s+de)?|bruto|inicial|m[ií]nimo garantido|"
    rf"oferecido|oferecida|oferecidos|oferecidas|de at[eé]|a partir de|entre)){{0,3}}"
    rf"\s*(?:[:：=–—-]\s*)?"
    rf"(?:(?:a partir de|de|entre)\s+)?"
    rf"(?P<amount>(?:R\$\s*)?{MONEY_NUMBER})(?![\d.,])",
    re.IGNORECASE,
)

def normalize_salary_text(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()

def has_real_salary(salary):
    value = normalize_salary_text(salary)
    if not value:
        return False
    placeholders = (
        "a combinar", "nao informado", "nao informada",
        "nao divulgado", "nao divulgada", "confidencial",
        "negociavel", "sob consulta", "salario nao informado",
        "salario a combinar",
    )
    if any(marker in value for marker in placeholders):
        return False
    if not re.search(r"\d", value):
        return False
    if not re.search(r"(?:R\$|[$€£])", value) and re.fullmatch(r"\d+", value):
        return False
    return True

MAX_SALARY_BRL = 10000.0

# Reconhece valores monetários em formatos brasileiros e internacionais.
SALARY_VALUE_RE = re.compile(
    rf"(?<![\w])(?:R\$\s*|[$€£]\s*)?{MONEY_NUMBER}(?![\d.,])",
    re.IGNORECASE,
)

def parse_salary_amount(raw_amount):
    """Converte um valor salarial para número e reconhece sufixos mil/k."""
    raw_value = str(raw_amount or "").strip()
    multiplier = 1000.0 if re.search(r"\s*(?:mil|k)\b", raw_value, re.IGNORECASE) else 1.0
    value = re.sub(r"\s*(?:mil|k)\b", "", raw_value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:R\$|[$€£])\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[^\d.,]", "", value)
    if not value:
        return None

    if "." in value and "," in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        left, _, right = value.rpartition(",")
        if len(right) == 3 and left:
            value = value.replace(",", "")
        else:
            value = left.replace(",", "") + "." + right
    elif "." in value:
        parts = value.split(".")
        if len(parts) > 1 and len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
        else:
            value = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(value) * multiplier
    except ValueError:
        return None


def salary_exceeds_limit(salary, description=""):
    """Retorna True quando algum limite salarial informado passa de R$ 10 mil."""
    for match in SALARY_VALUE_RE.finditer(salary or ""):
        amount = parse_salary_amount(match.group(0))
        if amount is not None and amount > MAX_SALARY_BRL:
            return True

    text = re.sub(r"<[^>]+>", " ", description or "")
    text = re.sub(r"\s+", " ", text).strip()
    range_tail_re = re.compile(
        rf"\s*(?:-|–|—|\ba\b|\bat[eé]\b)\s*(?:R\$\s*)?({MONEY_NUMBER})(?![\d.,])",
        re.IGNORECASE,
    )
    for match in SALARY_AMOUNT_RE.finditer(text):
        amount = parse_salary_amount(match.group("amount"))
        if amount is not None and amount > MAX_SALARY_BRL:
            return True
        range_match = range_tail_re.match(text[match.end():match.end() + 100])
        if range_match:
            upper_amount = parse_salary_amount(range_match.group(1))
            if upper_amount is not None and upper_amount > MAX_SALARY_BRL:
                return True
    return False


def extract_salary(structured_salary, description):
    structured_salary = re.sub(r"\s+", " ", structured_salary or "").strip()
    if has_real_salary(structured_salary):
        return structured_salary
    text = re.sub(r"<[^>]+>", " ", description or "")
    text = re.sub(r"\s+", " ", text).strip()
    for match in SALARY_AMOUNT_RE.finditer(text):
        amount = re.sub(r"\s+", " ", match.group("amount")).strip()
        raw_number = re.sub(r"^R\$\s*", "", amount, flags=re.IGNORECASE).strip()
        if not amount.upper().startswith("R$") and re.fullmatch(r"\d{1,2}", raw_number):
            continue
        return amount
    return ""


ESTADOS={"distrito federal","goias","mato grosso","mato grosso do sul"}
CIDADES={"brasilia","goiania","cuiaba","campo grande"}
def matches(city,state,title,desc):
    return norm(state) in ESTADOS and norm(city) in CIDADES

def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return "".join(char for char in s if not unicodedata.combining(char))
def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()

def parse_date(s):
    if not s: return None
    s=s.strip()
    for fmt in ("%d.%m.%Y","%d/%m/%Y","%Y-%m-%d","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M:%SZ"):
        try: return datetime.strptime(s,fmt)
        except ValueError: pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    # O feed pode trazer datas em formato RSS/RFC 822, por exemplo:
    # Wed, 15 Oct 2026 10:30:00 GMT.
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError, OverflowError):
        return None

def key(j):
    return j["url"] or hashlib.md5(f'{j["title"]}|{j["company"]}|{j["city"]}'.encode()).hexdigest()

def intro(title, city):
    return random.choice([
        f"Confira a vaga para {title} em {city}. Veja os detalhes e como se candidatar.",
        f"Nova oportunidade para {title} em {city}. Saiba mais sobre essa vaga.",
        f"Empresa está contratando {title} em {city}. Confira requisitos e envie seu currículo."
    ])

def load_state(today):
    try:
        with open(STATE_FILE,encoding="utf-8") as f: s=json.load(f)
        return s.get("jobs",{}) if s.get("date")==today else {}
    except (OSError,json.JSONDecodeError): return {}

def save_state(today,jobs):
    with open(STATE_FILE,"w",encoding="utf-8") as f:
        json.dump({"date":today,"jobs":jobs},f,ensure_ascii=False,indent=2)

def main():
    today=datetime.now(TIMEZONE).date().isoformat()
    selected=load_state(today)
    # Não reutilizar vagas antigas sem salário validado.
    selected={k:j for k,j in selected.items() if has_real_salary(j.get("salary","")) and not salary_exceeds_limit(j.get("salary",""), j.get("description",""))}
    r=requests.get(FEED_URL,headers={"User-Agent":"Mozilla/5.0 (compatible; FeedProcessor/1.0)"},timeout=60)
    r.raise_for_status()
    candidates={}
    with gzip.open(io.BytesIO(r.content),"rt",encoding="utf-8") as f:
        for _,elem in ET.iterparse(f,events=("end",)):
            if elem.tag!="job": continue
            title=elem.findtext("title","").strip()
            desc=elem.findtext("description","").strip()
            company=elem.findtext("company/name","").strip() or "Confidencial"
            url=elem.findtext("urlDeeplink","").strip() or elem.findtext("link","").strip()
            typ=elem.findtext("jobType","").strip()
            source_salary=elem.findtext("salary","").strip()
            loc=elem.find("locations/location")
            city=loc.findtext("city","").strip() if loc is not None else ""
            state=loc.findtext("state","").strip() if loc is not None else ""
            pub=elem.findtext("pubdate","").strip()
            dt=parse_date(pub)
            if not title or not url or not city or not state or not dt or not matches(city,state,title,desc):
                elem.clear(); continue
            salary=extract_salary(source_salary,desc)
            if not salary or salary_exceeds_limit(salary, desc):
                elem.clear(); continue
            j={"id":hashlib.md5(f"{title}-{company}-{city}-{url}".encode()).hexdigest(),
               "title":title,"description":intro(title,city)+"\n\n"+clean(desc),"salary":salary,
               "company":company,"city":city,"state":state,"tipo":typ,"url":url,
               "data_publicacao":dt.date().isoformat(),"origem":"WhatJobs"}
            candidates[key(j)]=j
            elem.clear()

    for k in list(selected):
        if k in candidates: selected[k]=candidates[k]

    novos=[j for k,j in candidates.items() if k not in selected]
    novos.sort(key=lambda j:j["data_publicacao"],reverse=True)
    for j in novos:
        if len(selected)>=MAX_JOBS_PER_DAY: break
        selected[key(j)]=j

    if not selected:
        raise SystemExit("ERRO: nenhuma vaga com remuneração válida; os arquivos existentes foram preservados.")
    os.makedirs(OUTPUT_FOLDER,exist_ok=True)
    for fn in os.listdir(OUTPUT_FOLDER):
        if fn.endswith(".json"): os.remove(os.path.join(OUTPUT_FOLDER,fn))
    with open(os.path.join(OUTPUT_FOLDER,"part_1.json"),"w",encoding="utf-8") as f:
        json.dump(list(selected.values())[:MAX_JOBS_PER_DAY],f,ensure_ascii=False,indent=2)
    save_state(today,selected)
    print(f"Data: {today} | Encontradas hoje: {len(candidates)} | Selecionadas: {min(len(selected),MAX_JOBS_PER_DAY)}")

if __name__=="__main__": main()
