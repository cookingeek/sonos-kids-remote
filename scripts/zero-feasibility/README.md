# Machbarkeitstest: Apple Music auf dem Pi Zero 2 W

Prüft mit Zahlen, ob ein **Raspberry Pi Zero 2 W (512 MB RAM)** Apple Music über
den Web-Player in einem Headless-Chrome dauerhaft abspielen kann – über
Bluetooth-Kopfhörer oder AirPlay.

Am Ende steht **PASST** oder **PASST NICHT**, mit Messwerten.

## Was getestet wird

| Kriterium | Grenze | Warum |
|---|---|---|
| Chrome-Speicher (resident) | ≤ 300 MB | Budget nach Abzug von System, PipeWire, eigenem Dienst |
| Freier Systemspeicher | dauerhaft ≥ 50 MB | sonst wird das System träge oder bricht ein |
| OOM-Kills | 0 | Prozessabbrüche wegen Speichermangel |
| Absturz der Chrome-Seite | nein | |
| Stillstand der Wiedergabe | ≤ 30 s gesamt | Position läuft nicht weiter (Puffer, CPU, Netz) |
| Dauer | 30 min | Speicher wächst bei lange laufenden Web-Apps |

Zusätzlich protokolliert: Ladezeit bis MusicKit bereit, Zeit bis zum ersten Ton,
CPU-Last von Chrome, Swap-/zram-Nutzung, PipeWire-Aussetzer (xruns, soweit messbar).

„Chrome-Speicher (resident)“ ist der Teil, der zwingend im RAM liegen muss
(`Pss_Anon + Pss_Shmem` aller Chrome-Prozesse). Programmcode, den der Kernel bei
Bedarf von der Karte nachlädt, wird getrennt als „verdrängbar“ ausgewiesen.

## Voraussetzungen

- Raspberry Pi Zero 2 W mit **Raspberry Pi OS Lite 64-Bit**, per SSH erreichbar
- Apple-Music-Abo
- Bluetooth-Kopfhörer und/oder AirPlay-Lautsprecher im selben Netz

## Ablauf

### 1. Einrichten (einmalig)

```bash
git clone <dieses-repo> && cd sonos-kids-remote/scripts/zero-feasibility
sudo ./setup.sh
sudo reboot
```

`setup.sh` installiert Chromium mit Widevine (auf Pi OS) bzw. Google Chrome,
PipeWire und BlueZ, ersetzt die Swap-Datei auf der SD-Karte durch zram und gibt
den Grafikspeicher frei (`gpu_mem=16`, KMS-Treiber aus). Letzteres schaltet die
HDMI-Ausgabe ab. Mit `--no-tune-boot` überspringen; Rückgängig: Sicherung
`config.txt.zero-feasibility.bak` zurückkopieren.

### 2. Kopfhörer koppeln (für den Bluetooth-Test)

```bash
bluetoothctl
  power on
  scan on            # Kopfhörer in den Kopplungsmodus versetzen, Adresse abwarten
  pair  AA:BB:CC:DD:EE:FF
  trust AA:BB:CC:DD:EE:FF
  connect AA:BB:CC:DD:EE:FF
  quit
pactl list short sinks   # ein Eintrag mit "bluez" muss erscheinen
```

### 3. Bei Apple anmelden (Live-Ansicht im eigenen Browser)

Auf dem Laptop einen SSH-Tunnel öffnen – so laufen die Eingaben verschlüsselt:

```bash
ssh -L 8080:127.0.0.1:8080 pi@<zero>.local
```

Im selben SSH-Fenster:

```bash
./feasibility.py login
```

Dann auf dem Laptop **http://localhost:8080** öffnen. Dort erscheint die echte
Apple-Music-Seite vom Pi. Auf „Anmelden“ tippen, Apple-ID, Passwort und
Bestätigungscode eingeben. Für Passwort-Manager gibt es oben das Feld
„Text einfügen“. Sobald „Angemeldet ✓“ erscheint, beendet sich das Programm.
Die Sitzung liegt in `~/.local/share/zero-feasibility/profile`.

Das Skript protokolliert keine Eingaben.

### 4. Kurztest (2 Minuten)

```bash
./feasibility.py check
```

Zeigt: Ladezeit, ob Widevine verfügbar ist, ob die Anmeldung erhalten blieb,
Speicher im Leerlauf.

### 5. Dauertest (30 Minuten)

Album-Link aus Apple Music kopieren („Teilen → Link kopieren“), dann:

```bash
# Bluetooth-Kopfhörer
./feasibility.py run --album "https://music.apple.com/de/album/…/1234567890" --sink bluez

# AirPlay-Lautsprecher (z. B. IKEA Symfonisk)
./feasibility.py run --album "…" --airplay
```

Während des Tests hinhören und **hörbare Aussetzer notieren** – die misst das
Skript nicht vollständig.

### 6. Varianten vergleichen (optional)

```bash
./feasibility.py run --album "…" --sink bluez --profile balanced   # mit Sandbox, voller JIT
./feasibility.py run --album "…" --sink bluez --memory-max 320M    # hartes Limit für Chrome
./feasibility.py run --album "…" --sink bluez --no-block-images    # Cover nicht blockieren
```

| Profil | Inhalt |
|---|---|
| `lean` (Standard) | alles Sparsame: ein Render-Prozess, keine Site-Isolation, kein GPU-Prozess, Low-End-Modus, **ohne Sandbox**, V8 ohne Optimierungs-JIT |
| `balanced` | wie `lean`, aber mit Sandbox und vollem JIT (mehr Speicher, weniger CPU) |
| `default` | Chrome-Standard, nur headless (Vergleichswert) |

`lean` schaltet die Sandbox ab. Vertretbar, weil der Browser nur
`music.apple.com` lädt – für den späteren Dauerbetrieb aber eine bewusste
Entscheidung.

## Ergebnisse

Jeder Lauf schreibt nach `~/.local/share/zero-feasibility/results/<Zeitstempel>/`:

- `summary.json` – Urteil, alle Grenzwerte, Kennzahlen
- `samples.csv` – Messwerte alle 10 s

Diese beiden Dateien plus deine Notizen zu hörbaren Aussetzern reichen für die
Entscheidung.

## Bekannte Grenzen des Tests

- Ob Apples Login direkt in der Seite oder in einem Popup erscheint, ist
  ungeprüft; das Skript folgt Popups automatisch.
- `Widevine: ok` heißt: Der Browser meldet ein Widevine-Modul. Ob Apple die
  Lizenz ausliefert, zeigt erst der Dauertest (Wiedergabe startet / startet nicht).
- PipeWire-Aussetzer werden über `pw-top` gezählt; bei älteren PipeWire-Versionen
  steht dort „nicht messbar“.
- Getestet wurde die Mechanik (Login per Live-Ansicht, Messung, Urteil) gegen eine
  nachgebaute MusicKit-Seite. Auf dem echten Pi und gegen `music.apple.com` lief
  das Skript noch nicht.
