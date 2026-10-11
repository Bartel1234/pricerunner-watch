import base64
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from core import VERSION, DEFAULTS, PRESETS, validate_config, product_id, candidate
from crawler import Crawler, Blocked, Cancelled
import adtraction

DATA=Path(os.environ.get('DATA_DIR','./data'))
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'prices.sqlite3'
LOCK=threading.Lock()
STOP=threading.Event()
CSRF=secrets.token_urlsafe(32)
PASSWORD=os.environ.get('APP_PASSWORD','')

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def connection():
    db=sqlite3.connect(DB,timeout=30)
    db.row_factory=sqlite3.Row
    return db

def init():
    with connection() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,started TEXT,ended TEXT,status TEXT,message TEXT,discovered INTEGER DEFAULT 0,checked INTEGER DEFAULT 0,errors INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,url TEXT,name TEXT,last_seen TEXT);
        CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,product_id TEXT,run_id INTEGER,at TEXT,price INTEGER,offers TEXT,reason TEXT);
        CREATE INDEX IF NOT EXISTS obs_product ON observations(product_id,id);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id INTEGER,at TEXT,message TEXT);
        ''')
        db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)',(json.dumps(DEFAULTS),))
        saved=json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
        if 'source_mode' not in saved:
            saved.update(source_mode='adtraction',feed_selections=[],interval_hours=0)
            db.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(saved),))
        db.execute("UPDATE runs SET status='afbrudt',ended=?,message='Container genstartet under scanning. Delresultater er gemt.' WHERE status='kører'",(now(),))

def config():
    with connection() as db: return json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
def save_config(c):
    with connection() as db: db.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(c),))
def credentials():
    path=DATA/'adtraction-secrets.json'
    return json.loads(path.read_text()) if path.exists() else {}

def save_credentials(data):
    old=credentials()
    token=data.get('token','') or old.get('token','')
    channel=data.get('channel_id')
    if not isinstance(token,str) or not 16<=len(token)<=256 or not token.isascii() or any(c.isspace() for c in token): raise ValueError('Indtast en gyldig API-nøgle.')
    if type(channel) is not int or channel<=0: raise ValueError('Kanal-ID skal være et positivt heltal.')
    path=DATA/'adtraction-secrets.json';tmp=DATA/'adtraction-secrets.tmp'
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f: json.dump({'token':token,'channel_id':channel},f)
    tmp.replace(path)
    if old.get('channel_id')!=channel:
        c=config();c['feed_selections']=[];c['interval_hours']=0;save_config(c)


def event(run,message):
    with connection() as db:
        db.execute('INSERT INTO events(run_id,at,message) VALUES(?,?,?)',(run,now(),message))
        db.execute('UPDATE runs SET message=? WHERE id=?',(message,run))
    print(message,flush=True)
def update_run(run,**values):
    with connection() as db:
        db.execute('UPDATE runs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),run))
def record(run,url,title,offers,threshold,pid=None):
    pid=pid or product_id(url)
    available=[o['price'] for o in offers if not o['unavailable']]
    price=min(available) if available else None
    with connection() as db:
        old=db.execute('SELECT price,offers FROM observations WHERE product_id=? ORDER BY id DESC LIMIT 1',(pid,)).fetchone()
        previous=old['price'] if old else None
        if pid.startswith(('gtin:','adtraction:')) and old:
            before={o.get('program_id') for o in json.loads(old['offers']) if not o['unavailable']}
            after={o.get('program_id') for o in offers if not o['unavailable']}
            if before!=after: previous=None
        reason=candidate(offers,previous,threshold)
        db.execute('INSERT INTO products VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url,last_seen=excluded.last_seen',(pid,url,title,now()))
        db.execute('INSERT INTO observations(product_id,run_id,at,price,offers,reason) VALUES(?,?,?,?,?,?)',(pid,run,now(),price,json.dumps(offers,ensure_ascii=False),reason))

def run_pricerunner(run,c):
    discovered={};checked=errors=0;limited=False;browser=None;crawler=None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            context=browser.new_context(locale='da-DK',viewport={'width':1440,'height':1000})
            page=context.new_page()
            crawler=Crawler(page,c,STOP,DATA/'diagnostics'/str(run),lambda msg:event(run,msg))
            for source in c['sources']:
                try:
                    rows,coverage,total=crawler.discover(source)
                    discovered.update({r['url']:r for r in rows})
                    limited |= coverage=='Batchgrænse nået'
                    event(run,f'{coverage}: {len(rows)} links; kategoriens oplyste total: {total or "ukendt"}.')
                    update_run(run,discovered=len(discovered))
                    crawler.pause()
                except (Blocked,Cancelled): raise
                except Exception as e:
                    errors+=1;event(run,f'Kildefejl: {type(e).__name__}: {str(e)[:350]}');crawler.diagnostic('source-'+str(errors))
            # Prioritize never-checked/oldest products, rather than the same first 24 every run.
            with connection() as db: ages={r['id']:r['last_seen'] for r in db.execute('SELECT id,last_seen FROM products')}
            urls=sorted(discovered,key=lambda u:ages.get(product_id(u),''))
            limited |= len(urls)>c['max_products']
            for index,url in enumerate(urls[:c['max_products']]):
                crawler.check()
                event(run,f'Produkt {index+1}/{min(len(urls),c["max_products"])}: {discovered[url]["name"]}')
                try:
                    title,offers=crawler.product(url)
                    record(run,url,title,offers,c['discount_percent']);checked+=1
                except (Blocked,Cancelled): raise
                except Exception as e:
                    errors+=1;event(run,f'Produktfejl: {type(e).__name__}: {str(e)[:350]}');crawler.diagnostic('product-'+str(errors))
                update_run(run,checked=checked,errors=errors)
                crawler.pause()
            if not discovered: raise RuntimeError('Ingen produktlinks fundet.')
            status='delvis' if limited or errors else 'færdig'
            event(run,f'{checked} produkter målt, {errors} fejl. '+('Grænser/fejl betyder, at dette ikke er en fuld katalogscanning.' if status=='delvis' else 'Alle fundne produkter i de valgte kilder er behandlet.'))
            update_run(run,status=status)
            browser.close()
    except Blocked as e:
        c['interval_hours']=0;save_config(c)
        if crawler: crawler.diagnostic('blocked')
        update_run(run,status='blokeret');event(run,str(e))
    except Cancelled:
        update_run(run,status='stoppet');event(run,'Stoppet af bruger. Delresultater er gemt.')
    except Exception as e:
        update_run(run,status='fejl');event(run,f'{type(e).__name__}: {str(e)[:800]}')
    finally:
        update_run(run,ended=now(),checked=checked,errors=errors)
        LOCK.release()

def run_feeds(run,c):
    checked=errors=0
    try:
        auth=credentials()
        if not auth.get('token'): raise ValueError('Gem Adtraction-nøgle og kanal-ID under Indstillinger.')
        if not c.get('feed_selections'): raise ValueError('Hent og vælg mindst ét godkendt feed under Indstillinger.')
        allowed=adtraction.programs(auth['token'],auth['channel_id'])
        lookup={(p['id'],f['id']):p['name'] for p in allowed for f in p['feeds']}
        rows=[]
        for selection in c['feed_selections']:
            if STOP.is_set(): raise Cancelled()
            pair=(selection['program_id'],selection['feed_id'])
            if pair not in lookup: raise adtraction.FeedError('Et valgt feed er ikke tilgængeligt/godkendt for denne kanal. Hent feedlisten igen.')
            event(run,'Henter godkendt feed: '+lookup[pair])
            try:
                raw,updated=adtraction.feed(auth['token'],auth['channel_id'],*pair)
                count=0
                for r in raw:
                    if STOP.is_set(): raise Cancelled()
                    row=adtraction.normalize(r,pair[0],lookup[pair],updated)
                    if row: rows.append(row);count+=1
                event(run,f'{lookup[pair]}: {len(raw)} feedrækker; {count} hardwaretilbud i DKK med gyldig pris.')
            except adtraction.FeedError:
                # No incomplete retailer set is committed: that could create false drops.
                raise
            if STOP.wait(3): raise Cancelled()
        products=adtraction.group(rows)
        update_run(run,discovered=len(products))
        if not products: raise adtraction.FeedError('Ingen RAM, grafikkort, harddiske eller SSD matchede de valgte feeds. Ingen målinger gemt.')
        for product in products.values():
            if STOP.is_set(): raise Cancelled()
            record(run,product['url'],product['name'],product['offers'],c['discount_percent'],product['id']);checked+=1
            if checked%100==0: update_run(run,checked=checked)
        event(run,f'{checked} hardwareprodukter importeret fra {len(c["feed_selections"])} feeds. Feeddata kan være forsinkede; kontrollér tilbud hos butikken.')
        update_run(run,status='færdig')
    except Cancelled:
        update_run(run,status='stoppet');event(run,'Stoppet af bruger. Allerede gemte målinger bevares.')
    except Exception as e:
        errors=1
        # Error strings from the API adapter are deliberately sanitized.
        message=str(e) if isinstance(e,(adtraction.FeedError,ValueError)) else 'Intern fejl: '+type(e).__name__
        update_run(run,status='fejl');event(run,message)
        c['interval_hours']=0;save_config(c)
    finally:
        update_run(run,ended=now(),checked=checked,errors=errors)
        LOCK.release()

def run_scan(run,c):
    if c.get('source_mode','adtraction')=='adtraction': run_feeds(run,c)
    else: run_pricerunner(run,c)


def start_scan():
    if not LOCK.acquire(blocking=False): return None
    try:
        STOP.clear();c=config()
        with connection() as db:
            run=db.execute("INSERT INTO runs(started,status,message) VALUES(?,'kører','Starter datakilde…')",(now(),)).lastrowid
        threading.Thread(target=run_scan,args=(run,c),daemon=True).start()
        return run
    except Exception:
        LOCK.release();raise

def scheduler():
    while True:
        time.sleep(30)
        try:
            c=config()
            if not c['interval_hours'] or LOCK.locked(): continue
            with connection() as db: last=db.execute('SELECT started FROM runs ORDER BY id DESC LIMIT 1').fetchone()
            # Enabling a schedule requires an initial manual scan.
            if last and time.time()-datetime.fromisoformat(last[0]).timestamp()>=c['interval_hours']*3600: start_scan()
        except Exception as e: print('Scheduler:',type(e).__name__,str(e),flush=True)

def state():
    with connection() as db:
        runs=[dict(r) for r in db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 12')]
        products=[dict(r) for r in db.execute('''SELECT p.*,o.at,o.price,o.reason,o.offers,o.run_id FROM products p JOIN observations o ON o.id=(SELECT MAX(id) FROM observations WHERE product_id=p.id) ORDER BY (o.reason IS NOT NULL) DESC,o.at DESC''')]
        for r in products: r['offers']=json.loads(r['offers'])
        events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 30')]
    auth=credentials()
    return {'adtraction':{'configured':bool(auth.get('token')),'channel_id':auth.get('channel_id')},'version':VERSION,'running':LOCK.locked(),'config':config(),'presets':PRESETS,'runs':runs,'products':products,'events':events}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args): pass
    def reply(self,status,body,kind='application/json; charset=utf-8',headers=None):
        if isinstance(body,(dict,list)): body=json.dumps(body,ensure_ascii=False).encode()
        elif isinstance(body,str): body=body.encode()
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def authorized(self):
        expected='Basic '+base64.b64encode(('admin:'+PASSWORD).encode()).decode()
        if not PASSWORD or not hmac.compare_digest(self.headers.get('Authorization',''),expected):
            self.reply(401,{'error':'Log ind med admin og APP_PASSWORD.'},headers={'WWW-Authenticate':'Basic realm="PriceRunner Watch", charset="UTF-8"'})
            return False
        return True
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/healthz': return self.reply(200,{'ok':True})
        if not self.authorized(): return
        if path=='/':
            html=(Path(__file__).parent/'templates/index.html').read_text().replace('__CSRF__',CSRF)
            return self.reply(200,html,'text/html; charset=utf-8')
        if path=='/api/state': return self.reply(200,state())
        if path=='/api/history':
            pid=parse_qs(urlsplit(self.path).query).get('id',[''])[0]
            with connection() as db: rows=[dict(r) for r in db.execute('SELECT at,price,reason,offers FROM observations WHERE product_id=? ORDER BY id DESC LIMIT 100',(pid,))]
            for row in rows: row['offers']=json.loads(row['offers'])
            return self.reply(200,rows)
        if path=='/api/export': return self.reply(200,state(),headers={'Content-Disposition':'attachment; filename="pricerunner-export.json"'})
        return self.reply(404,{'error':'Ikke fundet'})
    def do_POST(self):
        if not self.authorized(): return
        if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),CSRF): return self.reply(403,{'error':'Genindlæs siden.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=65536: raise ValueError('For stor forespørgsel')
            data=json.loads(self.rfile.read(size) or b'{}')
            if self.path=='/api/start':
                run=start_scan()
                return self.reply(202 if run else 409,{'run':run,'error':None if run else 'En scanning kører allerede.'})
            if self.path=='/api/stop': STOP.set();return self.reply(200,{'ok':True})
            if self.path in ('/api/adtraction','/api/adtraction/programs'):
                if not LOCK.acquire(blocking=False): return self.reply(409,{'error':'Stop scanning først.'})
                try:
                    if self.path=='/api/adtraction':
                        save_credentials(data);return self.reply(200,{'ok':True})
                    auth=credentials()
                    if not auth.get('token'): raise ValueError('Gem nøgle og kanal-ID først.')
                    return self.reply(200,{'programs':adtraction.programs(auth['token'],auth['channel_id'])})
                except adtraction.FeedError as e: return self.reply(400,{'error':str(e)})
                finally: LOCK.release()
            if self.path=='/api/config':
                if not LOCK.acquire(blocking=False): return self.reply(409,{'error':'Stop scanning før ændring af indstillinger.'})
                try: save_config(validate_config(data))
                finally: LOCK.release()
                return self.reply(200,{'ok':True})
            return self.reply(404,{'error':'Ikke fundet'})
        except (ValueError,TypeError,AttributeError) as e: self.reply(400,{'error':str(e)})

if __name__=='__main__':
    if len(PASSWORD)<16: raise SystemExit('APP_PASSWORD skal indeholde mindst 16 tegn. Se README.')
    init()
    threading.Thread(target=scheduler,daemon=True).start()
    print(f'PriceRunner Watch {VERSION} · port 8788',flush=True)
    server=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8788'))),Handler)
    server.serve_forever()
