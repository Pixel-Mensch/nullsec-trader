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
```

Wenn `--cargo-m3` oder `--budget-isk` fehlen, fragt die CLI interaktiv nach Cargo und Budget.

### Replay

- Replay wird ueber `replay.enabled` und `replay.snapshot_path` in der Config gesteuert.
- `NULLSEC_REPLAY_ENABLED=1` erzwingt Replay, `NULLSEC_REPLAY_ENABLED=0` erzwingt Live.
- Live-Runs koennen nach dem Fetch ein Replay-Snapshot schreiben, wenn `replay.write_snapshot_after_fetch=true` gesetzt ist.
- Vorhandene Replay-Fixtures fuer Regressionen liegen unter [`tests/fixtures`](./tests/fixtures).

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
- [`fees.py`](./fees.py), [`fee_engine.py`](./fee_engine.py): Gebuehrenmodell
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
