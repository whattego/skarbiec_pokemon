// ==UserScript==
// @name         Skarbiec – ceny EN/NM z Cardmarketu (automatycznie)
// @namespace    itmate.skarbiec-en
// @version      1.2
// @description  Sprawdza najtańsze oferty EN/NM z wysyłką do PL dla kart z twojego Skarbca (watchlisty + portfel) i zapisuje je w prywatnym repo. Działa z przycisku „Uaktualnij ceny EN/NM” w Skarbcu, sam przy otwarciu Skarbca albo Cardmarketu (gdy ceny mają ponad 20 h).
// @match        https://www.cardmarket.com/*
// @match        https://*.github.io/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      api.github.com
// @connect      www.cardmarket.com
// @run-at       document-idle
// @noframes
// @downloadURL  https://whattego.github.io/skarbiec_pokemon/skarbiec_en.user.js
// @updateURL    https://whattego.github.io/skarbiec_pokemon/skarbiec_en.user.js
// ==/UserScript==

(function () {
  'use strict';

  const VERSION = '1.2';
  const EVERY_H = 20;            // jak często odświeżać samo (godziny)
  const MAX_CARDS = 150;         // maks. kart na jedno odświeżenie
  const HISTORY_MAX = 400;       // ile pomiarów trzymać w en/history.json
  const FILTER = 'language=1&minCondition=2';   // EN, NM lub lepszy
  const CFG = 'sk_cfg', LAST = 'sk_en_last', LOCK = 'sk_en_lock';
  const onCM = location.hostname === 'www.cardmarket.com';

  // ---------- na stronie Skarbca: przejmij token i repo (zero konfiguracji) ----------
  if (!onCM) {
    if (document.title !== 'Skarbiec') return;
    document.documentElement.dataset.skarbiecEn = VERSION;   // strona wie, że skrypt jest zainstalowany
    const token = localStorage.getItem('skarbiec_token');
    if (token) {
      // jak na stronie Skarbca: repo zdjęć z ustawień, inaczej <login>/skarbiec-foto (login z adresu strony, gdy repo nie jest zapisane)
      const owner = (localStorage.getItem('skarbiec_repo') || '').split('/')[0] || location.hostname.split('.')[0];
      const photo = localStorage.getItem('skarbiec_photo_repo') || `${owner}/skarbiec-foto`;
      const cur = GM_getValue(CFG, null);
      if (!cur || cur.token !== token || cur.repo !== photo) GM_setValue(CFG, { token, repo: photo });
    }
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pause = () => sleep(2000 + Math.random() * 1500);
  const eur = s => parseFloat(String(s).replace(/[^\d,.]/g, '').replace(/\.(?=\d{3})/g, '').replace(',', '.'));
  const attrText = e => e.getAttribute('title') || e.getAttribute('aria-label') || e.getAttribute('data-bs-original-title') || '';
  const isChallenge = title => /just a moment|cierpliwo|verify you are human|attention required/i.test(title || '');

  // ---------- komunikaty: na Cardmarkecie plakietka w rogu, w Skarbcu status dla strony ----------
  let badge;
  function report(state, txt, hideAfter) {   // state: run | ok | warn | err
    if (!onCM) {
      document.documentElement.dataset.skarbiecEnStatus = JSON.stringify({ state, text: txt, t: Date.now() });
      document.dispatchEvent(new Event('skarbiec-en-status'));
      return;
    }
    if (!badge) {
      badge = document.createElement('div');
      badge.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:99999;background:#111;font:12px/1.4 system-ui,sans-serif;padding:7px 10px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.4);max-width:340px';
      document.body.appendChild(badge);
    }
    badge.style.color = { run: '#aaa', ok: '#4ade80', warn: '#fbbf24', err: '#f87171' }[state] || '#ddd';
    badge.textContent = '💼 Skarbiec: ' + txt;
    if (hideAfter) setTimeout(() => { badge?.remove(); badge = null; }, hideAfter);
  }

  function gh(method, path, body, raw) {
    const c = GM_getValue(CFG, null);
    return new Promise((res, rej) => GM_xmlhttpRequest({
      method, url: `https://api.github.com/repos/${c.repo}${path}`, timeout: 60000,
      headers: { Authorization: `Bearer ${c.token}`, Accept: raw ? 'application/vnd.github.raw' : 'application/vnd.github+json', 'Content-Type': 'application/json' },
      data: body ? JSON.stringify(body) : undefined,
      onload: r => (r.status >= 200 && r.status < 300) || (method === 'GET' && r.status === 404) ? res(r)
        : rej(new Error(`GitHub ${r.status}${r.status === 401 ? ' – token wygasł albo jest nieważny; wpisz nowy w Ustawieniach Skarbca' : r.status === 404 ? ' – brak repozytorium albo dostępu' : ''}`)),
      onerror: () => rej(new Error('brak połączenia z GitHubem')), ontimeout: () => rej(new Error('GitHub nie odpowiada')),
    }));
  }
  async function ghPutJson(path, obj, message) {
    const cur = await gh('GET', `/contents/${path}`);
    const sha = cur.status === 200 ? JSON.parse(cur.responseText).sha : undefined;
    await gh('PUT', `/contents/${path}`, { message, content: btoa(unescape(encodeURIComponent(JSON.stringify(obj)))), ...(sha ? { sha } : {}) });
  }

  // strona Cardmarketu: na samym Cardmarkecie zwykły fetch, w Skarbcu przez Tampermonkey z twoimi ciasteczkami Cardmarketu
  function cmGet(path) {
    if (onCM) return fetch(path, { credentials: 'include' }).then(async r => ({ status: r.status, html: await r.text() }));
    return new Promise((res, rej) => GM_xmlhttpRequest({
      method: 'GET', url: 'https://www.cardmarket.com' + path, timeout: 60000, anonymous: false,
      onload: r => res({ status: r.status, html: r.responseText }),
      onerror: () => rej(new Error('brak połączenia z Cardmarketem')), ontimeout: () => rej(new Error('Cardmarket nie odpowiada')),
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
    if (!cfg?.token || !cfg.repo) return report('warn', onCM ? 'skrypt działa, ale nie zna tokenu – otwórz raz stronę Skarbca w tej przeglądarce.' : 'brak tokenu GitHub – wpisz go w Ustawieniach Skarbca.', 10000);
    if (onCM && isChallenge(document.title)) return;
    const last = GM_getValue(LAST, 0);
    if (!force && Date.now() - last < EVERY_H * 36e5) {
      if (onCM && /^\/\w+\/Pokemon\/?$/.test(location.pathname)) report('ok', `ceny EN/NM aktualne (sprawdzone ${Math.round((Date.now() - last) / 36e5)} godz. temu).`, 4000);
      return;
    }
    if (Date.now() - GM_getValue(LOCK, 0) < 3 * 60e3) return report('warn', 'odświeżanie już trwa w innej karcie.', 6000);
    GM_setValue(LOCK, Date.now());
    try {
      const tr = await gh('GET', '/contents/en/targets.json', null, true);
      if (tr.status === 404) return report('warn', 'brak listy kart – dodaj coś do watchlisty albo portfela w Skarbcu.', 9000);
      const targets = (JSON.parse(tr.responseText).items || []).slice(0, MAX_CARDS);
      const items = {};
      let n = 0, stop = '';
      for (const t of targets) {
        n++; GM_setValue(LOCK, Date.now());
        report('run', `sprawdzam ceny EN/NM: ${n}/${targets.length}…`);
        const url = `/en/Pokemon/Products?idProduct=${t.id}&${FILTER}${t.holo ? '&isReverseHolo=Y' : ''}`;
        let r;
        for (const wait of [0, 30, 60, 120]) {
          if (wait) { report('warn', `Cardmarket zwolnił – czekam ${wait} s…`); await sleep(wait * 1000); }
          r = await cmGet(url);
          if (r.status !== 403 && r.status !== 429) break;
        }
        const doc = new DOMParser().parseFromString(r.html, 'text/html');
        if (isChallenge(doc.title)) { stop = 'Cardmarket prosi o weryfikację – otwórz cardmarket.com, przejdź ją i kliknij „Uaktualnij” jeszcze raz'; break; }
        if (r.status < 200 || r.status >= 300) { stop = `Cardmarket HTTP ${r.status}`; break; }
        if (n === 1 && !doc.querySelector('a[href*="Logout"], form[action*="Logout"]')) { stop = 'nie jesteś zalogowany na Cardmarket w tej przeglądarce – zaloguj się i spróbuj ponownie'; n = 0; break; }
        const offers = readOffers(doc, t.holo), top3 = offers.slice(0, 3);
        items[`${t.id}${t.holo ? 'h' : ''}`] = {
          min: offers[0]?.price ?? null, avg3: top3.length ? +(top3.reduce((a, o) => a + o.price, 0) / top3.length).toFixed(2) : null,
          n: offers.length, seller: offers[0]?.seller || '', name: t.name || '',
        };
        if (n < targets.length) await pause();
      }
      const keys = Object.keys(items);
      if (keys.length) {
        report('run', 'zapisuję w Skarbcu…');
        const t = new Date().toISOString();
        await ghPutJson('en/auto.json', { v: 1, t, name: 'automatycznie', filter: FILTER, items }, `ceny EN/NM: ${keys.length} kart`);
        // historia do wykresu: tylko najtańsza cena każdej karty
        const hr = await gh('GET', '/contents/en/history.json', null, true);
        const hist = hr.status === 200 ? JSON.parse(hr.responseText) : { v: 1, h: [] };
        hist.h.push({ t, p: Object.fromEntries(keys.map(k => [k, items[k].min])) });
        hist.h = hist.h.slice(-HISTORY_MAX);
        await ghPutJson('en/history.json', hist, 'historia cen EN/NM');
      }
      if (stop) report(keys.length ? 'warn' : 'err', keys.length ? `przerwano po ${keys.length}/${targets.length} kartach: ${stop}. Zapisano to, co sprawdzone.` : stop, 15000);
      else { GM_setValue(LAST, Date.now()); report('ok', `✓ ceny EN/NM ${targets.length} kart zapisane.`, 6000); }
    } catch (e) {
      report('err', '⚠️ ' + e.message, 12000);
    } finally {
      GM_setValue(LOCK, 0);
    }
  }

  GM_registerMenuCommand('Skarbiec: odśwież ceny EN/NM teraz', () => refresh(true));
  if (!onCM) document.addEventListener('skarbiec-en-refresh', () => refresh(true));
  refresh(onCM && location.hash === '#skarbiec-en');
})();
