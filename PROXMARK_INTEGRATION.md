# Intégration Proxmark3 - ZeroRange

> **Historical note (v1.2):** the `*_handler.py` challenge files described below were
> replaced by scenario stages in `challenges/<module>/stages.py`; the hardware drivers
> (`proxmark_handler.py`, `ibutton_usb_reader.py`) are unchanged.
> See [docs/SCENARIO_GUIDE.md](docs/SCENARIO_GUIDE.md).


## Résumé

Intégration complète du support Proxmark3 pour les challenges NFC et RFID 125kHz dans ZeroRange.

## Fichiers créés

### 1. `proxmark_handler.py`
Handler principal pour communiquer avec le Proxmark3 via subprocess.

**Fonctionnalités:**
- Détection automatique du Proxmark
- Mode simulation si Proxmark non disponible
- Commandes NFC (ISO14443A):
  - `nfc_scan()` - Scanner carte NFC
  - `nfc_read_block()` - Lire un bloc MIFARE
  - `nfc_dump_mifare()` - Dump complet MIFARE Classic
- Commandes RFID 125kHz (LF):
  - `rfid_scan()` - Scanner tag RFID
  - `rfid_read_em410x()` - Lire EM410x
  - `rfid_clone_to_t5577()` - Cloner vers T5577
  - `rfid_simulate_em410x()` - Simuler EM410x

### 2. `nfc_handler.py`
Gestionnaire des 3 challenges NFC.

**Challenges:**
1. **Detect & Read** (10pts) - Détecter et lire une carte NFC (60s timeout)
2. **Clone Card** (10pts) - Lire et dumper une carte NFC en 2 étapes (45s par étape)
3. **MIFARE Attack** (10pts) - Attaque nested sur MIFARE Classic (60s)

**Fonctionnalités:**
- Countdown visuel sur LCD
- Bouton Skip (BTN5) pour abandonner
- Retry/Back sur échec
- Support multi-types: MIFARE Classic, Ultralight, NTAG, DESFire

### 3. `rfid_handler.py`
Gestionnaire des 3 challenges RFID 125kHz.

**Challenges:**
1. **Detect Tag** (10pts) - Détecter un tag RFID (60s timeout)
2. **Clone to T5577** (10pts) - Lire puis cloner vers T5577 (45s par étape)
3. **Simulate EM410x** (10pts) - Simuler un tag EM410x (60s)

**Fonctionnalités:**
- Support EM410x, HID Prox, Indala
- Clonage vers T5577
- Simulation EM410x
- Retry/Back sur échec

## Fichiers modifiés

### 1. `zerorange.py`
**Modifications:**
- Ajout des imports: `ProxmarkHandler`, `NFCHandler`, `RFIDHandler`
- Ajout des attributs: `self.proxmark`, `self.nfc`, `self.rfid`
- Initialisation dans `init_system()` avec gestion d'erreur gracieuse
- Menus NFC et RFID fonctionnels (au lieu de "Soon!")
- Ajout de `run_nfc_challenge(challenge_num)` - Execute challenges NFC
- Ajout de `run_rfid_challenge(challenge_num)` - Execute challenges RFID
- Score total passé de 40 à 90 points

### 2. `database.py`
**Modifications:**
- Expansion de 3 à 9 challenges:
  - Challenges 1-3: iButton (10pts chacun)
  - Challenges 4-6: NFC (10pts chacun)
  - Challenges 7-9: RFID (10pts chacun)
- Migration automatique des bases existantes
- Mise à jour de `init_db()` pour ajouter les nouveaux challenges

### 3. `ibutton_handler.py`
**Modifications:**
- Uniformisation à 10 points par challenge (au lieu de 10-15-15)
- Suppression des totaux en dur dans les messages de succès
- Cohérence avec le nouveau système de scoring

### 4. `nfc_handler.py` & `rfid_handler.py`
**Modifications:**
- Suppression des totaux en dur ("/30") dans les messages de succès
- Affichage simplifié: juste "+10pts"

## Documentation

### `docs/PROXMARK_SETUP.md`
Guide complet d'installation et configuration du Proxmark3:
- Installation des dépendances
- Compilation du client
- Configuration USB
- Tests de fonctionnalité
- Dépannage

## Architecture

```
ZeroRange (zerorange.py)
├── ProxmarkHandler (proxmark_handler.py)
│   ├── Commandes NFC (hf 14a)
│   └── Commandes RFID (lf em/hid/indala)
├── NFCHandler (nfc_handler.py)
│   ├── Challenge 1: Detect & Read
│   ├── Challenge 2: Clone Card
│   └── Challenge 3: MIFARE Attack
└── RFIDHandler (rfid_handler.py)
    ├── Challenge 1: Detect Tag
    ├── Challenge 2: Clone to T5577
    └── Challenge 3: Simulate EM410x
```

## Système de scoring

**Total: 90 points**

| Module   | Challenge 1 | Challenge 2 | Challenge 3 | Total Module |
|----------|-------------|-------------|-------------|--------------|
| iButton  | 10 pts      | 10 pts      | 10 pts      | 30 pts       |
| NFC      | 10 pts      | 10 pts      | 10 pts      | 30 pts       |
| RFID     | 10 pts      | 10 pts      | 10 pts      | 30 pts       |

## Base de données

**Structure challenges:**
```
ID | Module  | Name              | Description           | Points
---+---------+-------------------+-----------------------+--------
1  | ibutton | Touch & Read      | Detect any iButton    | 10
2  | ibutton | Clone iButton     | Read then emulate     | 10
3  | ibutton | Emulate Specific  | Create custom ID      | 10
4  | nfc     | Detect & Read     | Detect any NFC card   | 10
5  | nfc     | Clone Card        | Read and dump NFC     | 10
6  | nfc     | MIFARE Attack     | Break MIFARE Classic  | 10
7  | rfid    | Detect Tag        | Detect RFID 125kHz    | 10
8  | rfid    | Clone to T5577    | Clone tag to T5577    | 10
9  | rfid    | Simulate EM410x   | Simulate EM410x tag   | 10
```

## Déploiement

### Fichiers à uploader sur Raspberry Pi:
1. `proxmark_handler.py` - Nouveau
2. `nfc_handler.py` - Nouveau
3. `rfid_handler.py` - Nouveau
4. `zerorange.py` - Modifié
5. `database.py` - Modifié
6. `ibutton_handler.py` - Modifié
7. `docs/PROXMARK_SETUP.md` - Nouveau

### Commandes d'upload (quand Raspberry Pi démarré):
```bash
# Use deploy_to_pi.sh script or manual scp:
scp proxmark_handler.py user@RASPBERRY_IP:/home/user/ZeroRange/
scp nfc_handler.py user@RASPBERRY_IP:/home/user/ZeroRange/
scp rfid_handler.py user@RASPBERRY_IP:/home/user/ZeroRange/
scp zerorange.py user@RASPBERRY_IP:/home/user/ZeroRange/
scp database.py user@RASPBERRY_IP:/home/user/ZeroRange/
scp ibutton_handler.py user@RASPBERRY_IP:/home/user/ZeroRange/
scp -r docs/ user@RASPBERRY_IP:/home/user/ZeroRange/
```

## Tests

### Test unitaire Proxmark (sans hardware):
```bash
python3 proxmark_handler.py
```

### Test NFC (avec Proxmark):
```bash
python3 nfc_handler.py
```

### Test RFID (avec Proxmark):
```bash
python3 rfid_handler.py
```

### Test complet:
```bash
sudo python3 zerorange.py
```

## Notes importantes

1. **Mode simulation**: Si Proxmark non détecté, le système fonctionne en mode simulation (logs seulement)
2. **Permissions**: L'utilisateur doit être dans le groupe `dialout` pour accéder au Proxmark
3. **Port USB**: Par défaut `/dev/ttyACM0`, configurable dans le code
4. **Migration DB**: La base de données est automatiquement migrée de 3 à 9 challenges au premier lancement

## Prochaines étapes

1. Installer Proxmark3 sur Raspberry Pi (voir `docs/PROXMARK_SETUP.md`)
2. Uploader les fichiers modifiés
3. Tester chaque module individuellement
4. Lancer le système complet
5. Valider les 9 challenges

## Compatibilité

- **Proxmark3 RDV4**: Recommandé
- **Proxmark3 Easy**: Compatible
- **Proxmark3 Generic**: Compatible avec limitations possibles
- **OS**: Raspberry Pi OS (Debian-based)
- **Python**: 3.7+
