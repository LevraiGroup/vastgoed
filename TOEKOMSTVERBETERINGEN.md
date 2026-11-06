# Toekomstverbeteringen — Pandenselectiesysteem Levrai

Geparkeerde uitbreidingen die bewust (nog) niet in het actieve model zitten. Elk item
bevat genoeg detail om het later zonder heronderzoek te bouwen.

---

## 1. Leegstand via KVK Handelsregister  *(getest, werkt — wacht op productiesleutel)*

**Idee:** een commercieel pand (winkel/kantoor/bedrijf) zónder actieve KVK-vestiging op
het adres is een sterk leegstand-signaal. Vult precies het gat dat BAG laat vallen: BAG
registreert leegstand nauwelijks (2 panden in heel Delft), terwijl KVK de economische
leegstand van winkels/kantoren zichtbaar maakt.

**Voorgestelde score:** `leegstands_of_mutatiesignaal: 4` (was onderdeel van budget; bij
heractivering schaal_max met +4 ophogen).

### Resultaat van de testrun (augustus 2026)
De koppeling is end-to-end getest tegen de publieke KVK-testomgeving:

| | Uitkomst |
|---|---|
| Commerciële panden in Delft | 605 |
| KVK-bevragingen uitgevoerd | 605 / 605 |
| Vestiging gevonden | 0 |
| "Geen vestiging" (leegstand-vlag) | 605 — **allemaal fictief** |

De testdatabase bevat uitsluitend fictieve bedrijven op fictieve postcodes; elke Delftse
postcode (26xx) gaf HTTP 404. Conclusie: **de koppeling werkt bewezen** (605 live calls),
maar de testmodus kan geen echte leegstand meten. De les zit in de **reikwijdte**: KVK
neemt 605 panden onder de loep vs 2 bij BAG (~300× breder).

### Geverifieerd API-contract
- Zoeken v2: `GET {basis}/zoeken?postcode=&huisnummer=`
- Header: `apikey: <sleutel>`
- Antwoord: `{ totaal, resultaten:[ { kvkNummer, naam, adres:{binnenlandsAdres:{...}}, type } ] }`
- Test: `https://api.kvk.nl/test/api/v2` + de publieke testsleutel van het KVK-ontwikkelaarsportaal (https://developers.kvk.nl) (gratis, fictieve data)
- Productie: `https://api.kvk.nl/api/v2` — **EUR 6,40/mnd per key + EUR 0,02/query**

### Wat nodig is om te activeren
1. Productiesleutel via https://developers.kvk.nl.
2. Module `bronnen/kvk.py` herstellen (git-historie / onderstaand patroon), toevoegen aan
   `bronnen/MODULES`, en het signaal `_sig_kvk` terugzetten in `_KWALIFICATIE_SIGNALEN`
   in `selectie.py`.
3. Signaallogica: `commercieel and kvk_vestigingen == 0` → +4 ("geen actieve vestiging").
4. Kostenrem: `alleen_commercieel: true`, `max_bevragingen` als plafond. 605 commerciële
   panden × EUR 0,02 ≈ EUR 12 per volledige Delft-run.

---

## 2. Verkoophistorie via Kadaster Koopsom  *(betaald — bewust uitgesteld)*

**Idee:** "lang niet verkocht" (> 10 jaar) als signaal voor langbezit / hogere
verkoopkans. **Enige bron** is het Kadaster; er is geen gratis alternatief.

- Koopsom API via Mijn Kadaster (Kadata), **± EUR 0,45 per adres**. Alleen de laatste
  transactie**datum** is nodig (de prijs bewust genegeerd).
- Kostenrem bij bouw: alleen werklijst-kandidaten (score ≥ drempel), hard plafond
  `max_bevragingen`. 500 bevragingen ≈ EUR 225.
- Exact endpoint-pad staat achter Mijn Kadaster en moet bij afname worden bevestigd.

Uitgezet omdat de opdrachtgever de Kadaster-prijs/-kosten wil vermijden.

---

## 3. Energielabel bulk i.p.v. per-adres  *(gratis, kleine optimalisatie)*

De actieve module `bronnen/energielabel.py` werkt per adres via de EP-online v5 API. Voor
grote steden (Rotterdam, Amsterdam) is het maandbestand efficiënter: één download i.p.v.
tienduizenden calls. Zet `bronnen.energielabel.bulk_csv` naar het CSV-pad. Kolomnamen van
het bestand bij eerste gebruik verifiëren (de loader detecteert flexibel).

---

## 4. Dedup-register + maandelijkse mutatiedetectie  *(briefing sectie 7)*

- Register van eerder behandelde/geselecteerde panden, zodat maandelijks alleen **nieuwe**
  kansrijke panden bovenkomen. Datastructuur ondersteunt dit al via de velden
  `eerder_geselecteerd` en `laatst_beoordeeld`.
- Mutatiedetectie: vergelijk de nieuwe maand-WFS met de vorige en signaleer
  statuswijzigingen (bv. "in gebruik" → "buiten gebruik" = verse leegstand).

---

## 5. Uitbreiding naar meer gemeenten

Den Haag en Rotterdam toevoegen in `config.yaml` onder `gebieden`. De
postcode-partitionering in `ingest.py` schaalt mee; let op het WFS-paginatieplafond
(51.000) — grotere steden vereisen fijnere partities.
