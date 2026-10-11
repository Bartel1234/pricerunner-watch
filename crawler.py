import json
import re
from pathlib import Path
from core import product_id, parse_offers, source_url

class Blocked(Exception): pass
class Cancelled(Exception): pass

CARDS = """() => Array.from(document.querySelectorAll('a[href*="/pl/"]')).filter(a=>a.querySelector('img')).map(a=>({url:a.href,name:a.getAttribute('aria-label')||a.querySelector('img')?.alt||a.innerText.split('\\n')[0]}))"""
OFFERS = """() => Array.from(document.querySelectorAll('a[aria-label]')).filter(a=>(a.getAttribute('aria-label')||'').startsWith('Åbn tilbud fra ')).map(a=>({label:a.getAttribute('aria-label'),text:a.innerText}))"""

class Crawler:
    def __init__(self, page, config, stop, diagnostic_dir, report):
        self.page,self.config,self.stop,self.report=page,config,stop,report
        self.diagnostic_dir=Path(diagnostic_dir)
        self.last_text = None
        self.last_url = None
        self.last_status = None
    def check(self):
        if self.stop.is_set(): raise Cancelled()
    def pause(self):
        if self.stop.wait(self.config['delay_seconds']): raise Cancelled()
    def guard(self):
        self.check()
        text=self.page.locator('body').inner_text(timeout=15000)
        self.last_text = text
        self.last_url = self.page.url
        if re.search(r'verify you are human|checking your browser|adgang nægtet|access denied|unusual traffic|automated queries|bekræft.{0,20}(menneske|robot)',text,re.I):
            self.diagnostic('blocked', text)
            raise Blocked('PriceRunner viser adgangsblokering eller menneskekontrol. Automatisk scanning er slået fra.')
        return text
    def goto(self,url):
        self.check()
        self.last_text = None
        self.last_url = source_url(url)
        self.last_status = None
        response=self.page.goto(source_url(url),wait_until='domcontentloaded',timeout=45000)
        self.last_status = response.status if response else None
        self.guard()
        if response and response.status in (403,429):
            self.diagnostic('blocked', self.last_text)
            raise Blocked(f'HTTP {response.status}: adgang begrænset. Automatisk scanning er slået fra.')
        # The consent UI may appear after hydration; wait briefly via locator, not a fixed long sleep.
        try:
            self.page.get_by_role('button',name='Afvis alle',exact=True).click(timeout=3500)
        except Exception:
            self.guard()
    def discover(self,url):
        if '/pl/' in url: return [{'url':url,'name':url.split('/')[-1]}], 'Produktliste', None
        self.goto(url)
        self.page.locator('a[href*="/pl/"] img').first.wait_for(timeout=20000)
        seen={}
        total=None
        for index in range(self.config['max_pages']):
            text=self.guard()
            m=re.search(r'Du har set\s+(\d+)\s+af\s+([\d.]+)\s+produkter',text)
            if m: total=int(m[2].replace('.',''))
            for row in self.page.evaluate(CARDS):
                try:
                    if product_id(row['url']): seen[row['url']]=row
                except ValueError: pass
            self.report(f'Katalog: {len(seen)} produktlinks fundet. Batch {index+1}.')
            more=self.page.get_by_role('button',name='Vis flere',exact=True)
            if not more.count() or not more.is_visible() or (m and int(m[1])>=total):
                return list(seen.values()),'Katalog slut',total
            if index+1>=self.config['max_pages']: break
            self.pause()
            before=self.page.locator('a[href*="/pl/"]').count()
            more.click(timeout=15000)
            try:
                self.page.wait_for_function("n => document.querySelectorAll('a[href*=\"/pl/\"]').length > n",arg=before,timeout=20000)
            except Exception:
                self.guard()
                raise RuntimeError('Vis flere gav ingen nye produktlinks. Kataloget er ikke fuldt hentet.')
        return list(seen.values()),'Batchgrænse nået',total
    def product(self,url):
        self.goto(url)
        title=self.page.locator('h1').inner_text(timeout=20000)
        try:
            self.page.locator('a[aria-label^="Åbn tilbud fra "]').first.wait_for(timeout=15000)
        except Exception:
            self.guard()
            raise RuntimeError('Ingen læsbare butikstilbud. Gammel pris beholdes som historik.')
        self.guard()
        offers=parse_offers(self.page.evaluate(OFFERS))
        if not offers: raise RuntimeError('Tilbud fundet, men prisformat kunne ikke læses.')
        return title,offers
    def diagnostic(self, label, text=None):
        # Keep captured evidence usable after Playwright's context manager closes.
        # Do not overwrite a saved blocked page with an empty closed-browser read.
        try:
            self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
            path = self.diagnostic_dir / (label + '.txt')
            if text is None:
                try:
                    text = self.page.locator('body').inner_text(timeout=3000)
                except Exception:
                    text = self.last_text
            if text is None:
                if path.exists(): return
                text = 'Sidens tekst kunne ikke læses. Se URL og HTTP-status nedenfor.'
            report = f'URL: {self.last_url or "ukendt"}\nHTTP-status: {self.last_status or "ukendt"}\n\n{text[:100000]}'
            path.write_text(report, encoding='utf-8')
        except Exception as exc:
            self.report(f'Fejlrapport kunne ikke gemmes: {type(exc).__name__}: {exc}')
