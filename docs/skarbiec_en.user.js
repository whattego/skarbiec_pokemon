// ==UserScript==
// @name         Skarbiec – ceny EN/NM z Cardmarketu (automatycznie)
// @namespace    itmate.skarbiec-en
// @version      1.1
// @description  Raz na dobę, przy dowolnej wizycie na Cardmarkecie, sprawdza w tle najtańsze oferty EN/NM z wysyłką do PL dla kart z twojego Skarbca (watchlisty + portfel) i zapisuje je w prywatnym repo. Skarbiec pokazuje je w kolumnie „Najtaniej EN/NM”.
// @match        https://www.cardmarket.com/*
// @match        https://*.github.io/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      api.github.com
// @run-at       document-idle
// @noframes
// @downloadURL  https://whattego.github.io/skarbiec_pokemon/skarbiec_en.user.js
// @updateURL    https://whattego.github.io/skarbiec_pokemon/skarbiec_en.user.js
// ==/UserScript==

(function () {
  'use strict';

  const EVERY_H = 20;            // jak często odświeżać (godziny)
  const MAX_CARDS = 150;         // maks. kart na jedno odświeżenie
  const FILTER = 'language=1&minCondition=2';   // EN, NM lub lepszy
  const CFG = 'sk_cfg', LAST = 'sk_en_last', LOCK = 'sk_en_lock';

  // ---------- na stronie Skarbca: przejmij token i repo (zero konfiguracji) ----------
  if (location.hostname.endsWith('github.io')) {
    if (document.title !== 'Skarbiec') return;
    const token = localStorage.getItem('skarbiec_token');
    if (!token) return;
    // jak na stronie Skarbca: repo zdjęć z ustawień, inaczej <login>/skarbiec-foto (login z adresu strony, gdy repo nie jest zapisane)
    const owner = (localStorage.getItem('skarbiec_repo') || '').split('/')[0] || location.hostname.split('.')[0];
    const photo = localStorage.getItem('skarbiec_photo_repo') || `${owner}/skarbiec-foto`;
    const cur = GM_getValue(CFG, null);
    if (!cur || cur.token !== token || cur.repo !== photo) GM_setValue(CFG, { token, repo: photo });
    return;
  }

  // ---------- na Cardmarkecie ----------
  const LANG = location.pathname.split('/')[1] || 'en';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pause = () => sleep(2000 + Math.random() * 1500);
  const eur = s => parseFloat(String(s).replace(/[^\d,.]/g, '').replace(/\.(?=\d{3})/g, '').replace(',', '.'));
  const attrText = e => e.getAttribute('title') || e.getAttribute('aria-label') || e.getAttribute('data-bs-original-title') || '';

  let badge;
  function say(txt, color = '#ddd', hideAfter) {
    if (!badge) {
      badge = document.createElement('div');
      badge.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:99999;background:#111;font:12px/1.4 system-ui,sans-serif;padding:7px 10px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.4);max-width:340px';
      document.body.appendChild(badge);
    }
    badge.style.color = color; badge.textContent = '💼 Skarbiec: ' + txt;
    if (hideAfter) setTimeout(() => { badge?.remove(); badge = null; }, hideAfter);
  }

  function gh(method, path, body, raw) {
    const c = GM_getValue(CFG, null);
    return new Promise((res, rej) => GM_xmlhttpRequest({
      method, url: `https://api.github.com/repos/${c.repo}${path}`, timeout: 60000,
      headers: { Authorization: `Bearer ${c.token}`, Accept: raw ? 'application/vnd.github.raw' : 'application/vnd.github+json', 'Content-Type': 'application/json' },
      data: body ? JSON.stringify(body) : undefined,
      onload: r => (r.status >= 200 && r.status < 300) || (method === 'GET' && r.status === 404) ? res(r)
        : rej(new Error(`GitHub ${r.status}${r.status === 401 ? ' – token wygasł albo jest nieważny; otwórz Skarbiec z nowym tokenem' : r.status === 404 ? ' – brak repozytorium albo dostępu' : ''}`)),
      onerror: () => rej(new Error('brak połączenia z GitHubem')), ontimeout: () => rej(new Error('GitHub nie odpowiada')),
    }));
  }

  // oferty z jednej strony produktu: tylko te z przyciskiem koszyka (sprzedawca wysyła do PL)
  function readOffers(doc, holo) {
    const out = [];
    for (const row of doc.querySelectorAll('.article-row')) {
      const seller = row.querySelector('.seller-name a')?.textContent.trim();
      const price = eur(row.querySelector('.color-primary.fw-bold')?.textContent);
      const form = row.querySelector('form[data-ajax-action]');
      const cart = form?.querySelector('input[name^="idArticle["]');
      const rev = [...row.querySelectorAll('[title], [aria-label], [data-bs-original-title]')].some(e => /reverse holo/i.test(attrText(e)));
      // Cardmarket pamięta ostatni filtr Reverse Holo – zwykłe i reverse rozdzielamy po ikonie oferty
      if (seller && !isNaN(price) && cart && rev === !!holo) out.push({ seller, price });
    }
    return out.sort((a, b) => a.price - b.price);
  }

  async function refresh(force) {
    const cfg = GM_getValue(CFG, null);
    // problemy z konfiguracją pokazujemy zawsze (najwyżej raz na stronę), żeby skrypt nigdy nie milczał
    if (!cfg?.token || !cfg.repo) return say('skrypt działa, ale nie zna tokenu – otwórz raz stronę Skarbca w tej przeglądarce.', '#fbbf24', 10000);
    if (/just a moment|cierpliwo|verify you are human/i.test(document.title)) return;
    if (!document.querySelector('a[href*="Logout"], form[action*="Logout"]')) return say('zaloguj się na Cardmarket – bez tego nie widać, kto wysyła do Polski.', '#fbbf24', 8000);
    const last = GM_getValue(LAST, 0);
    if (!force && Date.now() - last < EVERY_H * 36e5) {
      if (/^\/\w+\/Pokemon\/?$/.test(location.pathname)) say(`ceny EN/NM aktualne (sprawdzone ${Math.round((Date.now() - last) / 36e5)} godz. temu).`, '#888', 4000);
      return;
    }
    if (Date.now() - GM_getValue(LOCK, 0) < 15 * 60e3) { if (force) say('odświeżanie już trwa w innej karcie.', '#fbbf24', 6000); return; }
    GM_setValue(LOCK, Date.now());
    try {
      const tr = await gh('GET', '/contents/en/targets.json', null, true);
      if (tr.status === 404) { say('brak listy kart – otwórz Skarbiec, a sam ją zapisze.', '#fbbf24', 9000); return; }
      const targets = (JSON.parse(tr.responseText).items || []).slice(0, MAX_CARDS);
      const items = {};
      let n = 0, stop = '';
      for (const t of targets) {
        n++; GM_setValue(LOCK, Date.now());
        say(`ceny EN/NM ${n}/${targets.length}…`, '#aaa');
        const url = `/${LANG}/Pokemon/Products?idProduct=${t.id}&${FILTER}${t.holo ? '&isReverseHolo=Y' : ''}`;
        let r;
        for (const wait of [0, 30, 60, 120]) {
          if (wait) { say(`Cardmarket zwolnił – czekam ${wait} s…`, '#fbbf24'); await sleep(wait * 1000); }
          r = await fetch(url, { credentials: 'include' });
          if (r.status !== 403 && r.status !== 429) break;
        }
        if (!r.ok) { stop = `HTTP ${r.status}`; break; }
        const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
        if (/just a moment|cierpliwo|verify you are human/i.test(doc.title)) { stop = 'Cloudflare'; break; }
        const offers = readOffers(doc, t.holo), top3 = offers.slice(0, 3);
        items[`${t.id}${t.holo ? 'h' : ''}`] = {
          min: offers[0]?.price ?? null, avg3: top3.length ? +(top3.reduce((a, o) => a + o.price, 0) / top3.length).toFixed(2) : null,
          n: offers.length, seller: offers[0]?.seller || '', name: t.name || '',
        };
        await pause();
      }
      if (Object.keys(items).length) {
        const cur = await gh('GET', '/contents/en/auto.json');
        const sha = cur.status === 200 ? JSON.parse(cur.responseText).sha : undefined;
        const doc = { v: 1, t: new Date().toISOString(), name: 'automatycznie', filter: FILTER, items };
        await gh('PUT', '/contents/en/auto.json', { message: `ceny EN/NM: ${Object.keys(items).length} kart`, content: btoa(unescape(encodeURIComponent(JSON.stringify(doc)))), ...(sha ? { sha } : {}) });
      }
      if (stop) say(`przerwano po ${n - 1}/${targets.length} kartach (${stop}); zapisano to, co sprawdzone. Spróbuję przy następnej wizycie.`, '#fbbf24', 12000);
      else { GM_setValue(LAST, Date.now()); say(`✓ ceny EN/NM ${targets.length} kart zapisane.`, '#4ade80', 6000); }
    } catch (e) {
      say('⚠️ ' + e.message, '#f87171', 12000);
    } finally {
      GM_setValue(LOCK, 0);
    }
  }

  GM_registerMenuCommand('Skarbiec: odśwież ceny EN/NM teraz', () => refresh(true));
  refresh(location.hash === '#skarbiec-en');
})();
