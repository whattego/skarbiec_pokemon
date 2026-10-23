# Skarbiec – panel inwestycyjny kart Pokémon

Twoja prywatna strona z wykresami, z portfelem (zysk/strata, data, od której sprzedaż nie wymaga PIT), z watchlistami i z przeglądem rynku. Do tego bot, który codziennie sprawdza ceny i pisze na Discord, gdy jest okazja.

- **Koszt: 0 zł.** Strona działa na GitHub Pages, bot na GitHub Actions.
- **Twój komputer może być wyłączony.**
- **Bez ryzyka bana.** Bot nie loguje się na Cardmarket, tylko czyta jego publiczny cennik (raz na dobę, ok. 3:00).
- **Prywatność.** Watchlisty, portfel i historia są szyfrowane AES-256 twoim hasłem. W repozytorium leżą tylko zaszyfrowane pliki. Hasło nigdy nie opuszcza przeglądarki.

## Instalacja (ok. 20 minut, jednorazowo)

### 1. Repozytorium na GitHubie
1. Załóż konto na github.com (jeśli nie masz).
2. **+ → New repository**, nazwa: `skarbiec`, widoczność **Public** (darmowe Pages wymagają publicznego repozytorium; twoje dane i tak są zaszyfrowane) → **Create repository**.
3. Kliknij **uploading an existing file** i przeciągnij **zawartość** rozpakowanego folderu `skarbiec`: foldery `.github`, `bot`, `docs` i plik `README.md` → **Commit changes**.
   - Folder `.github` jest ukryty. W Windows: Eksplorator → Widok → Pokaż → Ukryte elementy.
   - Jeśli `.github` się nie wgra: **Add file → Create new file**, wpisz nazwę `.github/workflows/bot.yml` i wklej treść tego pliku.

4. Drugie repozytorium na zdjęcia kart (skaner): **+ → New repository**, nazwa `skarbiec-foto`, widoczność **Private**, zaznacz **Add a README file** → **Create repository**. Zostaje puste, strona sama będzie do niego zapisywać.

Zamiast wgrywania przez przeglądarkę możesz wypchnąć lokalne repozytorium (folder `skarbiec` ma już `git init` i pierwszy commit):
```bash
git remote add origin https://github.com/TWÓJ-LOGIN/skarbiec.git
git push -u origin main
```
Jeśli w repozytorium na GitHubie są już pliki (np. wgrane przez przeglądarkę albo `docs/vault.enc` po założeniu skarbca), najpierw je dołącz – **nie używaj `push --force`**, bo skasujesz skarbiec:
```bash
git fetch origin
git merge origin/main --allow-unrelated-histories -X ours -m "połączenie z GitHubem"
git push -u origin main
```
Bot codziennie zapisuje dane do repozytorium, więc przed każdym kolejnym `git push` zrób `git pull --rebase`.

### 2. Strona (GitHub Pages)
**Settings → Pages → Build and deployment:** Source: *Deploy from a branch*, Branch: `main`, folder: `/docs` → **Save**.
Po 1–2 minutach strona będzie pod adresem `https://TWÓJ-LOGIN.github.io/skarbiec/`.

### 3. Token (żeby strona mogła zapisywać zmiany)
1. Kliknij swój awatar → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Nazwa: `skarbiec`. Wygaśnięcie: najdłuższe dostępne (zapisz w kalendarzu, kiedy je odnowić).
3. **Repository access:** *Only select repositories* → `skarbiec` **i** `skarbiec-foto`.
4. **Permissions → Repository permissions:** **Contents: Read and write** i **Actions: Read and write**.
5. **Generate token** i skopiuj go (zaczyna się od `github_pat_`). Token działa tylko na te dwa repozytoria.
   Masz już token tylko do `skarbiec`? Edytuj go (**Edit** przy tokenie) i dopisz `skarbiec-foto` – nie trzeba nowego.

### 4. Discord
Na swoim serwerze: **ustawienia kanału → Integracje → Webhooki → Nowy webhook → Kopiuj URL webhooka**.

### 5. Załóż skarbiec
1. Otwórz `https://TWÓJ-LOGIN.github.io/skarbiec/`.
2. Wpisz token i wymyśl **mocne hasło** (min. 10 znaków, najlepiej 3–4 losowe słowa). Pliki są publicznie dostępne w zaszyfrowanej postaci, więc słabe hasło dałoby się złamać.
3. Na GitHubie: **Settings → Secrets and variables → Actions → New repository secret** i dodaj dwa sekrety:
   - `SKARBIEC_PASSWORD` = to samo hasło,
   - `DISCORD_WEBHOOK` = URL webhooka.

### 6. Pierwsze uruchomienie
1. Zakładka **Actions** → jeśli trzeba, kliknij zgodę na uruchamianie workflowów.
2. **Skarbiec bot → Run workflow**. Po ok. 2 minutach strona ma katalog wszystkich produktów Pokémon.
3. Na stronie: **Ustawienia → Wyślij test na Discord**.

Od teraz bot działa sam codziennie rano (i zapasowo po południu).

### 7. Skaner kart (opcjonalnie, ok. 5 minut)
1. Załóż konto na **console.anthropic.com** → **Billing**: doładuj np. 5 $ (starczy na kilka tysięcy zdjęć) i ustaw **limit miesięczny** (Limits), np. 5 $.
2. **Settings → API keys → Create key**, skopiuj klucz (`sk-ant-…`).
3. Na stronie: **Ustawienia → Skaner zdjęć** → wklej klucz, sprawdź nazwę repozytorium zdjęć (`login/skarbiec-foto`) → **Zapisz i sprawdź**. Obie pozycje powinny mieć ✓.

Klucz zostaje tylko w tej przeglądarce (jak token GitHub). Na telefonie wklej go raz, w Ustawieniach na telefonie.

### 8. Ceny EN/NM (opcjonalnie, 2 minuty)
Publiczny cennik Cardmarketu ma tylko ceny ze wszystkich języków. Prawdziwe najtańsze oferty **po angielsku, NM, od sprzedawców wysyłających do Polski** pobiera skrypt Tampermonkey z twojej przeglądarki (twoja sesja Cardmarketu):
1. Otwórz `https://TWÓJ-LOGIN.github.io/skarbiec_pokemon/skarbiec_en.user.js` → Tampermonkey pokaże okno → **Zainstaluj** (aktualizacje pobierze sam).
   - W Chrome Tampermonkey musi mieć włączone uruchamianie skryptów: `chrome://extensions` → Tampermonkey → **Szczegóły** → **Zezwalaj na skrypty użytkownika** (w starszych wersjach: **Tryb dewelopera**).
2. Bądź zalogowany na Cardmarket w tej przeglądarce.
3. W Skarbcu: **Watchlisty → 🔄 Uaktualnij ceny EN/NM**. Otworzy się na chwilę karta Cardmarketu (ok. 3 s na kartę) i zamknie się sama; postęp widać też pod przyciskiem w Skarbcu. Jeśli przeglądarka zablokuje nową kartę, zezwól na wyskakujące okna dla strony Skarbca.
4. Ceny odświeżają się też same przy otwarciu Skarbca albo Cardmarketu, jeśli mają ponad 20 godzin. Wykres watchlisty pokazuje sumę EN/NM w czasie.

## Jak używać
- **Watchlisty:** import z Tampermonkey (tryb `#track` → przycisk 🤖) albo dodawanie z wyszukiwarki.
  - Próg okazji dla całej listy: np. SIR-y poniżej 1500 €.
  - Cena „kup poniżej” dla pojedynczej pozycji.
- **Portfel:** wpisz wszystko, co już masz – cenę zakupu (PLN lub EUR) i datę. Strona liczy:
  - wartość i zysk,
  - datę, od której sprzedaż prywatna nie wymaga PIT (pół roku od końca miesiąca zakupu).
  Gdy coś sprzedasz, kliknij **Sprzedaj**, a zysk trafi do „zrealizowanego”.
- **Skaner:** **📷 Zrób zdjęcie** (telefon) albo **🖼️ Wybierz zdjęcia** (wiele naraz).
  - Najtaniej wychodzi strona segregatora 3×3: 9 kart to jedno zapytanie.
  - Claude Haiku 5.5 odczytuje nazwę i numer karty, a TCGdex dopasowuje kartę z Cardmarketu. Koszt to ok. 0,1 grosza za zdjęcie i widzisz go na bieżąco.
  - Pewne trafienia są zaznaczone. Pozycje z „sprawdź” albo z kilkoma wariantami wybierasz z listy. Wpisz koszt, jeśli go znasz, i kliknij **Dodaj do portfela**.
  - Każde zdjęcie zapisuje się w prywatnym `skarbiec-foto` (WebP, ok. 150 KB). W portfelu przycisk 📷 pokazuje zdjęcie danej karty.
  - Suma „rozpoznane karty warte razem” to szybka wycena lotu: sfotografuj lot z FB/OLX, zanim złożysz ofertę.
- **Rynek:** wyszukiwarka wszystkich kart i sealed, największe wzrosty i spadki względem średniej z 30 dni, historia z dziennych zrzutów (produkty od 10 €).
- **Alerty na Discord:**
  - 🔥 lista poniżej progu,
  - 🎯 pozycja poniżej twojej ceny,
  - 💸 pozycja ≥ 20% poniżej szczytu z 90 dni,
  - 📉 lista −10% w tydzień,
  - 🔎 pozycja −25% w dzień,
  - 💰 zysk w portfelu +50/100/200/400%,
  - 🧾 pozycja, którą od dziś można sprzedać bez PIT,
  - 📊 podsumowanie tygodnia.
  Progi zmienisz w Ustawieniach.

## Dobrze wiedzieć
- **Ceny to Price Trend Cardmarketu**, czyli rynkowa cena ze sprzedaży we wszystkich językach i stanach. Do oceny trendu i wartości portfela to dobra miara. Konkretne oferty sprawdzasz przed zakupem sam albo skryptem Tampermonkey.
- **Historia pozycji zaczyna się w dniu dodania** – bot nie zna cen sprzed instalacji. Dzienne zrzuty rynku też zaczynają się od pierwszego uruchomienia.
- **Telefon:** strona działa w przeglądarce. W Chrome: menu → „Dodaj do ekranu głównego”.
- **Zapamiętane hasło** zaznaczaj tylko na swoich urządzeniach. „Zapomnij to urządzenie” w Ustawieniach usuwa hasło i token z przeglądarki.
- **Kopia zapasowa:** Ustawienia → Pobierz kopię (zwykły JSON z listami i portfelem).
- **Wyłączenie bota przez GitHub:** w publicznym repozytorium GitHub wyłącza zaplanowane uruchomienia po 60 dniach bez aktywności. Codzienne zapisy bota powinny temu zapobiegać. Gdyby jednak przyszedł mail o wyłączeniu, wystarczy kliknąć **Enable workflow**.
- **Zgubione hasło:** danych nie da się odzyskać. Trzymaj kopię zapasową.
