import re
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

VERSION = '0.1.0-beta.2'
DEFAULTS = {'sources': ['https://www.pricerunner.dk/cl/38/RAM'], 'max_pages': 2,
            'max_products': 24, 'delay_seconds': 8, 'interval_hours': 0,
            'discount_percent': 35}
PRESETS = {'RAM': 'https://www.pricerunner.dk/cl/38/RAM',
           'Grafikkort': 'https://www.pricerunner.dk/cl/37/Grafikkort',
           'Harddiske og SSD': 'https://www.pricerunner.dk/cl/36/Harddiske'}

def source_url(value):
    u = urlsplit(value.strip())
    if u.scheme != 'https' or u.netloc != 'www.pricerunner.dk' or not re.match(r'^/(cl/\d+/|pl/\d+-\d+/)', u.path):
        raise ValueError('Brug en https://www.pricerunner.dk/cl/… eller /pl/… adresse.')
    return urlunsplit((u.scheme, u.netloc, u.path, u.query, ''))

def product_id(url):
    m = re.search(r'/pl/\d+-(\d+)/', source_url(url))
    if not m: raise ValueError('Ikke et produktlink')
    return m[1]

def money(value):
    s = value.replace('\xa0',' ').strip()
    if not re.fullmatch(r'\d+(?:\.\d{3})*(?:,\d{1,2})?', s):
        raise ValueError('Ukendt prisformat: ' + s)
    return int(Decimal(s.replace('.','').replace(',','.')) * 100)

def parse_offers(rows):
    offers = {}
    for row in rows:
        m = re.fullmatch(r'Åbn tilbud fra (.+)\. Pris: ([\d.,\s\xa0]+)\s+kr\.?\.?', row['label'])
        if not m: continue
        try: price = money(m[2])
        except ValueError: continue
        if price <= 0: continue
        merchant = m[1].strip()
        text = row.get('text','')
        key = (merchant.casefold(), price)
        offer = {'merchant':merchant,'price':price,'text':text,
                 'unavailable':bool(re.search(r'ikke på lager|udsolgt|kan ikke købes',text,re.I)),
                 'order_only':bool(re.search(r'bestillingsvare|fjernlager',text,re.I))}
        if key not in offers or len(text)>len(offers[key]['text']): offers[key]=offer
    return sorted(offers.values(),key=lambda o:o['price'])

def candidate(offers, previous, threshold):
    # One price per merchant; a promoted duplicate is never a competitor.
    shops = {}
    for o in offers:
        if not o['unavailable']:
            shops[o['merchant'].casefold()] = min(o['price'], shops.get(o['merchant'].casefold(),o['price']))
    prices = sorted(shops.values())
    if not prices: return None
    low = prices[0]
    reasons=[]
    if len(prices)>=3 and low <= prices[1]*(1-threshold/100):
        reasons.append(f'{round(100*(1-low/prices[1]))}% under næstbilligste butik (ekskl. fragt)')
    if previous and low <= previous*(1-threshold/100):
        reasons.append(f'{round(100*(1-low/previous))}% under seneste måling')
    return '; '.join(reasons) or None

def validate_config(data):
    c = dict(DEFAULTS)
    c['sources'] = list(dict.fromkeys(source_url(s) for s in data.get('sources',[]) if s.strip()))
    if not 1 <= len(c['sources']) <= 12: raise ValueError('Vælg 1–12 kilder.')
    for key,lo,hi in [('max_pages',1,100),('max_products',1,5000),('delay_seconds',5,120),('interval_hours',0,168),('discount_percent',10,90)]:
        v=data.get(key,c[key])
        if isinstance(v,bool) or not isinstance(v,int) or not lo<=v<=hi: raise ValueError(f'Ugyldig værdi for {key}: {lo}–{hi}')
        c[key]=v
    if 0<c['interval_hours']<6: raise ValueError('Automatisk interval skal være mindst 6 timer.')
    return c
