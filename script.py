#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import gzip, hashlib, io, json, os, random, re
from datetime import datetime
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import requests

FEED_URL = "https://feeds.whatjobs.com/sinerj/sinerj_pt_BR.xml.gz"
OUTPUT_FOLDER = "json_parts"
STATE_FILE = "daily_jobs_state.json"
MAX_JOBS_PER_DAY = 100
TIMEZONE = ZoneInfo("America/Sao_Paulo")

ESTADOS={"distrito federal","goiás","mato grosso","mato grosso do sul"}
CIDADES={"brasilia","goiania","cuiaba","campo grande"}
def matches(city,state,title,desc):
    return norm(state) in ESTADOS and norm(city) in CIDADES

def norm(s): return (s or "").strip().lower()
def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()

def parse_date(s):
    if not s: return None
    s=s.strip()
    for fmt in ("%d.%m.%Y","%d/%m/%Y","%Y-%m-%d","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M:%SZ"):
        try: return datetime.strptime(s,fmt)
        except ValueError: pass
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError: return None

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
            loc=elem.find("locations/location")
            city=loc.findtext("city","").strip() if loc is not None else ""
            state=loc.findtext("state","").strip() if loc is not None else ""
            pub=elem.findtext("pubdate","").strip()
            dt=parse_date(pub)
            if not title or not url or not city or not state or not dt or dt.date().isoformat()!=today or not matches(city,state,title,desc):
                elem.clear(); continue
            j={"id":hashlib.md5(f"{title}-{company}-{city}-{url}".encode()).hexdigest(),
               "title":title,"description":intro(title,city)+"\n\n"+clean(desc),
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

    os.makedirs(OUTPUT_FOLDER,exist_ok=True)
    for fn in os.listdir(OUTPUT_FOLDER):
        if fn.endswith(".json"): os.remove(os.path.join(OUTPUT_FOLDER,fn))
    with open(os.path.join(OUTPUT_FOLDER,"part_1.json"),"w",encoding="utf-8") as f:
        json.dump(list(selected.values())[:MAX_JOBS_PER_DAY],f,ensure_ascii=False,indent=2)
    save_state(today,selected)
    print(f"Data: {today} | Encontradas hoje: {len(candidates)} | Selecionadas: {min(len(selected),MAX_JOBS_PER_DAY)}")

if __name__=="__main__": main()
