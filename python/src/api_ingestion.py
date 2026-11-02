"""Configurable REST API ingestion adapter.

Secrets are read from environment variables. This module deliberately does not
assume a vendor-specific API or field schema.
"""
import argparse, json, os, time
from pathlib import Path
import pandas as pd
import requests

def fetch_records(base_url, token, records_path="data", next_path="next",
                 page_size=500, timeout=30, max_pages=1000):
    session=requests.Session()
    session.headers.update({"Authorization":f"Bearer {token}","Accept":"application/json"})
    url=base_url
    params={"limit":page_size}
    records=[]
    for _ in range(max_pages):
        response=session.get(url,params=params,timeout=timeout)
        response.raise_for_status()
        payload=response.json()
        if isinstance(payload,list):
            batch=payload; next_url=None
        elif isinstance(payload,dict):
            batch=payload
            for part in records_path.split("."):
                batch=batch[part]
            next_url=payload
            for part in next_path.split("."):
                next_url=next_url.get(part) if isinstance(next_url,dict) else None
        else:
            raise ValueError("API response must be a JSON object or array")
        if not isinstance(batch,list):
            raise ValueError("Configured records_path must resolve to a JSON array")
        records.extend(batch)
        if not next_url: break
        url=next_url if str(next_url).startswith("http") else base_url.rstrip("/")+"/"+str(next_url).lstrip("/")
        params=None
        time.sleep(.1)
    else:
        raise RuntimeError(f"Pagination exceeded max_pages={max_pages}; refusing partial extract")
    if not records:
        raise ValueError("API returned zero records; refusing to overwrite the last valid extract")
    return pd.json_normalize(records)

def map_fields(raw, mapping):
    missing=[source for source in mapping.values() if source not in raw.columns]
    if missing:
        raise ValueError(f"API field mapping references missing source fields: {missing}")
    return raw.rename(columns={v:k for k,v in mapping.items()})

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--mapping",required=True,help="JSON object mapping canonical field names to API response field names")
    p.add_argument("--output",default="data/raw/api_conversations.csv")
    p.add_argument("--records-path",default=os.getenv("API_RECORDS_PATH","data"))
    p.add_argument("--next-path",default=os.getenv("API_NEXT_PATH","next"))
    a=p.parse_args()
    url=os.getenv("SUPPORT_API_URL"); token=os.getenv("SUPPORT_API_TOKEN")
    if not url or not token:
        raise SystemExit("Set SUPPORT_API_URL and SUPPORT_API_TOKEN as environment variables/GitHub Actions secrets")
    mapping=json.loads(Path(a.mapping).read_text())
    raw=fetch_records(url,token,a.records_path,a.next_path)
    canonical=map_fields(raw,mapping)
    required={"chat_id","arrived_at_utc","region","language","channel","market","team","local_timezone","event_type","concurrency","first_response_minutes","handling_minutes","resolved","csat","converted","revenue","contact_reason","escalated"}
    absent=sorted(required-set(canonical.columns))
    if absent: raise ValueError(f"Mapped API extract is missing canonical fields: {absent}")
    output=Path(a.output); output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix(output.suffix+".tmp")
    canonical.to_csv(temp,index=False); temp.replace(output)
    print(json.dumps({"rows":len(canonical),"output":str(output),"source":"configured_rest_api"}))
if __name__=="__main__": main()
