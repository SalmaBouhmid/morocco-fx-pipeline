# Cahier des charges — Morocco FX Pipeline (dirham)

> Projet portfolio n° 3 de Salma Bouhmid (DUT data engineering, EST, Agadir). Objectif : montrer un **pipeline qui tourne
> tout seul chaque jour**, sur des données marocaines réelles, utile aux entreprises de la région (export, tourisme, transferts).
> Ce document est la référence unique du projet : toute nouvelle session Claude Code doit le lire en premier.

## 1. Pitch

Un **pipeline de données quotidien** qui collecte les **cours de change officiels de Bank Al-Maghrib** (32 devises, depuis 1999),
les historise sans doublon, contrôle leur qualité, calcule des indicateurs utiles (moyennes, volatilité, panier du dirham)
et alimente un **dashboard en ligne mis à jour automatiquement chaque jour**.

Angle métier (Souss-Massa) : les **exportateurs agricoles** d'Agadir vendent en euros, les **hôtels** facturent des clients européens,
et les **transferts des Marocains du monde** dépendent de l'EUR/MAD : tous ont besoin de suivre le dirham.

Phrase CV : *« Pipeline quotidien des cours de change Bank Al-Maghrib (32 devises, 1999 → aujourd'hui) : ingestion incrémentale
et idempotente, orchestration Airflow sous Docker, modèles dbt testés, exécution planifiée par GitHub Actions et dashboard Streamlit
mis à jour automatiquement. »*

## 2. Questions métier

| # | Question | Indicateurs |
|---|---|---|
| Q1 | Quel est le cours du jour et sa variation ? | cours, variation jour / semaine / mois, par devise |
| Q2 | Le dirham est-il stable face à l'euro et au dollar ? | volatilité glissante 30 j, plus fortes variations, comparaison par période |
| Q3 | Quand un exportateur aurait-il dû convertir ses euros ? | meilleur / pire mois historique, moyenne mobile, saisonnalité |
| Q4 | Comment se comporte le panier du dirham ? | indice reconstruit EUR/USD (pondérations officielles à **vérifier sur le site de Bank Al-Maghrib** avant de les utiliser) |
| Q5 | Les données sont-elles complètes ? | jours manquants (hors week-ends et jours fériés), valeurs aberrantes, retards de publication |

## 3. Données

- **API** : Frankfurter, fournisseur `bam` (Bank Al-Maghrib) — gratuite, **sans clé**, historique quotidien depuis 1999-01-04.
  - Dernier jour : `https://api.frankfurter.dev/v2/providers/bam/rates`
  - Historique : `https://api.frankfurter.dev/v2/rates?base=mad&providers=bam&from=AAAA-MM-JJ` (testé le 2026-11-06 : JSON
    `[{date, base, quote, rate}, …]`, 32 devises).
- Frankfurter est un **agrégateur** de la source officielle : le dire dans le README. Option : le portail développeur officiel de
  Bank Al-Maghrib demande une inscription et une clé (Salma s'inscrit elle-même si on l'utilise ; clé dans `.env`, jamais dans Git).

## 4. Architecture (deux modes d'exécution, même code)

```
                 ┌──────────── Mode local « entreprise » ────────────┐
API Frankfurter  │  Airflow (Docker) : DAG quotidien                 │
(BAM, 32 devises)│   extract → load (upsert) → dbt build → contrôles │──► PostgreSQL
                 └───────────────────────────────────────────────────┘
                 ┌──────────── Mode cloud gratuit ────────────────────┐
                 │  GitHub Actions (cron chaque jour)                 │
                 │   même code → DuckDB/Parquet versionné dans le repo│──► Streamlit Cloud (dashboard public,
                 └────────────────────────────────────────────────────┘    mis à jour chaque jour tout seul)

Couches : raw (réponse API brute, JSON horodaté) → staging (types, dédoublonnage) → marts
          (fct_daily_rates, fct_monthly_rates, fct_volatility, mad_basket_index, data_quality_report)
```

Points d'ingénierie à démontrer (c'est ce qui distingue le projet d'un tutoriel) :
- **Incrémental** : on garde la dernière date chargée (watermark) et on ne demande que les jours manquants.
- **Idempotent** : relancer deux fois le même jour ne crée aucun doublon (clé `date + devise`, upsert).
- **Backfill** : une commande recharge tout l'historique depuis 1999.
- **Robuste** : retries avec attente si l'API ne répond pas, journalisation, échec visible (et non silencieux).
- **Qualité** : tests dbt + contrôle des trous de dates et des variations anormales (> 5 % en un jour → alerte).

## 5. Stack

| Outil | Rôle | Phrase à savoir dire |
|---|---|---|
| Python (requests, pandas) | appel API, retries | « J'appelle l'API, je garde la réponse brute, puis je charge. » |
| PostgreSQL / DuckDB | stockage local / stockage léger pour le cloud | « DuckDB, c'est un SQLite analytique : un fichier, très rapide. » |
| dbt | modèles SQL testés, mêmes modèles pour Postgres et DuckDB | « dbt sépare la logique SQL de l'endroit où elle tourne. » |
| Airflow + Docker | planification quotidienne, relances, historique | « Le DAG tourne chaque jour à 18 h ; s'il échoue, il réessaie. » |
| GitHub Actions (cron) | exécution gratuite dans le cloud | « Pas de serveur à payer : GitHub lance le pipeline chaque jour. » |
| Streamlit + Plotly | dashboard public | lien cliquable dans le CV |

## 6. Phases

| Phase | Contenu | Salma doit savoir expliquer |
|---|---|---|
| 1 | `extract.py` + retries + tests (avec une réponse API simulée) | API REST, JSON, retry |
| 2 | Chargement incrémental + idempotent dans DuckDB ; commande `backfill` | watermark, upsert, idempotence |
| 3 | dbt (adaptateur DuckDB) : staging + marts + tests | modèle, test, lineage |
| 4 | Contrôles qualité + rapport | pourquoi un trou de date n'est pas forcément une erreur (week-end, jour férié) |
| 5 | GitHub Actions cron quotidien qui commit les données à jour | cron, CI vs exécution planifiée |
| 6 | Dashboard Streamlit déployé (cours du jour, historique, volatilité, panier, qualité) | lien en ligne |
| 7 | Mode entreprise : Docker Compose (Postgres + Airflow) avec le même code et dbt-postgres | DAG, conteneur |
| 8 | README FR/EN + schéma + captures, CI verte, tag v1.0 ; fiche entretien dans `pour_moi/` | pitch de 30 s |

Ordre volontaire : les phases 1 à 6 donnent **vite** un projet en ligne qui tourne seul ; Airflow/Docker (phase 7) vient ensuite.

## 7. Exigences de qualité

- Code et noms en anglais ; README FR + EN ; explications simples.
- Aucun chiffre inventé ; toute pondération ou règle officielle (panier du dirham) citée avec sa source.
- Commits au nom de Salma uniquement (pas de « Co-Authored-By »).
- Tests pytest (sans appel réseau : réponses simulées) + tests dbt ; ruff ; CI sur chaque push.
- Le cron ne doit pas faire grossir le dépôt sans fin : un seul fichier Parquet/DuckDB compact, réécrit (pas un fichier par jour).

## 8. Définition de « terminé »

- [ ] Le dashboard public affiche les cours **du dernier jour ouvré** sans action manuelle pendant 7 jours de suite.
- [ ] `backfill` recharge 1999 → aujourd'hui ; relancer ne crée aucun doublon (test automatisé).
- [ ] `docker compose up` lance Airflow + Postgres et le DAG réussit.
- [ ] Dépôt public `SalmaBouhmid/morocco-fx-pipeline`, CI verte, épinglé ; fiche entretien dans `pour_moi/` (non publiée).

## 9. Contraintes de l'environnement

- Windows 11, Python Anaconda : `C:\Users\123\anaconda3\python.exe`. Git configuré (« Salma bouhmid »), push via le gestionnaire
  d'identifiants. Docker pas encore installé (nécessaire seulement en phase 7 ; Salma l'installe elle-même).
- Salma est étudiante, très peu de temps : petites phases livrables, explications en français simple, 3 questions de vérification
  à la fin de chaque phase.
