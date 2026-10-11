import base64, importlib, json, os, tempfile, threading, unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from core import money,parse_offers,candidate,source_url,validate_config,DEFAULTS
from crawler import Blocked, Cancelled, Crawler

class Prices(unittest.TestCase):
    def test_danish_money(self):
        self.assertEqual(money('1.935,50'),193550)
        self.assertEqual(money('805'),80500)
        for bad in ['-25','1,935.50','645 kr./md.']:
            with self.assertRaises(ValueError): money(bad)
    def test_labels_dedup_and_instalments(self):
        rows=[{'label':'Åbn tilbud fra CS MEGASTORE. Pris: 1.935\xa0kr..','text':'CS MEGASTORE'},
              {'label':'Åbn tilbud fra CS MEGASTORE. Pris: 1.935\xa0kr..','text':'Kingston 64GB\nFri fragt, 4-5 dage\n1.935 kr.\nEller 645 kr./md.'},
              {'label':'Åbn tilbud fra CompuMail. Pris: 10.083 kr..','text':'Bestillingsvare'}]
        offers=parse_offers(rows)
        self.assertEqual(len(offers),2);self.assertEqual(offers[0]['price'],193500)
        self.assertIn('4-5 dage',offers[0]['text']);self.assertTrue(offers[1]['order_only'])
    def test_unavailable(self):
        self.assertIsNone(candidate([{'merchant':'a','price':100,'unavailable':True},{'merchant':'b','price':1000,'unavailable':False}],1000,35))
    def test_unique_competitors(self):
        offers=[{'merchant':n,'price':p,'unavailable':False} for n,p in [('A',100),('a',120),('B',1000)]]
        self.assertIsNone(candidate(offers,None,35))
        offers.append({'merchant':'C','price':1100,'unavailable':False})
        self.assertIn('90%',candidate(offers,None,35))
    def test_history_drop(self):
        o=[{'merchant':'A','price':600,'unavailable':False}]
        self.assertIsNone(candidate(o,None,35));self.assertIn('40%',candidate(o,1000,35))
    def test_urls(self):
        for u in ['http://www.pricerunner.dk/cl/38/RAM','https://www.pricerunner.dk.evil.test/cl/38/RAM','https://user@www.pricerunner.dk/cl/38/RAM','https://127.0.0.1/pl/38-123/RAM','https://www.pricerunner.dk/info/test']:
            with self.assertRaises(ValueError):source_url(u)
        self.assertIn('attr=1',source_url('https://www.pricerunner.dk/cl/38/RAM?attr=1#x'))
    def test_config(self):
        self.assertEqual(validate_config(DEFAULTS),DEFAULTS)
        for key,value in [('interval_hours',1),('max_pages',0),('delay_seconds',0),('max_products',True),('max_products',1.2)]:
            with self.assertRaises(ValueError):validate_config({**DEFAULTS,key:value})

class System(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();os.environ['DATA_DIR']=self.tmp.name
        os.environ['APP_PASSWORD']='test-password-123456789'
        import app
        self.app=importlib.reload(app);self.app.init();self.url='https://www.pricerunner.dk/pl/38-123/RAM/Test'
    def tearDown(self):self.tmp.cleanup()
    def offers(self,p):return [{'merchant':'Test','price':p,'unavailable':False,'order_only':False,'text':'Fri fragt'}]
    def test_history_null(self):
        self.app.record(1,self.url,'RAM',self.offers(100000),35);self.app.record(2,self.url,'RAM',self.offers(60000),35)
        self.assertIn('40%',self.app.state()['products'][0]['reason'])
        sold=self.offers(50000);sold[0]['unavailable']=True;self.app.record(3,self.url,'RAM',sold,35)
        self.assertIsNone(self.app.state()['products'][0]['price'])
        with self.app.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],3)
    def test_restart(self):
        with self.app.connection() as db:db.execute("INSERT INTO runs(status) VALUES('kører')")
        self.app.init();self.assertEqual(self.app.state()['runs'][0]['status'],'afbrudt')
    def test_one_job(self):
        self.app.LOCK.acquire()
        try:self.assertIsNone(self.app.start_scan())
        finally:self.app.LOCK.release()
    def test_auth_csrf_http(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),self.app.Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        base='http://127.0.0.1:'+str(server.server_port);auth='Basic '+base64.b64encode(b'admin:test-password-123456789').decode()
        try:
            with self.assertRaises(HTTPError) as cm:urlopen(base+'/api/state')
            self.assertEqual(cm.exception.code,401)
            with urlopen(Request(base+'/api/state',headers={'Authorization':auth})) as r:self.assertEqual(json.load(r)['config']['max_products'],24)
            with self.assertRaises(HTTPError) as cm:urlopen(Request(base+'/api/config',data=b'{}',headers={'Authorization':auth}))
            self.assertEqual(cm.exception.code,403)
            with self.assertRaises(HTTPError) as cm:urlopen(Request(base+'/api/config',data=json.dumps({**DEFAULTS,'interval_hours':1}).encode(),headers={'Authorization':auth,'X-CSRF-Token':self.app.CSRF}))
            self.assertEqual(cm.exception.code,400)
            with urlopen(Request(base+'/',headers={'Authorization':auth})) as r:self.assertNotIn('__CSRF__',r.read().decode())
        finally:server.shutdown();server.server_close();t.join()
    def fake_run(self,blocked=False):
        browser=SimpleNamespace(new_context=lambda **kw:SimpleNamespace(new_page=lambda:object()),close=lambda:None)
        class Manager:
            def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:browser))
            def __exit__(self,*args):pass
        cfg={**DEFAULTS,'interval_hours':6};self.app.save_config(cfg)
        with self.app.connection() as db:run=db.execute("INSERT INTO runs(status) VALUES('kører')").lastrowid
        self.app.LOCK.acquire()
        discover={'side_effect':Blocked('Testblokering')} if blocked else {'return_value':([{'url':self.url,'name':'RAM'}],'Produktliste',None)}
        with patch.dict('sys.modules',{'playwright':SimpleNamespace(),'playwright.sync_api':SimpleNamespace(sync_playwright=Manager)}),patch('app.Crawler.discover',**discover),patch('app.Crawler.product',side_effect=RuntimeError('Ingen tilbud')),patch('app.Crawler.pause'),patch('app.Crawler.diagnostic'):
            self.app.run_scan(run,cfg)
    def test_block_disables_schedule(self):
        self.fake_run(True);self.assertFalse(self.app.LOCK.locked());self.assertEqual(self.app.config()['interval_hours'],0)
        self.assertEqual(self.app.state()['runs'][0]['status'],'blokeret')
    def test_successful_worker(self):
        browser=SimpleNamespace(new_context=lambda **kw:SimpleNamespace(new_page=lambda:object()),close=lambda:None)
        class Manager:
            def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:browser))
            def __exit__(self,*args):pass
        with self.app.connection() as db:run=db.execute("INSERT INTO runs(status) VALUES('kører')").lastrowid
        self.app.LOCK.acquire()
        with patch.dict('sys.modules',{'playwright':SimpleNamespace(),'playwright.sync_api':SimpleNamespace(sync_playwright=Manager)}),patch('app.Crawler.discover',return_value=([{'url':self.url,'name':'RAM'}],'Katalog slut',1)),patch('app.Crawler.product',return_value=('RAM',self.offers(193500))),patch('app.Crawler.pause'):
            self.app.run_scan(run,DEFAULTS)
        state=self.app.state()
        self.assertEqual(state['runs'][0]['status'],'færdig')
        self.assertEqual(state['runs'][0]['checked'],1)
        self.assertEqual(state['products'][0]['price'],193500)
        self.assertFalse(self.app.LOCK.locked())
    def test_block_evidence_saved_before_browser_closes(self):
        closed = False
        def read(**kw):
            if closed: raise RuntimeError('Browser closed')
            return 'Adgang nægtet — request blocked by security screening'
        page=SimpleNamespace(url='https://www.pricerunner.dk/cl/38/RAM',locator=lambda _:SimpleNamespace(inner_text=read))
        crawler=Crawler(page,DEFAULTS,threading.Event(),self.tmp.name,lambda msg:None)
        crawler.last_status=403
        with self.assertRaises(Blocked):crawler.guard()
        path=__import__('pathlib').Path(self.tmp.name)/'blocked.txt'
        self.assertTrue(path.exists())
        before=path.read_text()
        self.assertIn('HTTP-status: 403',before)
        self.assertIn('Adgang nægtet',before)
        closed=True
        crawler.diagnostic('blocked')
        self.assertEqual(path.read_text(),before)
    def test_diagnostic_save_error_visible(self):
        path=__import__('pathlib').Path(self.tmp.name)/'not-a-directory'
        path.write_text('test')
        messages=[]
        crawler=Crawler(None,DEFAULTS,threading.Event(),path,messages.append)
        crawler.diagnostic('blocked','Adgang nægtet')
        self.assertIn('Fejlrapport kunne ikke gemmes',messages[0])
    def test_cancel_interrupts_delay(self):
        stop=threading.Event();stop.set()
        crawler=Crawler(None,DEFAULTS,stop,self.tmp.name,lambda m:None)
        with self.assertRaises(Cancelled):crawler.pause()
    def test_failure_keeps_history(self):
        self.app.record(1,self.url,'RAM',self.offers(10000),35);self.fake_run()
        s=self.app.state();self.assertEqual(s['products'][0]['price'],10000)
        self.assertEqual(s['runs'][0]['errors'],1);self.assertEqual(s['runs'][0]['status'],'delvis')

if __name__=='__main__':unittest.main()
