from __future__ import annotations
import base64, os, re, statistics, time
from typing import Optional, Dict, Any, List
import requests
import streamlit as st

TOKEN_URL='https://api.ebay.com/identity/v1/oauth2/token'
SEARCH_URL='https://api.ebay.com/buy/browse/v1/item_summary/search'
SCOPE='https://api.ebay.com/oauth/api_scope'
CATEGORY='9355'
MARKETPLACE='EBAY_US'
TOKEN_CACHE={'token':None,'expires':0}
MODELS={
'iphone_14':'Apple iPhone 14','iphone_14_pro_max':'Apple iPhone 14 Pro Max',
'iphone_15_pro':'Apple iPhone 15 Pro','iphone_15_pro_max':'Apple iPhone 15 Pro Max',
's24_ultra':'Samsung Galaxy S24 Ultra','s25_ultra':'Samsung Galaxy S25 Ultra',
's25_edge':'Samsung Galaxy S25 Edge'}
EXCLUDE=('case','cover','screen protector','for parts','parts only','dummy','housing','back glass','battery only','camera lens','box only','bad imei','blacklisted','icloud locked')

def _secret(k):
    try:
        v=st.secrets.get(k)
        if v: return str(v)
    except Exception: pass
    return os.getenv(k)

def ebay_configured(): return bool(_secret('EBAY_CLIENT_ID') and _secret('EBAY_CLIENT_SECRET'))

def get_token():
    now=time.time()
    if TOKEN_CACHE['token'] and now<TOKEN_CACHE['expires']-60: return TOKEN_CACHE['token']
    cid,sec=_secret('EBAY_CLIENT_ID'),_secret('EBAY_CLIENT_SECRET')
    if not cid or not sec: raise RuntimeError('Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in Streamlit Secrets.')
    basic=base64.b64encode(f'{cid}:{sec}'.encode()).decode()
    r=requests.post(TOKEN_URL,headers={'Authorization':f'Basic {basic}','Content-Type':'application/x-www-form-urlencoded'},data={'grant_type':'client_credentials','scope':SCOPE},timeout=20)
    r.raise_for_status(); d=r.json(); TOKEN_CACHE.update(token=d['access_token'],expires=now+int(d.get('expires_in',7200)))
    return TOKEN_CACHE['token']

def normalize_model(model):
    key=str(model).lower().strip().replace('-','_').replace(' ','_')
    return MODELS.get(key,str(model).strip())

def _storage(storage):
    if storage is None: return ''
    s=int(storage); return '1TB' if s==1024 else f'{s}GB'

def _match(title,model,storage):
    t=title.lower()
    if any(x in t for x in EXCLUDE): return False
    tokens=[x.lower() for x in re.findall(r'[A-Za-z0-9]+',model) if x.lower() not in ('apple','samsung','galaxy')]
    if not all(x in t for x in tokens): return False
    if storage:
        s=int(storage); pats=[rf'\b{s}\s*gb\b']+([r'\b1\s*tb\b'] if s==1024 else [])
        if not any(re.search(p,t,re.I) for p in pats): return False
    return True

def _iqr(rows):
    if len(rows)<5: return rows
    ps=sorted(x['price'] for x in rows); q=statistics.quantiles(ps,n=4,method='inclusive'); i=q[2]-q[0]
    if i<=0: return rows
    lo=max(0,q[0]-1.5*i); hi=q[2]+1.5*i
    return [x for x in rows if lo<=x['price']<=hi]

def fetch_ebay_market_price(model:str,storage_gb:Optional[int]=None,limit:int=100)->Dict[str,Any]:
    name=normalize_model(model); query=' '.join(x for x in (name,_storage(storage_gb),'unlocked') if x)
    try:
        r=requests.get(SEARCH_URL,headers={'Authorization':f'Bearer {get_token()}','X-EBAY-C-MARKETPLACE-ID':MARKETPLACE},params={'q':query,'category_ids':CATEGORY,'filter':'conditions:{USED},priceCurrency:USD,deliveryCountry:US','limit':min(max(limit,1),200),'auto_correct':'KEYWORD'},timeout=25)
        r.raise_for_status(); items=r.json().get('itemSummaries',[]) or []; rows=[]
        for it in items:
            title=str(it.get('title',''))
            if not _match(title,name,storage_gb): continue
            try: price=float((it.get('price') or {}).get('value'))
            except (TypeError,ValueError): continue
            if price<=0: continue
            rows.append({'title':title,'price':price,'condition':it.get('condition'),'url':it.get('itemWebUrl')})
        raw=len(rows); rows=_iqr(rows)
        if not rows: return {'ok':False,'model':name,'storage_gb':storage_gb,'query':query,'error':'No suitable matching listings found.','listing_count':0,'raw_listing_count':raw}
        ps=[x['price'] for x in rows]
        return {'ok':True,'model':name,'storage_gb':storage_gb,'query':query,'market_value':round(statistics.median(ps),2),'median_price':round(statistics.median(ps),2),'mean_price':round(statistics.mean(ps),2),'low_price':round(min(ps),2),'high_price':round(max(ps),2),'listing_count':len(rows),'raw_listing_count':raw,'source':'eBay Browse API','price_type':'Current active asking prices','listings':rows[:20]}
    except Exception as e:
        return {'ok':False,'model':name,'storage_gb':storage_gb,'query':query,'error':str(e),'listing_count':0,'raw_listing_count':0}

fetch_ebay_market_price_cached=st.cache_data(ttl=3600,show_spinner=False)(fetch_ebay_market_price)

def get_live_or_fallback_market_value(model,storage_gb=None,fallback_value=None):
    if ebay_configured():
        x=fetch_ebay_market_price_cached(model,storage_gb)
        if x.get('ok'):
            x['used_fallback']=False; return x
    return {'ok':fallback_value is not None,'model':normalize_model(model),'storage_gb':storage_gb,'market_value':fallback_value,'median_price':fallback_value,'source':'Stored market baseline','price_type':'Fallback reference','used_fallback':True,'listing_count':0}
