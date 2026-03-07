# Nullsec Trader Tool

`Nullsec Trader Tool` ist ein Python-Werkzeug fuer EVE Online, das konkrete Nullsec-Handelsrouten bewertet und daraus ausfuehrbare Handelsplaene ableitet. Es soll nicht nur Spreads anzeigen, sondern beantworten, ob ein Trade nach Gebuehren, Transport, Marktliquiditaet und realistischer Exit-Chance tatsaechlich nutzbar ist.

Der Schwerpunkt liegt auf konservativen Entscheidungen fuer echte Nutzung: realistisch erwartbarer Profit, belastbare Transportkosten, sinnvolle Positionsgroessen und klar lesbare Execution Plans. Architektur ist hier Mittel zum Zweck. Wenn ein Trade fachlich nicht belastbar ist, soll er lieber aussortiert oder als nicht handelbar markiert werden.

## Kernfunktionen

- Marktanalyse fuer konfigurierte Strukturen und Locations, inklusive Jita als eigener Location-Knoten (`jita_44`)
- Candidate-Erzeugung fuer `instant`, `fast_sell` und `planned_sell`
- Zentrales Gebuehrenmodell fuer Sales Tax, Broker Fees, SCC-Surcharge und optionales Relist-Budget
- Shipping- und Hauling-Kosten ueber konfigurierbare `shipping_lanes` und zusaetzliche `route_costs`
- Route Search mit risikoadjustiertem Ranking statt reinem Papier-Profit
- Portfolio-Bau unter Budget-, Cargo-, Liquidations- und Nachfragelimits
- Execution Plans, Route Leaderboard, CSV-Exporte und Candidate-Dumps
- Lokales Trade Journal fuer Soll/Ist-Abgleich von vorgeschlagenen und tatsaechlich ausgefuehrten Trades
- Optionaler persoenlicher Character Context via EVE SSO / ESI: Character-Identitaet, Skills, optionale Skill Queue, offene Orders und Wallet-Snapshots mit lokalem Cache/Fallback
- Wallet-/Journal-Reconciliation fuer persoenliche Handels-Historie mit Match-Confidence, offenen Positionen und ungematchter Wallet-Aktivitaet
- persoenliche Journal-Analytics mit Datenqualitaetsstufen, Sample-Size-Hinweisen und separater personaler Calibration-Basis ohne stillen Ranking-Eingriff
- Replay-Unterstuetzung fuer reproduzierbare Analysen und Regressionstests
- Snapshot-Only-Modus zum Bauen neuer Replay-Snapshots aus Live-Daten

## Fachliches Entscheidungsmodell

### Exit-Typen

- `instant`: Das Item wird am Ziel direkt gegen vorhandene Buy Orders verkauft. Das ist der schnellste und verlaesslichste Exit, hat aber oft die kleinere Marge.
- `planned`: Das Item wird am Ziel als Sell Order eingeplant. Der Zielpreis wird konservativ aus sichtbarer Konkurrenz, `queue_ahead_units`, Referenzpreis und Nachfrage hergeleitet.
- `speculative`: Das Item verlaesst sich auf einen gelisteten Exit, ohne die gleiche fachliche Belastbarkeit wie `planned_sell`. Im Output sollte das vorsichtiger gelesen werden als `instant`.

### Was `planned_sell` hier bedeutet

- Das Tool trennt bewusst zwischen theoretischem Vollverkauf und konservativem Erwartungswert.
- `gross_profit_if_full_sell` zeigt nur, was passieren wuerde, wenn die gesamte Position voll verkauft wird.
- `expected_units_sold_90d`, `expected_units_unsold_90d`, `expected_days_to_sell` und `expected_realized_profit_90d` bilden den konservativen 90-Tage-Erwartungswert ab.
- Sichtbare Sell-Orders auf oder unter dem Zielpreis, `queue_ahead_units`, Referenzpreis-Plausibilitaet und Markt-History druecken Preis, Menge und Confidence.
- Dead Markets werden absichtlich hart gefiltert. Wenig sichtbare Konkurrenz allein gilt nicht als guter Markt.
- Wenn nur schwache regionale History verfuegbar ist, sinken Confidence und Positionsgroesse. Das ist ein Hilfssignal, kein Beweis fuer echten Struktur-Absatz.

### Jita, Gebuehren und Shipping

- Jita ist als eigener Location-Knoten `jita_44` eingebunden und wird nicht wie eine Upwell-Structure behandelt.
- Jita-Daten werden bei Bedarf auch fuer `jita_split_price` und Shipping-Collateral-Berechnungen genutzt.
- Gebuehren laufen zentral ueber [`fees.py`](./fees.py) und [`fee_engine.py`](./fee_engine.py).
- Instant-Exits und gelistete Exits werden unterschiedlich bepreist. Gelistete Exits enthalten zusaetzlich Broker, SCC und optionales Relist-Budget.
- Shipping- und zusaetzliche Routenkosten werden vor dem finalen Ranking vom Profit abgezogen.
- Wenn fuer eine Route kein belastbares Transportmodell existiert, wird sie standardmaessig blockiert. Eine Zero-Cost-Ausnahme ist nur explizit ueber `route_search.allow_zero_transport_cost_for_routes` moeglich.

### Wichtiger Unterschied: Papierprofit vs. erwartbarer Profit

- Ein hoher `gross_profit_if_full_sell` ist kein Kaufsignal.
- Fuer Entscheidungen ist `expected_realized_profit_90d` wichtiger.
- Gerade in duennen Nullsec-Maerkten bleibt der sichtbare Spread nur dann brauchbar, wenn Exit, Nachfrage und Transport auch realistisch wirken.

## Nutzung / Start

### Voraussetzungen

- Python 3.10 oder neuer
- Abhaengigkeiten installieren:

```powershell
python -m pip install -r .\requirements.txt
```

- Fuer Live-Betrieb: gueltige ESI-Credentials und Zugriff auf die benoetigten Strukturen
- Fuer optionalen privaten Character Context: lokale EVE-SSO-App / ESI-App mit `client_id` und optional `client_secret`
- Lokale Secrets am besten ueber `config.local.json` oder Umgebungsvariablen setzen

Als Vorlage gibt es [`config.local.example.json`](./config.local.example.json).

### Echte Einstiegspunkte

Der produktive CLI-Pfad ist:

`run.bat` oder `run_trader.ps1` -> `main.py` -> `runtime_runner.run_cli()`

[`nullsectrader.py`](./nullsectrader.py) ist kein produktiver CLI-Startpfad. Die Datei dient nur als duenne Kompatibilitaets- und Import-Fassade fuer Tests und lokale Skripte.

### Empfohlene Starts

PowerShell-Wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode live
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode replay
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode live -CargoM3 15000 -BudgetISK 800000000
powershell -ExecutionPolicy Bypass -File .\run_trader.ps1 -Mode live -SnapshotOnly
```

Batch-Wrapper fuer den normalen Live-Start:

```bat
run.bat
```

Direkt ueber Python:

```powershell
python .\main.py --cargo-m3 10000 --budget-isk 500m
python .\main.py --snapshot-only
python .\main.py --snapshot-only --structures 1040804972352 1049588174021 --snapshot-out .\snapshot.json
python .\main.py auth login
python .\main.py auth status
python .\main.py character sync
python .\main.py character status
```

Wenn `--cargo-m3` oder `--budget-isk` fehlen, fragt die CLI interaktiv nach Cargo und Budget.

### Risk Profiles / Handelsmodi

Das Tool unterstuetzt konfigurierbare Risk Profiles, die echte Auswirkungen auf Candidate-Auswahl, Portfoliobau, Route-Ranking und Output haben.

#### Profil waehlen

Per CLI-Argument:

```powershell
python .\main.py --profile conservative --cargo-m3 10000 --budget-isk 500m
python .\main.py --profile aggressive
python .\main.py --profile instant_only
python .\main.py --profile low_maintenance
```

Per Umgebungsvariable (ueberschreibt CLI und Config):

```powershell
$env:NULLSEC_RISK_PROFILE = "high_liquidity"
python .\main.py
```

Per `config.local.json`:

```json
{
  "risk_profile": {
    "name": "balanced"
  }
}
```

Einzelne Parameter koennen im Config-Block ueberschrieben werden (werden auf das Basisprofil aufgesetzt):

```json
{
  "risk_profile": {
    "name": "balanced",
    "max_items": 25,
    "min_expected_profit_isk": 2000000
  }
}
```

#### Eingebaute Profile

| Profil | Beschreibung | planned_sell | Max Items | Max Tage |
|---|---|---|---|---|
| `conservative` | Nur liquide Instant-Exits, enge Confidence-Schwellen | blockiert | 20 | 14 |
| `balanced` | Standardverhalten, gemischte Exits (Standard-Profil) | erlaubt | 40 | 45 |
| `aggressive` | Maximaler Papierprofit, duenne Maerkte toleriert | erlaubt | 100 | 90 |
| `instant_only` | Kein planned_sell, nur Buy-Order-Exits | blockiert | 50 | 1 |
| `high_liquidity` | Exit-Qualitaet vor Marge, harte Strafe fuer tote Maerkte | erlaubt | 30 | 21 |
| `low_maintenance` | Wenige Items, klare Exits, minimales Repricing-Risiko | blockiert | 12 | 21 |

#### Was die Profile steuern

- **Candidate Filter**: `min_fill_probability`, `max_expected_days_to_sell`, `planned_min_liquidity_confidence`, `min_expected_profit_isk`, `min_profit_per_m3`
- **Portfolio**: `max_item_share_of_budget`, `max_items`, `max_liquidation_days_per_position`
- **planned_sell-Blockierung**: Profile wie `instant_only`, `conservative` und `low_maintenance` blockieren den planned_sell-Pfad vollstaendig
- **Route-Ranking**: Jedes Profil gewichtet `stale_market_penalty`, `speculative_penalty`, `concentration_penalty` und `capital_lock_risk` unterschiedlich
- **Output**: Das aktive Profil und seine Restriktionen erscheinen im Execution Plan Header

#### Beispiel: konservativ vs. aggressiv

Bei denselben Marktdaten:

- `conservative` laesst nur Kandidaten mit >= 70% Fill-Probability, max. 14 Tage Verkaufsdauer, min. 5m ISK konservativem Profit durch — und blockiert planned_sell.
- `aggressive` akzeptiert bereits 10% Fill-Probability, bis zu 90 Tage, keine ISK-Untergrenze und erlaubt speculative Exits.

Ergebnis: Bei duennen Maerkten zeigt `conservative` haeufig keinen Plan (korrekte Ablehnung), `aggressive` baut einen Plan aus schwaecheren Signalen.

### Replay

- Replay wird ueber `replay.enabled` und `replay.snapshot_path` in der Config gesteuert.
- `NULLSEC_REPLAY_ENABLED=1` erzwingt Replay, `NULLSEC_REPLAY_ENABLED=0` erzwingt Live.
- Live-Runs koennen nach dem Fetch ein Replay-Snapshot schreiben, wenn `replay.write_snapshot_after_fetch=true` gesetzt ist.
- Vorhandene Replay-Fixtures fuer Regressionen liegen unter [`tests/fixtures`](./tests/fixtures).

### Persoenlicher Character Context (optional)

Der Character Context ist absichtlich optional. Ohne SSO/ESI bleibt das Tool
voll benutzbar. Wenn er aktiviert wird, kann das Tool echte Charakterdaten
statt generischer Annahmen nutzen.

#### Was aktuell genutzt werden kann

- Character-Identitaet aus dem EVE SSO Access Token
- Skill-Snapshot fuer echte Fee-Skill-Levels (`Accounting`, `Broker Relations`,
  `Advanced Broker Relations`)
- optionale Skill Queue
- offene Character Market Orders als Exposure-Signal im Output
- Wallet Balance sowie Wallet Journal / Transactions als lokale Snapshots fuer
  persoenliche Handels-Historie, Reconciliation und Soll/Ist-Abgleich

#### Verifizierte offizielle SSO-/ESI-Pfade

Die aktuell im Code genutzten privaten SSO-/ESI-Pfade wurden vor der
Implementierung gegen die offiziellen EVE Entwicklerquellen verifiziert:

- SSO Metadata Discovery: `https://login.eveonline.com/.well-known/oauth-authorization-server`
- SSO Authorize: `https://login.eveonline.com/v2/oauth/authorize`
- SSO Token: `https://login.eveonline.com/v2/oauth/token`
- Character Skills: `/characters/{character_id}/skills/`
- Character Skill Queue: `/characters/{character_id}/skillqueue/`
- Character Orders: `/characters/{character_id}/orders/`
- Character Wallet Balance: `/characters/{character_id}/wallet/`
- Character Wallet Journal: `/characters/{character_id}/wallet/journal/`
- Character Wallet Transactions: `/characters/{character_id}/wallet/transactions/`

Verifizierte Scope-Namen:

- `esi-skills.read_skills.v1`
- `esi-skills.read_skillqueue.v1` (nur wenn Skill Queue genutzt werden soll)
- `esi-markets.read_character_orders.v1`
- `esi-wallet.read_character_wallet.v1`

#### Lokale Einrichtung

1. Lege `client_id` und nach Moeglichkeit `client_secret` lokal in
   [`config.local.example.json`](./config.local.example.json)-Manier ab oder
   setze sie per `ESI_CLIENT_ID` / `ESI_CLIENT_SECRET`.
2. Aktiviere in `config.local.json` den Block `character_context.enabled`.
3. Starte einmal lokal den Login:

```powershell
python .\main.py auth login
python .\main.py character sync
```

4. Danach kann ein normaler Run den Charakterkontext live oder aus Cache
   verwenden.

Beispiel fuer `config.local.json`:

```json
{
  "esi": {
    "client_id": "your_client_id_here",
    "client_secret": "your_client_secret_here"
  },
  "character_context": {
    "enabled": true,
    "include_skill_queue": false,
    "wallet_journal_max_pages": 2,
    "wallet_transactions_max_pages": 2,
    "wallet_warn_stale_after_sec": 21600
  }
}
```

#### Lokale Dateien / Cache

Die private Character-Integration schreibt keine Secrets ins Repo. Alle lokalen
Artefakte liegen unter dem ohnehin ignorierten `cache/`-Bereich:

- `cache/character_context/sso_token.json`
- `cache/character_context/sso_metadata.json`
- `cache/character_context/character_profile.json`

#### Fallback-Verhalten

- Wenn `character_context.enabled=false`, nutzt das Tool generische Defaults.
- Wenn Replay/Offline aktiv ist, wird kein harter Live-Call erzwungen; ein
  vorhandener Character-Cache kann genutzt werden.
- Wenn Login, Refresh oder Character-Sync fehlschlagen, faellt das Tool sauber
  auf Cache oder generische Defaults zurueck.
- Ohne Character-Kontext bleiben Live-Marktlogik, Replay und Offline-Nutzung
  weiter lauffaehig.

#### Wallet + Journal Reconciliation

Die persoenliche Handels-Historie ist jetzt als erste nutzbare Basis mit dem
lokalen Trade Journal verknuepft.

Verfuegbare Journal-Kommandos:

```powershell
python .\main.py journal reconcile
python .\main.py journal personal
python .\main.py journal unmatched
```

Was `journal reconcile` aktuell macht:

- laedt Character Context wie gewohnt live oder aus Cache
- nutzt `wallet_snapshot.transactions` und `wallet_snapshot.journal_entries`
- matched Wallet-Transactions gegen lokale Journal-Eintraege
- speichert Match-Ergebnis, Match-Confidence, Wallet-IDs, Fee-Match-Qualitaet,
  Snapshot-Freshness und Reconciliation-Status im lokalen Journal
- zeigt an, ob die Wallet-Historie frisch, alt, teilweise oder durch
  Page-Limits abgeschnitten ist

Was `journal personal` jetzt zusaetzlich zeigt:

- persoenliche Trefferquoten von vorgeschlagen -> gekauft und gekauft ->
  vollstaendig verkauft
- Anteil teilweise verkaufter Trades, unsicherer Matches und
  `wallet_unmatched`-Faelle
- realer vs erwarteter Profit und reale vs erwartete Sell-Dauer
- offene Positionen nach Altersklassen
- haeufige Problemklassen wie zu optimistische Profit-/Sell-Dauer-Annahmen,
  ungekaufte Vorschlaege, offene Langdreher und Order-Overlap
- Datenqualitaet, Sample Size und Guardrail-Hinweise fuer persoenliche Aussagen

Was `journal calibration` jetzt zusaetzlich zeigt:

- den bisherigen generischen Calibration-Report unveraendert
- plus eine separate `PERSONAL CALIBRATION BASIS`
- inklusive Quality-Level (`none`, `very_low`, `low`, `usable`, `good`),
  Sample Size, Warning-Hinweisen und `fallback to generic`-Policy

Aktuelle Matching-Signale:

- `character_id`, wenn im Plan/Journal vorhanden
- `type_id`
- Buy vs Sell Richtung
- Menge
- Preisnaehe zu geplantem oder bereits manuell erfasstem Preis
- Zeitfenster relativ zu Plan-/Trade-Zeit
- Markt-/Location-ID, wenn im Plan vorhanden
- verknuepfte Wallet-Journal-Refs fuer Gebuehren, wenn ESI diese liefert
- konservativer Zeitfenster-Fallback fuer Gebuehren nur dann, wenn genau ein
  plausibler Journal-Kandidat existiert

Wichtige Ehrlichkeit:

- Matching ist absichtlich nicht als perfekt modelliert
- persoenliche Analytics sind absichtlich nicht als globale Marktwahrheit
  modelliert
- unklare Faelle bleiben als `match_uncertain`
- nicht zuordenbare Wallet-Events bleiben in `journal unmatched` sichtbar
- Wallet-basierter Profit ist nur so gut wie die vorhandenen Wallet-Seiten und
  die verknuepfbaren Fee-/Tax-Refs
- Wallet-Reconciliation bleibt snapshot-basiert; alte Trades koennen trotz
  Paging-Verbesserungen unsicher bleiben, wenn die geladene Historie das echte
  Trade-Fenster nicht mehr abdeckt
- `wallet_journal_max_pages` und `wallet_transactions_max_pages` begrenzen
  bewusst den Abruf; wenn die Historie dadurch abgeschnitten wird, erscheint das
  als `truncated`-Hinweis im Output
- Fee-Matches werden jetzt als `exact`, `partial`, `fallback`, `uncertain` oder
  `unavailable` kenntlich gemacht, statt schwache Verknuepfungen still zu
  erzwingen
- Shipping und andere Kosten ausserhalb von Wallet-Daten bleiben separat
- keine oder schlechte persoenliche Historie fuehrt nicht zu einer stillen
  Bestrafung im Ranking; die persoenliche Basis bleibt aktuell rein
  analytisch/advisory
- geringe Sample Size oder schwache Datenqualitaet werden offen als
  `fallback to generic` bzw. `insufficient personal history` markiert

### Trade Journal

Normale Runs schreiben jetzt zusaetzlich eine maschinenlesbare Plan-Datei `trade_plan_<plan_id>.json`. Darin stehen `plan_id`, `route_id` und stabile `pick_id`s fuer die vorgeschlagenen Picks.

Neue Plan-Importe speichern zusaetzlich Matching-Hilfen wie Character-ID,
Markt-Location-IDs und vorhandene Open-Order-Warnhinweise mit ins Journal.

Damit kann ein Plan spaeter ins lokale Journal uebernommen werden:

```powershell
python .\main.py journal import-plan --plan-file .\trade_plan_plan_2026-03-07_12-00-00_ab12cd34.json
python .\main.py journal buy --entry-id pick_ab12cd34ef56 --qty 10 --price 1250000 --fees-paid 5m
python .\main.py journal sell --entry-id pick_ab12cd34ef56 --qty 10 --price 1550000 --fees-paid 6m
python .\main.py journal overview
python .\main.py journal open
python .\main.py journal closed
python .\main.py journal report
python .\main.py journal reconcile
python .\main.py journal personal
python .\main.py journal unmatched
```

### Wichtige Konfigurationsstellen

Die Konfiguration wird in dieser Reihenfolge geladen:

1. [`config.json`](./config.json)
2. `config.local.json` oder der Pfad aus `NULLSEC_LOCAL_CONFIG`
3. Environment-Overrides wie `ESI_CLIENT_ID`, `ESI_CLIENT_SECRET`, `NULLSEC_REPLAY_ENABLED`

Fuer den Betrieb relevant sind vor allem:

- `structures`, `locations`, `structure_regions`
- `fees`
- `shipping_lanes`, `route_costs`, `shipping_defaults`
- `filters_forward`, `filters_return`, `filters_planned_sell_forward`
- `planned_sell`, `reference_price`, `strict_mode`
- `portfolio`
- `route_search`, `route_profiles`, `route_chain`
- `replay`
- `character_context`

## Output verstehen

### Route Leaderboard

Wenn `route_search.enabled=true` ist, schreibt das Tool ein `route_leaderboard_<timestamp>.txt`.

Das Leaderboard zeigt nur handelbare Routen im Ranking. Nicht handelbare oder blockierte Routen stehen getrennt unter `PRUNED / NOT ACTIONABLE`.

Wichtige Felder:

- `Total Expected Realized Profit`: konservativer Erwartungswert nach Fees und Transport
- `Total Full Sell Profit`: theoretischer Vollverkaufswert
- `route_confidence`: zusammengefasste Route-Confidence
- `transport_confidence`: Transport-Belastbarkeit auf Route-Ebene
- `capital_lock_risk`: Risiko, wie lange Kapital in langsamen Exits festhaengt
- `Top3 Profit Share` und `Dominance Flag`: zeigen Konzentrationsrisiko auf wenige Items

Eine Route ist interessanter, wenn sie nicht nur hohen erwarteten Profit zeigt, sondern auch gute Confidence, normale Transport-Belastbarkeit, akzeptable Kapitalbindung und keine extreme Dominanz einzelner Items.

### Execution Plan

Im Route-Profile- und Chain-Pfad schreibt das Tool ein `execution_plan_<timestamp>.txt`.

Pro Route werden unter anderem ausgegeben:

- Buy-/Sell-Ort
- `Exit Type`
- `Total Expected Realized Profit`
- `Total Full Sell Profit`
- `route_confidence`
- `transport_confidence`
- `capital_lock_risk`
- Prune- oder Downgrade-Gruende
- optionaler Character-Context-Status (live/cache/default), Wallet-Balance und
  offene Order-Anzahl
- sichtbarer Order-Overlap-Hinweis, wenn vorgeschlagene Picks bereits mit
  eigenen Character-Orders kollidieren

Pro Pick werden unter anderem ausgegeben:

- `Expected Realized Profit`
- `Full Sell Profit`
- `Expected Units Sold`
- `Expected Units Unsold`
- `expected_days_to_sell`
- `liquidity_confidence`
- `transport_confidence`
- `overall_confidence`
- Fees, Taxes und Transportkosten
- bei Ueberlappung mit bestehenden Character-Orders: offenes Exposure fuer
  denselben Type
- staerkerer Warning-Tier fuer vorhandene Character-Sell-/Buy-Orders auf
  demselben Type

Auf Pick-Ebene kann `transport_confidence` als Modellstatus wie `normal`, `exception` oder `blocked` erscheinen. Auf Route-Ebene ist es ein zusammengefasster Confidence-Wert.

Wichtig beim Lesen:

- Verlasse dich zuerst auf `Expected Realized Profit`, nicht auf `Full Sell Profit`.
- `instant` ist normalerweise belastbarer als `planned` oder `speculative`.
- Lange `expected_days_to_sell`, schwache Confidence oder hohe Queue sprechen gegen den Trade.
- `[NOT ACTIONABLE]` bedeutet: nicht normal handeln, auch wenn irgendwo noch ein theoretischer Spread sichtbar ist.

### Weitere Dateien

Je nach Modus entstehen ausserdem:

- `roundtrip_plan_<timestamp>.txt` im einfachen Roundtrip-Pfad ohne Route-Profile
- `*_to_*_<timestamp>.csv` fuer Pick-Daten
- `*_top_candidates_<timestamp>.txt` fuer Kandidaten-Diagnostik und Rejection-Reasons
- `market_snapshot.json` als Laufzeit-Snapshot

Ein Null-Ergebnis ist nicht automatisch ein Fehler. Wenn keine Route oder keine Picks erscheinen, heisst das im Normalfall: Unter den aktuellen Filtern, Kosten und Marktbedingungen ist gerade nichts belastbar handelbar.

## Projektstruktur

### Produktiver Runtime-Pfad

- [`run_trader.ps1`](./run_trader.ps1): empfohlener Wrapper fuer Live, Replay und Snapshot-Only
- [`run.bat`](./run.bat): einfacher Live-Wrapper mit Defaults aus `config.json`
- [`main.py`](./main.py): echter CLI-Einstiegspunkt
- [`runtime_runner.py`](./runtime_runner.py): Orchestrierung fuer Live, Replay, Route-Profile, Chain und Reports

### Kernmodule

- [`candidate_engine.py`](./candidate_engine.py): Candidate-Erzeugung, `planned_sell`-Logik, Queue- und Nachfragebewertung
- [`character_profile.py`](./character_profile.py): lokales Character-Profil, Cache/Fallback, Fee-Skill-Mapping und Order-Exposure
- [`eve_sso.py`](./eve_sso.py): lokaler EVE SSO Login, Token-Refresh und Scope-/Identity-Ableitung
- [`eve_character_client.py`](./eve_character_client.py): private Character-ESI-Endpunkte fuer Skills, Orders und Wallet
- [`fees.py`](./fees.py), [`fee_engine.py`](./fee_engine.py): Gebuehrenmodell
- [`journal_models.py`](./journal_models.py), [`journal_store.py`](./journal_store.py), [`journal_reporting.py`](./journal_reporting.py), [`journal_cli.py`](./journal_cli.py): Plan-IDs, lokales SQLite-Journal, Soll/Ist-Auswertung und Journal-CLI
- [`journal_reconciliation.py`](./journal_reconciliation.py): Wallet-Transaction-/Wallet-Journal-Matching gegen lokale Journal-Eintraege mit Confidence und Unmatched-Tracking
- [`shipping.py`](./shipping.py): Shipping-Lanes, Transportkosten, Route-Blocking
- [`route_search.py`](./route_search.py): Route Search, Ranking und Route-Summary fuer das Leaderboard
- [`portfolio_builder.py`](./portfolio_builder.py): Portfolio-Bau unter Risiko-, Nachfrage-, Budget- und Cargo-Grenzen
- [`execution_plan.py`](./execution_plan.py): Route Leaderboard und menschenlesbare Execution Plans
- [`market_fetch.py`](./market_fetch.py): Order-Abruf fuer Structures und Locations
- [`market_normalization.py`](./market_normalization.py): Replay-Snapshot-Normalisierung
- [`startup_helpers.py`](./startup_helpers.py): Node-, Chain- und Label-Aufloesung
- [`models.py`](./models.py): zentrale Datenmodelle wie `TradeCandidate`

### Runtime-Helfer

- [`runtime_clients.py`](./runtime_clients.py): Live-ESI-Client und Replay-Client
- [`runtime_common.py`](./runtime_common.py): CLI-Parsing, Pfade und kleine Runtime-Helfer
- [`runtime_reports.py`](./runtime_reports.py): CSV-, Chain- und Summary-Writer

### Tests und Fixtures

- [`tests`](./tests): Split-Test-Suite
- [`tests/fixtures`](./tests/fixtures): Replay-Fixtures fuer Regressionen
- [`test_nullsectrader.py`](./test_nullsectrader.py): Kompatibilitaets-Launcher fuer `tests.run_all`

Eine kompakte technische Pfadbeschreibung steht zusaetzlich in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Einschraenkungen und Risiken

- Das Tool sieht nur verfuegbare Orderbuchdaten, ESI-History und konfigurierte Kostenmodelle. Politische Lage, Zugriffsrisiko, Docking-Probleme, Gate-Lage und tatsaechliche Hauler-Verfuegbarkeit sind nicht modelliert.
- Duenne Nullsec-Maerkte bleiben schwierig. Auch mit haerteren Filtern kann sichtbare Nachfrage schneller verschwinden, als die History vermuten laesst.
- `planned_sell` ist riskanter als `instant`, weil Queue und Konkurrenz sich nach dem Kauf veraendern koennen.
- Regionale History ist fuer Strukturmaerkte nur ein schwacher Proxy. Das Tool behandelt sie inzwischen vorsichtiger, aber nicht magisch praezise.
- Shipping-Modelle sind konfigurationsgetrieben. Wenn Lane-Parameter nicht zur realen Hauling-Situation passen, passt auch die Profitrechnung nicht.
- Gebuehren haengen von den in der Config hinterlegten Skills und Markttypen ab. Wenn dein Charakter oder Markt-Setup davon abweicht, driftet das Ergebnis.
- Open-Order-Exposure wird derzeit als Diagnose/Hinweis ausgegeben, nicht als
  harte Route-Strafe. Das ist bewusst konservativ und vermeidet Heuristik-Muell
  im Ranking.
- Wallet-Reconciliation ist snapshot-basiert. Bei kurzer Cache-Historie oder
  limitierter ESI-Paginierung koennen echte Trades als ungematcht oder unsicher
  erscheinen.
- Ein blockierter oder leerer Plan ist oft die richtige Antwort. Das Tool soll lieber nichts empfehlen als schlechte Trades normal ausgeben.

## Entwicklung und Tests

### Tests ausfuehren

```powershell
python -m pytest -q
python .\tests\run_all.py
python .\test_nullsectrader.py
python .\scripts\quality_check.py
```

### Was die Tests absichern

Die Test-Suite deckt unter anderem ab:

- Gebuehren- und Fee-Engine-Verhalten
- Shipping-Kosten, Contract-Splitting und blockierte Routen ohne Transportmodell
- Route Search, Ranking und nicht handelbare Routen
- Portfolio-Caps fuer Liquidationsdauer, Nachfrage und Konzentration
- Replay-Integration ueber `main.py`
- Architektur-Regeln wie den echten Runtime-Pfad und die duenne Rolle von `nullsectrader.py`

### Worauf bei Refactors zu achten ist

- Kernlogik darf nicht still ueber Wrapper oder Hilfsdateien dupliziert werden.
- Fachliche Source of Truth liegt in den Domain-Modulen: `candidate_engine.py`, `fees.py` / `fee_engine.py`, `shipping.py`, `route_search.py`, `portfolio_builder.py`, `execution_plan.py`.
- Aenderungen an Candidate-, Shipping- oder Portfolio-Logik sollten immer durch Replay-Faelle und Regressionstests abgesichert werden.
- [`nullsectrader.py`](./nullsectrader.py) sollte duenn bleiben. Business-Logik gehoert nicht dorthin.
