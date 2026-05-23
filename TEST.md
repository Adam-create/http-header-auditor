# TEST.md — Guide de test et de prise en main

Ce document couvre l'ensemble des vérifications à effectuer pour valider le bon fonctionnement de l'outil, comprendre son comportement sur des cas réels et limites, et interpréter ses sorties. Les tests sont organisés du plus simple au plus avancé.

---

## Sommaire

1. [Prérequis et vérification de l'environnement](#1-prérequis-et-vérification-de-lenvironnement)
2. [Tests CLI de base](#2-tests-cli-de-base)
3. [Tests du moteur de scoring (sans réseau)](#3-tests-du-moteur-de-scoring-sans-réseau)
4. [Tests réseau et comportements limites](#4-tests-réseau-et-comportements-limites)
5. [Tests de sortie HTML et JSON](#5-tests-de-sortie-html-et-json)
6. [Test de bout en bout complet](#6-test-de-bout-en-bout-complet)

---

## 1. Prérequis et vérification de l'environnement

Avant de lancer les tests, confirmer que l'environnement est opérationnel.

### 1.1 Version Python

```bash
python --version
```

**Attendu :** `Python 3.10.x` ou supérieur. Si la commande `python` pointe sur Python 3.14 sans pip (cas Windows avec plusieurs versions), utiliser le chemin complet :

```bash
# Windows — exemple si python pointe sur une version sans pip
C:\Users\<you>\AppData\Local\Programs\Python\Python311\python.exe --version
```

### 1.2 Dépendances installées

```bash
python -m pip show requests jinja2
```

**Attendu :** deux blocs avec `Name: requests` / `Name: Jinja2` et leurs versions. Si absent :

```bash
python -m pip install requests jinja2
```

### 1.3 Imports sans erreur

```bash
python -c "import requests, jinja2; print('OK')"
```

**Attendu :** `OK`

### 1.4 Structure des fichiers

Depuis le répertoire `http-header-auditor/`, vérifier la présence des fichiers :

```bash
# Linux / macOS
ls -1

# Windows PowerShell
Get-ChildItem | Select-Object Name
```

**Attendu :**

```
auditor.py
headers.py
report.py
targets.txt
output/
README.md
TEST.md
```

---

## 2. Tests CLI de base

Tous les tests de cette section s'exécutent depuis le répertoire `http-header-auditor/`.

---

### T-CLI-01 — Aide en ligne

```bash
python auditor.py --help
```

**Attendu :** affichage du message d'aide avec les options `-u`, `-t`, `--output`, `--json`, `--verbose`. Aucune erreur.

---

### T-CLI-02 — Argument obligatoire manquant

```bash
python auditor.py
```

**Attendu :** message d'erreur argparse du type :

```
error: one of the arguments -u/--url -t/--targets is required
```

Code de retour non nul (erreur). Cela valide que `-u` ou `-t` est bien obligatoire.

---

### T-CLI-03 — `-u` et `-t` simultanément (exclusion mutuelle)

```bash
python auditor.py -u example.com -t targets.txt
```

**Attendu :** erreur argparse :

```
error: argument -t/--targets: not allowed with argument -u/--url
```

---

### T-CLI-04 — Fichier de cibles inexistant

```bash
python auditor.py -t fichier_qui_nexiste_pas.txt
```

**Attendu :** message d'erreur de l'outil (pas un crash Python) :

```
ERROR     Targets file not found: fichier_qui_nexiste_pas.txt
```

Suivi d'un `SystemExit`. Pas de traceback.

---

### T-CLI-05 — Domaine nu (sans schéma)

```bash
python auditor.py -u github.com
```

**Attendu :** l'outil ajoute automatiquement `https://` et audite `https://github.com/`. La ligne de log doit mentionner `https://github.com/`.

**Ce que ça vérifie :** la fonction `_normalise_url()` dans `auditor.py`.

---

### T-CLI-06 — URL avec schéma complet

```bash
python auditor.py -u https://www.mozilla.org
```

**Attendu :** audit normal, pas de doublement du schéma, pas d'erreur.

---

### T-CLI-07 — Fichier de cibles standard

```bash
python auditor.py -t targets.txt
```

**Attendu :** 5 lignes de log `INFO` (une par domaine), puis le tableau de synthèse :

```
Domain                                         Grade  Score  Status
------------------------------------------------------------------------
www.google.com                                   F       20  HTTPS
www.github.com                                   C       73  HTTPS
...
```

Un fichier `output/report.html` est créé. Aucun fichier `results.json` (l'option `--json` n'a pas été passée).

---

### T-CLI-08 — Export JSON activé

```bash
python auditor.py -u cloudflare.com --json
```

**Attendu :** deux lignes de log à la fin :

```
INFO      HTML report written → .../output/report.html
INFO      JSON export written  → .../output/results.json
```

Vérifier que `output/results.json` existe et n'est pas vide :

```bash
# Linux / macOS
wc -c output/results.json

# Windows PowerShell
(Get-Item output\results.json).Length
```

**Attendu :** taille > 500 octets.

---

### T-CLI-09 — Répertoire de sortie personnalisé

```bash
python auditor.py -u example.com --output ./test_out
```

**Attendu :** le répertoire `test_out/` est créé automatiquement s'il n'existe pas, et contient `report.html`. L'outil ne plante pas si le répertoire existe déjà.

Nettoyage après le test :

```bash
# Linux / macOS
rm -rf test_out/

# Windows PowerShell
Remove-Item -Recurse test_out
```

---

### T-CLI-10 — Mode verbose

```bash
python auditor.py -u github.com --verbose
```

**Attendu :** des lignes `DEBUG` apparaissent en plus des lignes `INFO`, par exemple :

```
DEBUG     https://github.com/ — HEAD returned 200
```

Sans `--verbose`, seules les lignes `INFO` s'affichent.

---

### T-CLI-11 — Fichier de cibles avec commentaires et lignes vides

Créer un fichier temporaire :

```bash
# Linux / macOS
cat > /tmp/test_targets.txt << 'EOF'
# Ceci est un commentaire
https://www.github.com

# Un autre commentaire

https://owasp.org
EOF
python auditor.py -t /tmp/test_targets.txt
```

```powershell
# Windows PowerShell
@"
# Ceci est un commentaire
https://www.github.com

# Un autre commentaire

https://owasp.org
"@ | Out-File -Encoding utf8 "$env:TEMP\test_targets.txt"
python auditor.py -t "$env:TEMP\test_targets.txt"
```

**Attendu :** exactement 2 domaines audités (`[1/2]` et `[2/2]`). Les commentaires et lignes vides sont ignorés.

---

## 3. Tests du moteur de scoring (sans réseau)

Ces tests s'exécutent directement sur `headers.py` via Python inline — **aucune connexion réseau requise**. Ils valident la logique de scoring indépendamment du reste de l'outil.

Lancer chaque bloc avec :

```bash
python -c "<contenu du bloc>"
```

Ou copier tous les blocs dans un seul script et l'exécuter.

---

### T-SCORE-01 — Score parfait (tous les headers bien configurés)

```python
from headers import analyse_headers

headers = {
    "content-security-policy": "default-src 'self'",
    "strict-transport-security": "max-age=31536000; includeSubDomains; preload",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}
results, score, grade = analyse_headers(headers)
assert score == 100, f"Attendu 100, obtenu {score}"
assert grade == "A",  f"Attendu A,   obtenu {grade}"
print(f"T-SCORE-01  PASS  score={score}  grade={grade}")
```

**Attendu :** `T-SCORE-01  PASS  score=100  grade=A`

---

### T-SCORE-02 — Aucun header (score nul)

```python
from headers import analyse_headers

results, score, grade = analyse_headers({})
assert score == 0, f"Attendu 0, obtenu {score}"
assert grade == "F", f"Attendu F, obtenu {grade}"
for r in results:
    assert r.status.value == "absent", f"{r.name} devrait être absent"
print(f"T-SCORE-02  PASS  score={score}  grade={grade}")
```

**Attendu :** `T-SCORE-02  PASS  score=0  grade=F`

---

### T-SCORE-03 — CSP avec `unsafe-inline` (−10 pts)

```python
from headers import analyse_headers

headers = {
    "content-security-policy": "default-src 'self'; script-src 'unsafe-inline'",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=()",
}
results, score, grade = analyse_headers(headers)
csp = next(r for r in results if r.name == "content-security-policy")
assert csp.score_awarded == 15, f"CSP attendu 15, obtenu {csp.score_awarded}"
assert score == 90,             f"Score attendu 90, obtenu {score}"
print(f"T-SCORE-03  PASS  CSP={csp.score_awarded}/25  total={score}")
```

**Attendu :** `T-SCORE-03  PASS  CSP=15/25  total=90`

**Pourquoi :** 25 − 10 (`unsafe-inline`) = 15 pts pour CSP. Total = 100 − 10 = 90.

---

### T-SCORE-04 — CSP avec `unsafe-inline` ET `unsafe-eval` (−20 pts)

```python
from headers import analyse_headers

headers = {
    "content-security-policy": "default-src 'self'; script-src 'unsafe-inline' 'unsafe-eval'",
}
results, score, grade = analyse_headers(headers)
csp = next(r for r in results if r.name == "content-security-policy")
assert csp.score_awarded == 5, f"CSP attendu 5, obtenu {csp.score_awarded}"
print(f"T-SCORE-04  PASS  CSP={csp.score_awarded}/25  (unsafe-inline -10, unsafe-eval -10)")
```

**Attendu :** `T-SCORE-04  PASS  CSP=5/25`

---

### T-SCORE-05 — HSTS avec `max-age` trop court (−8 pts)

```python
from headers import analyse_headers

headers = {"strict-transport-security": "max-age=3600"}
results, score, grade = analyse_headers(headers)
hsts = next(r for r in results if r.name == "strict-transport-security")
# max-age trop court : -8 pts ; includeSubDomains absent : -5 pts → 20-13=7
assert hsts.score_awarded == 7, f"HSTS attendu 7, obtenu {hsts.score_awarded}"
print(f"T-SCORE-05  PASS  HSTS={hsts.score_awarded}/20  (max-age court -8, no includeSubDomains -5)")
```

**Attendu :** `T-SCORE-05  PASS  HSTS=7/20`

---

### T-SCORE-06 — HSTS correct mais sans `includeSubDomains` (−5 pts)

```python
from headers import analyse_headers

headers = {"strict-transport-security": "max-age=31536000"}
results, score, grade = analyse_headers(headers)
hsts = next(r for r in results if r.name == "strict-transport-security")
assert hsts.score_awarded == 15, f"HSTS attendu 15, obtenu {hsts.score_awarded}"
print(f"T-SCORE-06  PASS  HSTS={hsts.score_awarded}/20  (no includeSubDomains -5)")
```

**Attendu :** `T-SCORE-06  PASS  HSTS=15/20`

---

### T-SCORE-07 — X-Content-Type-Options avec valeur non standard

```python
from headers import analyse_headers

headers = {"x-content-type-options": "nosniff-extended"}
results, score, grade = analyse_headers(headers)
xcto = next(r for r in results if r.name == "x-content-type-options")
assert xcto.score_awarded == 5,           f"XCTO attendu 5, obtenu {xcto.score_awarded}"
assert xcto.status.value  == "warning",   f"Status attendu warning, obtenu {xcto.status.value}"
print(f"T-SCORE-07  PASS  XCTO={xcto.score_awarded}/15  status={xcto.status.value}")
```

**Attendu :** `T-SCORE-07  PASS  XCTO=5/15  status=warning`

---

### T-SCORE-08 — X-Frame-Options avec `ALLOW-FROM` (déprécié, −10 pts)

```python
from headers import analyse_headers

headers = {"x-frame-options": "ALLOW-FROM https://partner.example.com"}
results, score, grade = analyse_headers(headers)
xfo = next(r for r in results if r.name == "x-frame-options")
assert xfo.score_awarded == 5,          f"XFO attendu 5, obtenu {xfo.score_awarded}"
assert xfo.status.value  == "warning",  f"Status attendu warning, obtenu {xfo.status.value}"
print(f"T-SCORE-08  PASS  XFO={xfo.score_awarded}/15  status={xfo.status.value}")
```

**Attendu :** `T-SCORE-08  PASS  XFO=5/15  status=warning`

---

### T-SCORE-09 — Referrer-Policy avec `unsafe-url` (très permissif)

```python
from headers import analyse_headers

headers = {"referrer-policy": "unsafe-url"}
results, score, grade = analyse_headers(headers)
rp = next(r for r in results if r.name == "referrer-policy")
assert rp.score_awarded == 2,         f"RP attendu 2, obtenu {rp.score_awarded}"
assert rp.status.value  == "warning", f"Status attendu warning, obtenu {rp.status.value}"
print(f"T-SCORE-09  PASS  RP={rp.score_awarded}/10  status={rp.status.value}")
```

**Attendu :** `T-SCORE-09  PASS  RP=2/10  status=warning`

---

### T-SCORE-10 — X-XSS-Protection absent AVEC CSP (pas de pénalité)

```python
from headers import analyse_headers

# CSP présent → X-XSS-Protection absent = pas de pénalité (déprécié)
headers = {"content-security-policy": "default-src 'self'"}
results, score, grade = analyse_headers(headers)
xxss = next(r for r in results if r.name == "x-xss-protection")
assert xxss.score_awarded == 5,             f"XXSS attendu 5, obtenu {xxss.score_awarded}"
assert xxss.status.value  == "deprecated",  f"Status attendu deprecated, obtenu {xxss.status.value}"
print(f"T-SCORE-10  PASS  XXSS={xxss.score_awarded}/5  status={xxss.status.value}")
```

**Attendu :** `T-SCORE-10  PASS  XXSS=5/5  status=deprecated`

**Pourquoi :** X-XSS-Protection est déprécié. Si CSP est présent, il joue le rôle de substitut — aucune pénalité.

---

### T-SCORE-11 — X-XSS-Protection absent SANS CSP (pénalité double)

```python
from headers import analyse_headers

# Ni CSP ni X-XSS-Protection → pénalité
results, score, grade = analyse_headers({})
xxss = next(r for r in results if r.name == "x-xss-protection")
assert xxss.score_awarded == 0,        f"XXSS attendu 0, obtenu {xxss.score_awarded}"
assert xxss.status.value  == "absent", f"Status attendu absent, obtenu {xxss.status.value}"
assert len(xxss.details) > 0,          "Devrait contenir un detail sur l'absence de CSP"
print(f"T-SCORE-11  PASS  XXSS={xxss.score_awarded}/5  details={xxss.details}")
```

**Attendu :** `T-SCORE-11  PASS  XXSS=0/5  details=['CSP is also absent — ...']`

---

### T-SCORE-12 — Normalisation de la casse des noms de headers

```python
from headers import analyse_headers

# Les noms de headers en casse mixte doivent être normalisés avant appel
# (la normalisation est faite dans auditor.py, mais on peut le simuler ici)
raw_mixed_case = {
    "Content-Security-Policy": "default-src 'self'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
}
# Normalisation manuelle (comme le fait auditor.py)
normalised = {k.lower(): v for k, v in raw_mixed_case.items()}
results, score, grade = analyse_headers(normalised)
csp  = next(r for r in results if r.name == "content-security-policy")
hsts = next(r for r in results if r.name == "strict-transport-security")
xcto = next(r for r in results if r.name == "x-content-type-options")
assert csp.score_awarded  == 25
assert hsts.score_awarded == 20
assert xcto.score_awarded == 15
print(f"T-SCORE-12  PASS  Casse mixte correctement normalisée")
```

**Attendu :** `T-SCORE-12  PASS  Casse mixte correctement normalisée`

---

### T-SCORE-13 — Header présent mais valeur vide (traité comme absent)

```python
from headers import analyse_headers

# Une valeur vide ou espaces seuls doit être traitée comme une absence
headers = {
    "x-content-type-options": "   ",  # blancs
    "x-frame-options": "",            # chaîne vide
}
results, score, grade = analyse_headers(headers)
xcto = next(r for r in results if r.name == "x-content-type-options")
xfo  = next(r for r in results if r.name == "x-frame-options")
assert xcto.score_awarded == 0, f"XCTO vide devrait scorer 0, obtenu {xcto.score_awarded}"
assert xfo.score_awarded  == 0, f"XFO vide devrait scorer 0, obtenu {xfo.score_awarded}"
print(f"T-SCORE-13  PASS  Valeurs vides traitées comme absentes")
```

**Attendu :** `T-SCORE-13  PASS  Valeurs vides traitées comme absentes`

---

### T-SCORE-14 — Grades aux seuils exacts

```python
from headers import score_to_grade

seuils = [(100, "A"), (90, "A"), (89, "B"), (75, "B"), (74, "C"),
          (50, "C"), (49, "D"), (25, "D"), (24, "F"), (0, "F")]
for score, expected in seuils:
    got = score_to_grade(score)
    status = "PASS" if got == expected else f"FAIL (obtenu {got})"
    print(f"  score={score:3d}  attendu={expected}  {status}")
```

**Attendu :** toutes les lignes marquées `PASS`.

---

## 4. Tests réseau et comportements limites

Ces tests nécessitent une connexion internet.

---

### T-NET-01 — Domaine joignable en HTTPS

```bash
python auditor.py -u https://www.cloudflare.com --verbose
```

**Attendu :**
- Ligne `INFO` avec `HTTPS  score=XX  grade=X`
- Pas d'erreur TLS
- `report.html` généré
- `protocol` dans la sortie console = `HTTPS`

---

### T-NET-02 — Domaine HTTP (sans HTTPS) — détection HSTS manquant

```bash
python auditor.py -u http://neverssl.com
```

**Attendu :**
- Protocol affiché : `HTTP`
- HSTS score = 0 (impossible d'avoir HSTS sans HTTPS)
- Grade vraisemblablement F ou D

**Ce que ça vérifie :** que le score HSTS est bien 0 sur un site HTTP pur, et que le rapport l'indique clairement.

---

### T-NET-03 — Domaine avec redirection HTTP → HTTPS

```bash
python auditor.py -u http://github.com --verbose
```

**Attendu :**
- Le log montre le suivi de la redirection
- `final_url` dans le rapport = `https://github.com/` (après redirect)
- HSTS évalué sur la réponse HTTPS finale

**Ce que ça vérifie :** que `allow_redirects=True` fonctionne et que les headers analysés sont ceux de la destination finale, pas de la réponse 301 intermédiaire.

---

### T-NET-04 — Domaine inexistant (UNREACHABLE)

```bash
python auditor.py -u https://ce-domaine-nexiste-vraiment-pas-du-tout.invalid
```

**Attendu :**
- Ligne `WARNING` avec `Connection error` ou `Name resolution failed`
- Tableau console : `UNREACHABLE — Connection error: ...`
- `report.html` généré avec une ligne rouge pour ce domaine, score 0, grade F
- Pas de crash Python

---

### T-NET-05 — Timeout simulé (domaine lent)

Modifier temporairement `DEFAULT_TIMEOUT` à `1` dans `auditor.py` (ligne `DEFAULT_TIMEOUT = 8`) puis :

```bash
python auditor.py -u https://httpbin.org/delay/5
```

**Attendu :** `WARNING  Request timed out after 1s` dans les logs, domaine marqué UNREACHABLE dans le rapport.

Remettre `DEFAULT_TIMEOUT = 8` après le test.

---

### T-NET-06 — Fichier multi-domaines avec un domaine mort

Créer un fichier de test :

```bash
# Linux / macOS
cat > /tmp/mixed.txt << 'EOF'
https://www.github.com
https://domaine-mort-inexistant-xyz-123.invalid
https://owasp.org
EOF
python auditor.py -t /tmp/mixed.txt --json
```

```powershell
# Windows PowerShell
@"
https://www.github.com
https://domaine-mort-inexistant-xyz-123.invalid
https://owasp.org
"@ | Out-File -Encoding utf8 "$env:TEMP\mixed.txt"
python auditor.py -t "$env:TEMP\mixed.txt" --json
```

**Attendu :**
- 3 domaines audités (`[1/3]`, `[2/3]`, `[3/3]`)
- Le domaine inexistant est marqué UNREACHABLE avec score 0
- Les deux autres ont des scores normaux
- `results.json` contient `"unreachable": 1`
- `report.html` affiche une bannière rouge pour le domaine mort

---

## 5. Tests de sortie HTML et JSON

### T-OUT-01 — HTML auto-contenu (pas de CDN externe)

```bash
python auditor.py -t targets.txt
```

Puis vérifier qu'aucune balise `<script>`, `<link>` ou `<img>` ne charge une ressource externe :

```python
import re

html = open("output/report.html", encoding="utf-8").read()
pattern = r'<(script|link|img|iframe)[^>]+(src|href)=["\']https?://'
hits = re.findall(pattern, html, re.IGNORECASE)
if not hits:
    print("PASS — aucune ressource externe chargée")
else:
    for h in hits:
        print("FAIL —", h)
```

**Attendu :** `PASS — aucune ressource externe chargée`

---

### T-OUT-02 — Structure JSON valide et complète

```bash
python auditor.py -u github.com --json
```

```python
import json

data = json.loads(open("output/results.json", encoding="utf-8").read())

# Clés de premier niveau
assert "meta"    in data
assert "summary" in data
assert "results" in data

# Clés summary
s = data["summary"]
assert "total_domains"      in s
assert "reachable"          in s
assert "unreachable"        in s
assert "average_score"      in s
assert "grade_distribution" in s

# Structure d'un résultat
r = data["results"][0]
assert "url"           in r
assert "final_url"     in r
assert "reachable"     in r
assert "tls_warning"   in r
assert "protocol"      in r
assert "audited_at"    in r
assert "total_score"   in r
assert "grade"         in r
assert "headers"       in r
assert len(r["headers"]) == 7   # exactement 7 headers analysés

# Structure d'un header
h = r["headers"][0]
assert "name"          in h
assert "display_name"  in h
assert "status"        in h
assert "raw_value"     in h
assert "score_awarded" in h
assert "score_max"     in h
assert "recommendation" in h
assert "details"       in h

print("PASS — structure JSON complète et valide")
print(f"  Domaine  : {r['url']}")
print(f"  Score    : {r['total_score']}/100  grade={r['grade']}")
print(f"  Headers  : {[h['name'] for h in r['headers']]}")
```

**Attendu :** `PASS — structure JSON complète et valide` suivi des détails du domaine audité.

---

### T-OUT-03 — Cohérence entre HTML et JSON

Après un audit multi-domaines avec `--json` :

```python
import json, re

html  = open("output/report.html",  encoding="utf-8").read()
data  = json.loads(open("output/results.json", encoding="utf-8").read())

for r in data["results"]:
    score = str(r["total_score"])
    grade = r["grade"]
    # Le score et le grade doivent apparaître dans le HTML
    assert score in html, f"Score {score} absent du HTML"
    assert f'>{grade}<' in html or f'"{grade}"' in html, f"Grade {grade} absent du HTML"

print(f"PASS — scores et grades cohérents entre JSON et HTML ({len(data['results'])} domaines)")
```

**Attendu :** `PASS — scores et grades cohérents entre JSON et HTML`

---

### T-OUT-04 — Rapport HTML lisible dans un navigateur

Ouvrir manuellement `output/report.html` dans un navigateur :

```bash
# Linux
xdg-open output/report.html

# macOS
open output/report.html

# Windows
Start-Process output\report.html
```

**Points à vérifier visuellement :**

| Point | Attendu |
|---|---|
| En-tête | Fond sombre, titre "HTTP Header Security Report" |
| Bande méta | Version, timestamp, user-agent visibles |
| Grille de stats | Score moyen, répartition des grades |
| Tableau récapitulatif | Barre de progression colorée par grade |
| Cards de détail | Cliquables (expand/collapse) |
| Boutons | "Expand all" et "Collapse all" fonctionnels |
| Statuts | Badges colorés (vert / orange / rouge / gris) |
| Valeurs brutes | En police monospace |
| Recommandations | Lisibles, en anglais courant |

---

## 6. Test de bout en bout complet

Ce test simule un scénario d'utilisation réaliste et vérifie l'enchaînement complet de l'outil.

### Objectif

Auditer 4 domaines, produire le HTML et le JSON, valider la cohérence des sorties.

### Étape 1 — Préparer les cibles

```bash
# Linux / macOS
cat > /tmp/e2e_targets.txt << 'EOF'
https://www.github.com
https://www.cloudflare.com
https://owasp.org
https://domaine-inexistant-e2e.invalid
EOF
```

```powershell
# Windows PowerShell
@"
https://www.github.com
https://www.cloudflare.com
https://owasp.org
https://domaine-inexistant-e2e.invalid
"@ | Out-File -Encoding utf8 "$env:TEMP\e2e_targets.txt"
```

### Étape 2 — Lancer l'audit

```bash
# Linux / macOS
python auditor.py -t /tmp/e2e_targets.txt --json --output ./e2e_output --verbose

# Windows
python auditor.py -t "$env:TEMP\e2e_targets.txt" --json --output ./e2e_output --verbose
```

### Étape 3 — Vérifier les sorties attendues

```python
import json, re
from pathlib import Path

# Fichiers présents
assert Path("e2e_output/report.html").exists(),   "report.html manquant"
assert Path("e2e_output/results.json").exists(),  "results.json manquant"

data = json.loads(Path("e2e_output/results.json").read_text(encoding="utf-8"))

# 4 domaines audités
assert data["summary"]["total_domains"] == 4,  f"Attendu 4, obtenu {data['summary']['total_domains']}"

# 1 domaine injoignable
assert data["summary"]["unreachable"]   == 1,  f"Attendu 1 unreachable, obtenu {data['summary']['unreachable']}"

# 3 domaines joignables
assert data["summary"]["reachable"]     == 3,  f"Attendu 3 reachable, obtenu {data['summary']['reachable']}"

# Le domaine mort a score 0 et grade F
dead = next(r for r in data["results"] if not r["reachable"])
assert dead["total_score"] == 0,  f"Score mort attendu 0, obtenu {dead['total_score']}"
assert dead["grade"]       == "F", f"Grade mort attendu F, obtenu {dead['grade']}"

# Chaque résultat a exactement 7 headers
for r in data["results"]:
    assert len(r["headers"]) == 7, f"{r['url']} : attendu 7 headers, obtenu {len(r['headers'])}"

# HTML auto-contenu
html = Path("e2e_output/report.html").read_text(encoding="utf-8")
ext_loads = re.findall(r'<(script|link|img)[^>]+(src|href)=["\']https?://', html, re.IGNORECASE)
assert not ext_loads, f"Ressources externes trouvées : {ext_loads}"

print("PASS — test de bout en bout complet")
print(f"  Domaines audités : {data['summary']['total_domains']}")
print(f"  Joignables       : {data['summary']['reachable']}")
print(f"  Injoignables     : {data['summary']['unreachable']}")
print(f"  Score moyen      : {data['summary']['average_score']}/100")
print(f"  Répartition      : {data['summary']['grade_distribution']}")
```

### Étape 4 — Nettoyage

```bash
# Linux / macOS
rm -rf e2e_output/

# Windows PowerShell
Remove-Item -Recurse e2e_output
```

---

## Récapitulatif des tests

| ID | Catégorie | Description | Réseau requis |
|---|---|---|---|
| T-CLI-01 | CLI | `--help` | Non |
| T-CLI-02 | CLI | Argument obligatoire manquant | Non |
| T-CLI-03 | CLI | `-u` et `-t` simultanément | Non |
| T-CLI-04 | CLI | Fichier de cibles inexistant | Non |
| T-CLI-05 | CLI | Domaine nu sans schéma | Oui |
| T-CLI-06 | CLI | URL avec schéma complet | Oui |
| T-CLI-07 | CLI | Fichier de cibles standard | Oui |
| T-CLI-08 | CLI | Export JSON activé | Oui |
| T-CLI-09 | CLI | Répertoire de sortie personnalisé | Oui |
| T-CLI-10 | CLI | Mode verbose | Oui |
| T-CLI-11 | CLI | Commentaires et lignes vides ignorés | Oui |
| T-SCORE-01 | Scoring | Score parfait 100/A | Non |
| T-SCORE-02 | Scoring | Aucun header 0/F | Non |
| T-SCORE-03 | Scoring | CSP `unsafe-inline` −10 pts | Non |
| T-SCORE-04 | Scoring | CSP `unsafe-inline` + `unsafe-eval` −20 pts | Non |
| T-SCORE-05 | Scoring | HSTS `max-age` court −8 pts | Non |
| T-SCORE-06 | Scoring | HSTS sans `includeSubDomains` −5 pts | Non |
| T-SCORE-07 | Scoring | XCTO valeur non standard → warning | Non |
| T-SCORE-08 | Scoring | XFO `ALLOW-FROM` → warning | Non |
| T-SCORE-09 | Scoring | Referrer-Policy `unsafe-url` → 2/10 | Non |
| T-SCORE-10 | Scoring | X-XSS absent + CSP présent → pas de pénalité | Non |
| T-SCORE-11 | Scoring | X-XSS absent + CSP absent → 0/5 | Non |
| T-SCORE-12 | Scoring | Normalisation casse des headers | Non |
| T-SCORE-13 | Scoring | Valeur vide traitée comme absente | Non |
| T-SCORE-14 | Scoring | Grades aux seuils exacts | Non |
| T-NET-01 | Réseau | Domaine HTTPS joignable | Oui |
| T-NET-02 | Réseau | Domaine HTTP pur, HSTS = 0 | Oui |
| T-NET-03 | Réseau | Redirection HTTP → HTTPS | Oui |
| T-NET-04 | Réseau | Domaine inexistant → UNREACHABLE | Oui |
| T-NET-05 | Réseau | Timeout simulé | Oui |
| T-NET-06 | Réseau | Mix domaines joignables/morts | Oui |
| T-OUT-01 | Sortie | HTML auto-contenu (pas de CDN) | Non |
| T-OUT-02 | Sortie | Structure JSON complète | Non |
| T-OUT-03 | Sortie | Cohérence HTML ↔ JSON | Non |
| T-OUT-04 | Sortie | Rendu visuel dans navigateur | Non |
| E2E | End-to-end | Scénario complet 4 domaines | Oui |
