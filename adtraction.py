"""Approved Adtraction v3 feeds. No browser scraping or automatic applications."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError

BASE = 'https://api.adtraction.net/v3/'
LIMIT = 64 * 1024 * 1024
HARDWARE = re.compile(r'\b(ram|ddr[345]|dimm|sodimm|grafikkort|graphics cards?|gpu|geforce|radeon|rtx|gtx|harddis[ck]e?|hard drives?|hdd|ssd|solid state)\b', re.I)

class FeedError(RuntimeError): pass
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the credential to another origin.
        raise FeedError('API omdirigerede forespørgslen. Ingen nøgle videresendt.')

def request(token, endpoint, body=None):
    req = Request(BASE + endpoint, data=None if body is None else json.dumps(body).encode(),
                  headers={'X-Token': token, 'Content-Type': 'application/json', 'Accept': 'application/json'},
                  method='GET' if body is None else 'POST')
    try:
        with build_opener(NoRedirect).open(req, timeout=60) as r:
            raw = r.read(LIMIT + 1)
            if len(raw) > LIMIT: raise FeedError('Feed overstiger 64 MiB. Vælg et mindre feed.')
            result = json.loads(raw)
            if not isinstance(result, list): raise FeedError('API returnerede et ukendt format.')
            return result, r.headers.get('feed_lastupdated', '')
    except HTTPError as e:
        # Do not log response body or request URLs with credentials.
        raise FeedError(f'Adtraction HTTP {e.code}. Kontrollér nøgle, kanal og programgodkendelse.') from None
    except (URLError, TimeoutError, OSError): raise FeedError('Adtraction kunne ikke kontaktes (netværk/timeout).') from None
    except (ValueError, UnicodeError): raise FeedError('Adtraction returnerede ugyldig JSON.') from None

def programs(token, channel):
    rows, _ = request(token, 'partner/programs/', {'market': 'DK', 'channelId': channel, 'approvalStatus': 1, 'status': 0})
    result = []
    for r in rows:
        if not isinstance(r, dict) or r.get('approvalStatus') != 1 or r.get('market') != 'DK' or r.get('currency') != 'DKK': continue
        feeds = [{'id': f['feedId'], 'name': str(f.get('name', 'Feed')), 'updated': str(f.get('lastUpdated', '')),
                  'count': f.get('numberOfProducts', 0)} for f in r.get('feeds', []) if isinstance(f, dict) and type(f.get('feedId')) is int]
        if feeds and type(r.get('programId')) is int:
            result.append({'id': r['programId'], 'name': str(r.get('programName', r['programId'])), 'feeds': feeds})
    return result

def feed(token, channel, program, feed_id):
    return request(token, 'partner/products/feed/', {'programId': program, 'channelId': channel, 'feedId': feed_id, 'setEpi': False, 'gt': False})

def gtin(value):
    s = str(value or '').strip()
    if len(s) not in (8, 12, 13, 14) or not s.isascii() or not s.isdigit(): return None
    total = sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(reversed(s[:-1])))
    if (10 - total % 10) % 10 != int(s[-1]): return None
    return s.zfill(14)

def normalize(row, program, merchant, updated):
    if not isinstance(row, dict) or row.get('approvalStatus') != 1 or row.get('currency') != 'DKK' or row.get('market') != 'DK': return None
    if row.get('programId') != program: return None
    name = str(row.get('productName') or '').strip()
    category = str(row.get('productCategory', ''))
    if not name or not HARDWARE.search(name + ' ' + category): return None
    url = str(row.get('productUrl', ''))
    try:
        u = urlsplit(url)
        if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password: return None
        price = Decimal(str(row.get('productPrice', '')))
        if not price.is_finite() or price <= 0 or price > 10000000 or price.as_tuple().exponent < -2: return None
    except (ValueError, InvalidOperation): return None
    code = gtin(row.get('ean'))
    sku = str(row.get('sku') or '').strip()
    pid = 'gtin:' + code if code else f'adtraction:{program}:' + hashlib.sha256((sku or url).encode()).hexdigest()[:24]
    stock = row.get('inStock')
    # Unknown stock remains visible, but is excluded from candidate calculations.
    text = ('På lager' if stock is True else 'Ikke på lager' if stock is False else 'Lagerstatus ukendt')
    if updated: text += ' · Feed opdateret: ' + updated
    if not code: text += ' · Uden gyldig EAN; sammenlignes kun inden for denne butik'
    offer = {'merchant': merchant, 'price': int(price * 100), 'unavailable': stock is not True,
             'order_only': False, 'text': text, 'url': url, 'feed_updated': updated, 'program_id': program}
    return {'id': pid, 'url': url, 'name': name, 'offer': offer}

def group(rows):
    result = {}
    for row in rows:
        p = result.setdefault(row['id'], {'id': row['id'], 'url': row['url'], 'name': row['name'], 'offers': []})
        offer = row['offer']
        # Feeds can overlap. Keep one available, cheapest offer per retailer.
        old = next((o for o in p['offers'] if o['program_id'] == offer['program_id']), None)
        if old is None: p['offers'].append(offer)
        elif (offer['unavailable'], offer['price']) < (old['unavailable'], old['price']):
            p['offers'].remove(old); p['offers'].append(offer)
    return result
