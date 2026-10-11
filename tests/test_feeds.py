import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from email.message import Message
import adtraction
from core import DEFAULTS, validate_config

EAN='0711719437215'
def row(**kw):
    return {'productName':'DDR5 RAM 32GB','productCategory':'RAM','productPrice':'805.50',
            'productUrl':'https://shop.example/product/1','currency':'DKK','programId':1,
            'approvalStatus':1,'market':'DK','ean':EAN,'sku':'ram-1','inStock':True,**kw}
PROGRAMS=[{'id':1,'name':'Testbutik','feeds':[{'id':10,'name':'Hardware'}]}]

class Feeds(unittest.TestCase):
    def test_money_and_stock(self):
        normalized=adtraction.normalize(row(),1,'Testbutik','2026-10-11')
        self.assertEqual(normalized['offer']['price'],80550)
        self.assertFalse(normalized['offer']['unavailable'])
        for stock in (False,None,'true',1):
            self.assertTrue(adtraction.normalize(row(inStock=stock),1,'Test','')['offer']['unavailable'])
        for price in ('NaN','Infinity','0','-2','1.000,50','12.345','1e20'):
            self.assertIsNone(adtraction.normalize(row(productPrice=price),1,'Test',''))
    def test_no_foreign_unapproved_or_bad_url(self):
        for kw in ({'currency':'SEK'},{'market':'SE'},{'approvalStatus':2},{'programId':3},
                   {'productUrl':'javascript:alert(1)'},{'productUrl':'https://name:pass@example.com/'},
                   {'productName':'Shirt','productCategory':'Clothing'}):
            self.assertIsNone(adtraction.normalize(row(**kw),1,'Test',''))
    def test_matching_is_exact_gtin_and_store_scoped_fallback(self):
        self.assertEqual(adtraction.gtin(EAN), '0'+EAN)
        self.assertIsNone(adtraction.gtin('0711719437216'))
        a=adtraction.normalize(row(),1,'A','')
        b=adtraction.normalize(row(programId=2,ean='0'+EAN),2,'B','')
        self.assertEqual(a['id'],b['id'])
        grouped=adtraction.group([a,b,a]);self.assertEqual(len(grouped[a['id']]['offers']),2)
        a=adtraction.normalize(row(ean=''),1,'A','')
        b=adtraction.normalize(row(programId=2,ean=''),2,'B','')
        self.assertNotEqual(a['id'],b['id'])
        a=adtraction.normalize(row(ean=None,sku=None),1,'A','')
        b=adtraction.normalize(row(ean=None,sku=None,productUrl='https://shop.example/product/2'),1,'A','')
        self.assertNotEqual(a['id'],b['id'])
    def test_request_contract_and_secret_redaction(self):
        class Response:
            headers=Message()
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,*_):return b'[]'
        token='private-test-token-1234'
        with patch('adtraction.build_opener') as opener:
            opener.return_value.open.return_value=Response()
            adtraction.feed(token,3,1,10)
            req=opener.return_value.open.call_args.args[0]
            self.assertNotIn(token,req.full_url)
            self.assertEqual(req.get_header('X-token'),token)
            self.assertEqual(json.loads(req.data),{'programId':1,'channelId':3,'feedId':10,'setEpi':False,'gt':False})
        error=adtraction.HTTPError('https://example.test/?secret=abc',403,'secret-response',{},None)
        with patch('adtraction.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(adtraction.FeedError) as cm:adtraction.feed(token,3,1,10)
            self.assertNotIn('secret',str(cm.exception))
        with self.assertRaises(adtraction.FeedError):adtraction.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
    def test_bad_feed_selection(self):
        for picks in ([{'program_id':True,'feed_id':1}],[{'program_id':1,'feed_id':0}],['x']):
            with self.assertRaises(ValueError):validate_config({**DEFAULTS,'feed_selections':picks})

class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();os.environ['DATA_DIR']=self.tmp.name
        import app
        self.app=importlib.reload(app);self.app.init()
        self.app.save_credentials({'token':'private-test-token-1234','channel_id':3})
        self.cfg={**DEFAULTS,'feed_selections':[{'program_id':1,'feed_id':10}]}
    def tearDown(self):self.tmp.cleanup()
    def run_feed(self,rows=None,error=None):
        with self.app.connection() as db:run=db.execute("INSERT INTO runs(status) VALUES('kører')").lastrowid
        self.app.LOCK.acquire()
        mock={'side_effect':error} if error else {'return_value':(rows,'2026-10-11')}
        with patch('app.adtraction.programs',return_value=PROGRAMS),patch('app.adtraction.feed',**mock),patch.object(self.app.STOP,'wait',return_value=False):
            self.app.run_scan(run,self.cfg)
        return self.app.state()
    def test_feed_worker_and_price_drop(self):
        state=self.run_feed([row(productPrice='1000')])
        self.assertEqual(state['runs'][0]['status'],'færdig')
        self.assertEqual(state['products'][0]['price'],100000)
        state=self.run_feed([row(productPrice='600')])
        self.assertIn('40%',state['products'][0]['reason'])
        self.assertFalse(self.app.LOCK.locked())
    def test_failed_feed_keeps_history_and_turns_off_schedule(self):
        self.run_feed([row()]);self.app.save_config({**self.cfg,'interval_hours':24})
        state=self.run_feed(error=adtraction.FeedError('HTTP 403'))
        self.assertEqual(state['products'][0]['price'],80550)
        self.assertEqual(state['runs'][0]['checked'],0)
        self.assertEqual(state['runs'][0]['status'],'fejl')
        self.assertEqual(state['config']['interval_hours'],0)
    def test_secret_not_exported_and_channel_reset(self):
        self.assertNotIn('private-test-token',json.dumps(self.app.state()))
        self.assertEqual((Path(self.tmp.name)/'adtraction-secrets.json').stat().st_mode&0o777,0o600)
        self.app.save_config(self.cfg)
        self.app.save_credentials({'token':'','channel_id':4})
        self.assertEqual(self.app.config()['feed_selections'],[])
        self.assertEqual(self.app.credentials()['token'],'private-test-token-1234')
    def test_changed_available_shops_not_history_drop(self):
        offers=[{'merchant':'A','program_id':1,'price':100000,'unavailable':False}]
        self.app.record(1,'https://shop.test/','RAM',offers,35,'gtin:'+EAN)
        offers=[{'merchant':'B','program_id':2,'price':60000,'unavailable':False}]
        self.app.record(2,'https://shop.test/','RAM',offers,35,'gtin:'+EAN)
        self.assertIsNone(self.app.state()['products'][0]['reason'])
    def test_migration_preserves_history_disables_old_crawler(self):
        self.app.record(1,'https://www.pricerunner.dk/pl/38-123/RAM/Test','RAM',[],35)
        old={k:v for k,v in DEFAULTS.items() if k not in ('source_mode','feed_selections')};old['interval_hours']=6
        self.app.save_config(old);self.app.init()
        self.assertEqual(self.app.config()['source_mode'],'adtraction')
        self.assertEqual(self.app.config()['interval_hours'],0)
        self.assertEqual(len(self.app.state()['products']),1)
