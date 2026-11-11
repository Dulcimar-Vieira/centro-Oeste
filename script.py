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
SIGLAS_ESTADOS={"df":"distrito federal","go":"goias","mt":"mato grosso","ms":"mato grosso do sul"}

def matches(city,state,title,desc):
    # Centro-Oeste inclui todas as cidades dos quatro estados/DF.
    # O campo cidade não pode ser apenas o nome do estado/região.
    state_norm=norm(state)
    state_norm=SIGLAS_ESTADOS.get(state_norm,state_norm)
    city_norm=norm(city)
    return state_norm in ESTADOS and bool(city_norm) and city_norm not in ESTADOS

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

    # Mantém os registros já selecionados no dia, inclusive os que receberam
    # "A combinar" no lote anterior. Valores acima do teto continuam excluídos.
    selected={
        k:j for k,j in selected.items()
        if (
            has_real_salary(j.get("salary",""))
            or normalize_salary_text(j.get("salary","")) == "a combinar"
        )
        and not salary_exceeds_limit(j.get("salary",""), j.get("description",""))
    }

    r=requests.get(FEED_URL,headers={"User-Agent":"Mozilla/5.0 (compatible; FeedProcessor/1.0)"},timeout=60)
    r.raise_for_status()

    candidates_with_salary={}
    candidates_without_salary={}
    counts={
        "xml_lidas":0,
        "fora_da_regiao":0,
        "localidade_invalida":0,
        "sem_dados_obrigatorios":0,
        "salario_acima_de_10000":0,
        "com_salario":0,
        "sem_salario":0,
        "duplicadas":0,
    }
    state_distribution={}
    regional_city_distribution={}

    with gzip.open(io.BytesIO(r.content), "rb") as f:
        for _,elem in ET.iterparse(f,events=("end",)):
            if elem.tag!="job":
                continue

            counts["xml_lidas"]+=1
            title=elem.findtext("title","").strip()
            desc=elem.findtext("description","").strip()
            company=elem.findtext("company/name","").strip() or "Confidencial"
            url=elem.findtext("urlDeeplink","").strip() or elem.findtext("link","").strip()
            typ=elem.findtext("jobType","").strip()
            source_salary=elem.findtext("salary","").strip()
            loc=elem.find("locations/location")
            city=loc.findtext("city","").strip() if loc is not None else ""
            state=loc.findtext("state","").strip() if loc is not None else ""
            state_norm=norm(state) or "(vazio)"
            state_distribution[state_norm]=state_distribution.get(state_norm,0)+1
            if state_norm in ESTADOS or state_norm in SIGLAS_ESTADOS:
                city_norm=norm(city) or "(vazio)"
                regional_city_distribution[city_norm]=regional_city_distribution.get(city_norm,0)+1
            pub=elem.findtext("pubdate","").strip()
            dt=parse_date(pub)

            if not title or not url or not city or not state:
                counts["sem_dados_obrigatorios"]+=1
                elem.clear()
                continue

            if not matches(city,state,title,desc):
                state_norm=norm(state)
                state_norm=SIGLAS_ESTADOS.get(state_norm,state_norm)
                if state_norm in ESTADOS and norm(city) in ESTADOS:
                    counts["localidade_invalida"]+=1
                else:
                    counts["fora_da_regiao"]+=1
                elem.clear()
                continue

            salary=extract_salary(source_salary,desc)

            # Salários explicitamente acima do limite não entram nem mesmo
            # como "A combinar", pois a remuneração está informada na fonte.
            if salary_exceeds_limit(salary,desc):
                counts["salario_acima_de_10000"]+=1
                elem.clear()
                continue

            if salary:
                counts["com_salario"]+=1
                salary_value=salary
            else:
                counts["sem_salario"]+=1
                salary_value="A combinar"

            j={"id":hashlib.md5(f"{title}-{company}-{city}-{url}".encode()).hexdigest(),
               "title":title,"description":intro(title,city)+"\n\n"+clean(desc),"salary":salary_value,
               "company":company,"city":city,"state":state,"tipo":typ,"url":url,
               "data_publicacao":dt.date().isoformat() if dt else datetime.now(TIMEZONE).date().isoformat(),
               "origem":"WhatJobs"}

            job_key=key(j)
            if has_real_salary(salary_value):
                target=candidates_with_salary
                other=candidates_without_salary
            else:
                target=candidates_without_salary
                other=candidates_with_salary

            # Se a mesma URL aparecer duas vezes, a versão com salário informado
            # sempre prevalece sobre a versão sem salário.
            if job_key in other:
                if has_real_salary(salary_value):
                    other.pop(job_key,None)
                else:
                    counts["duplicadas"]+=1
                    elem.clear()
                    continue
            if job_key in target:
                counts["duplicadas"]+=1
            else:
                target[job_key]=j

            elem.clear()

    # Atualiza os registros já selecionados. Se o feed passou a informar salário,
    # promove a vaga; se deixou de informar, não apaga um salário já conhecido.
    all_candidates={**candidates_without_salary,**candidates_with_salary}
    for k in list(selected):
        if k in all_candidates:
            incoming=all_candidates[k]
            if (
                has_real_salary(incoming.get("salary",""))
                or not has_real_salary(selected[k].get("salary",""))
            ):
                selected[k]=incoming

    # Primeiro entram todas as vagas com salário conhecido.
    salary_jobs=sorted(
        candidates_with_salary.items(),
        key=lambda item:item[1].get("data_publicacao",""),
        reverse=True
    )
    for k,j in salary_jobs:
        if k in selected:
            continue
        if len(selected)>=MAX_JOBS_PER_DAY:
            break
        selected[k]=j

    # Só depois completamos o limite com vagas sem salário, identificadas
    # explicitamente como "A combinar".
    no_salary_jobs=sorted(
        candidates_without_salary.items(),
        key=lambda item:item[1].get("data_publicacao",""),
        reverse=True
    )
    for k,j in no_salary_jobs:
        if k in selected:
            continue
        if len(selected)>=MAX_JOBS_PER_DAY:
            break
        selected[k]=j

    if not selected:
        print("Resumo de diagnóstico antes da interrupção:")
        for name,value in counts.items():
            print(f"  {name}: {value}")
        print(f"  candidatos_com_salario: {len(candidates_with_salary)}")
        print(f"  candidatos_a_combinar: {len(candidates_without_salary)}")
        raise SystemExit(
            "ERRO: nenhuma vaga regional válida foi encontrada; "
            "os arquivos existentes foram preservados."
        )

    # Ordena o arquivo final com salários conhecidos primeiro e, dentro de
    # cada grupo, prioriza as vagas mais recentes.
    ordered_jobs=sorted(
        selected.values(),
        key=lambda j:j.get("data_publicacao",""),
        reverse=True
    )
    ordered_jobs.sort(key=lambda j:not has_real_salary(j.get("salary","")))

    # Proteção: um feed parcial não pode substituir o último lote íntegro.
    previous_count=0
    if os.path.isfile("merged.json"):
        try:
            with open("merged.json",encoding="utf-8") as previous_file:
                previous_data=json.load(previous_file)
            previous_count=int(previous_data.get("total_vagas") or len(previous_data.get("vagas",[])))
        except (OSError,ValueError,TypeError):
            raise SystemExit(
                "ERRO: não foi possível validar o merged.json anterior; "
                "os arquivos existentes foram preservados."
            )

    minimum_safe_count=int(previous_count*0.75) if previous_count else 1
    if previous_count and len(ordered_jobs)<minimum_safe_count:
        print("Resumo do processamento:")
        for name,value in counts.items():
            print(f"  {name}: {value}")
        print(f"  selecionadas_com_salario: {sum(1 for j in ordered_jobs if has_real_salary(j.get('salary','')))}")
        print(f"  selecionadas_a_combinar: {sum(1 for j in ordered_jobs if not has_real_salary(j.get('salary','')))}")
        print(f"  total_selecionado: {len(ordered_jobs)}")
        print(f"  lote_anterior_valido: {previous_count}")
        print(f"  minimo_para_substituicao: {minimum_safe_count}")
        print("  estados_encontrados:")
        for name,value in sorted(state_distribution.items(),key=lambda item:item[1],reverse=True)[:20]:
            print(f"    {name}: {value}")
        print("  cidades_nos_estados_do_centro_oeste:")
        for name,value in sorted(regional_city_distribution.items(),key=lambda item:item[1],reverse=True)[:30]:
            print(f"    {name}: {value}")
        raise SystemExit(
            "ERRO: feed retornou lote abaixo do mínimo de segurança; "
            "merged.json, part_1.json e daily_jobs_state.json foram preservados."
        )

    os.makedirs(OUTPUT_FOLDER,exist_ok=True)
    for fn in os.listdir(OUTPUT_FOLDER):
        if fn.endswith(".json"):
            os.remove(os.path.join(OUTPUT_FOLDER,fn))

    output_path=os.path.join(OUTPUT_FOLDER,"part_1.json")
    temp_path=output_path+".tmp"
    with open(temp_path,"w",encoding="utf-8") as f:
        json.dump(ordered_jobs[:MAX_JOBS_PER_DAY],f,ensure_ascii=False,indent=2)
    os.replace(temp_path,output_path)

    save_state(today,selected)

    selected_with_salary=sum(1 for j in ordered_jobs if has_real_salary(j.get("salary","")))
    selected_without_salary=len(ordered_jobs)-selected_with_salary

    print("Resumo do processamento:")
    for name,value in counts.items():
        print(f"  {name}: {value}")
    print("  estados_encontrados:")
    for name,value in sorted(state_distribution.items(),key=lambda item:item[1],reverse=True)[:20]:
        print(f"    {name}: {value}")
    print(f"  selecionadas_com_salario: {selected_with_salary}")
    print(f"  selecionadas_a_combinar: {selected_without_salary}")
    print(f"  total_selecionado: {len(ordered_jobs[:MAX_JOBS_PER_DAY])}")


if __name__=="__main__": main()
