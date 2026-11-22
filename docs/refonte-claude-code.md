# Refonte du Carnet IA — instruction pour Claude Code

> Colle ce fichier à la racine du dépôt (avec les dossiers `assets/visuals/` et `reference/` livrés avec), puis dis à Claude Code :
> **« Lis `docs/refonte-claude-code.md` et exécute-le, étape par étape. »**

---

## Contexte

Ce dépôt est le site Quarto **Carnet IA** (`_quarto.yml`, `assets/theme.scss`, notes `.qmd` dans `llms/`, `agents/`, `evaluation/`, `toolbox/`) et l'**agent** qui écrit les nouvelles notes (`agent/carnet_agent/`, guide `agent/STYLE.md`, workflow `.github/workflows/agent.yml`).

Une maquette de refonte a été validée. Ses fichiers sont dans le dépôt :

- `reference/maquette/*.dc.html` : les écrans de référence en HTML avec styles en ligne (lis-les comme une spécification visuelle, ne les copie pas tels quels).
  - `Main.dc.html` : l'accueil · `Article.dc.html` : la lecture d'une note · `Topic.dc.html` : une page de thème en parcours · `Anatomie.dc.html` : le squelette commun d'une note (en français).
  - `Visuels-*.dc.html` : la galerie des visuels de synthèse.
- `assets/visuals/<slug>.svg` : **un visuel de synthèse par note existante** (26 fichiers, nommés comme le fichier `.qmd`, plus `toolbox-card.svg`). Ils sont prêts à l'emploi.
- `reference/vis.py` : le code qui a généré ces SVG. C'est **la grammaire visuelle** à réutiliser (palette, primitives, tailles).

La mission a trois parties : **(A) l'interface**, **(B) la restructuration des 25 notes existantes**, **(C) l'agent, pour que les prochaines notes sortent directement dans ce format**.

## Règles de travail

- Travaille sur une branche `refonte-lecture`. Un commit par étape ci-dessous. **Ne pousse pas et n'ouvre pas de PR sans me demander.**
- Après chaque étape : `quarto render` doit passer sans erreur, et `pytest agent/tests` doit rester vert.
- Ouvre les pages rendues (`_site/…`) pour vérifier le résultat, en clair **et** en sombre, sur ordinateur et en largeur mobile (390 px).
- **Ne perds aucune information** en restructurant : chaque fait, chiffre, bloc de code, exemple et source doit rester. Tu réorganises, tu ne réécris pas le fond et tu n'inventes rien.
- Ne change aucune URL existante (garde les `aliases`).
- Le contenu du site reste **en anglais**.
- Si un choix n'est pas couvert ici, prends l'option la plus proche de la maquette et note-la dans le résumé final.

---

## A. Interface (`assets/theme.scss`, `_quarto.yml`, `index.qmd`, `*/index.qmd`)

Garde la palette actuelle et les couleurs par thème. Ajoute une couleur propre aux guardrails : `#0f7a52` sur `#e8f6ef`. Elle existe déjà dans `theme.scss` (`$t-guardrails`) mais n'est pas utilisée.

1. **Typographie de lecture.**
   - Le corps du texte des notes passe en **Source Serif 4**, 19 px, interligne 1.75, largeur de colonne d'environ 700 px.
   - L'interface reste en **Inter**, les titres en **Space Grotesk** et le code en **JetBrains Mono**.
   - Charge Source Serif 4 dans l'`@import` Google Fonts existant.
2. **Page de note** (référence : `Article.dc.html`).
   - **À gauche** : la barre latérale du thème, avec le temps de lecture de chaque leçon.
   - **En dessous** : « On this page », avec un point plein pour les sections déjà lues. Essaie `toc-location: left` et vérifie au rendu que cela cohabite avec la sidebar. Si ça coince, garde la TOC à droite.
   - **À droite** : la colonne de marge pour les notes `.column-margin`.
   - **Barre de progression de lecture** : 3 px sous la navbar, couleur du thème. Un petit script dans `include-after-body`, qui respecte `prefers-reduced-motion`.
   - **Méta sous le sous-titre** : pastille du thème · « Lesson n of N » · « x min read » · « Updated <date> ». Calcule le temps de lecture à environ 200 mots par minute, dans un filtre Lua ou un pré-rendu, sans le saisir à la main.
   - **En fin de page** : un gros bouton « Next » vers la leçon suivante. Garde `page-navigation`, restylé.
3. **Blocs nouveaux ou restylés** (classes CSS, les mêmes que l'agent utilisera) :
   - `.synthesis` : la figure du visuel en tête de note. Coins arrondis, légende en dessous, et en mode sombre un fond clair autour du SVG (les SVG ont des couleurs claires codées en dur).
   - `.in30` : « In 30 seconds », un bloc sombre (`#16202e`, texte blanc), 3 puces. Il **remplace** `.tldr`. Garde `.tldr` stylé pour la compatibilité, mais plus aucune page ne doit l'utiliser.
   - `.column-margin` : les « Watch out » en ambre (`#b45309` sur `#fff3e2`) et les définitions en bleu, avec un petit intitulé en capitales. Sur mobile, ils redescendent dans le flux.
   - `.code-steps` : chaque bloc de code long dans un `<details>` avec un numéro, un titre et le langage. Seul le dernier est ouvert par défaut. Un filtre Lua est le plus propre : un bloc `::: {.code-step title="…"}` autour d'un bloc de code.
   - `details.quiz` existe déjà. Ajoute un titre « Check yourself » avant le premier quiz.
   - Sources : section repliée « Sources (n) ».
   - « Remember » reste un `callout-tip` vert.
4. **Vignettes.** Ajoute `image: /assets/visuals/<slug>.svg` dans le front matter de chaque note. Ajoute `image` aux `fields` de toutes les listings, pour que les cartes aient leur visuel.
5. **Accueil** (référence : `Main.dc.html`).
   - Titre à gauche et, à droite, le bloc « The learning path » : 1 LLMs → 2 Agents → 3 Evaluation & Guardrails, puis Toolbox en pointillés « Coming soon ».
   - Chaque étape affiche son nombre de notes et son temps total. Calcule-les, ne les écris pas en dur.
   - Ensuite : « Start here » (3 cartes : What is an agent, How Transformer LLMs Work, Guardrails for LLM apps), « Topics » (4 cartes), « Latest notes » (3 cartes avec vignette).
6. **Pages de thème** (référence : `Topic.dc.html`).
   - Chaque groupe devient un parcours numéroté : un cercle avec le numéro, une ligne verticale, puis une carte avec la vignette, le titre, le sous-titre et le temps de lecture. Le n°1 porte « start here ».
   - Utilise un template de listing personnalisé (`.ejs`) trié par `order`.
   - Ajoute `order:` dans les notes d'évaluation, dans cet ordre :
     - **Evaluating agents** : evaluating-ai-agents, agent-evaluation-workflow, traces-and-run-inspection, action-and-tool-use-evaluation, improvement-experiments, production-monitoring-and-regression-tests, agent-based-evaluation-in-practice
     - **Evaluating LLMs** : test-cases-and-benchmarks, llm-judges-and-custom-rubrics, validating-evaluators, red-teaming-llm-applications
     - **Guardrails** : guardrails-for-llm-apps, building-custom-guardrails, topic-guardrails, pii-guardrails, hallucination-guardrails, competitor-mention-guardrails
   - Donne aux guardrails leur couleur verte : pastille, accent de section, cartes.
7. Vérifie les contrastes : au moins 4.5:1 pour le texte, cibles cliquables d'au moins 44 px, focus visible.

## B. Restructurer les 25 notes existantes

Applique à chaque note le squelette de `reference/maquette/Anatomie.dc.html`, dans cet ordre :

1. Le front matter, avec `image:` et `order:` s'il y a lieu.
2. Le **visuel de synthèse** : `assets/visuals/<slug>.svg` dans une figure `.synthesis`, avec une légende d'une phrase en anglais qui dit ce que montre le schéma.
3. **In 30 seconds** : 3 puces de 25 mots au plus, tirées du TL;DR et du contenu. Jamais « This page explains… ».
4. **Concepts clés** : 3 ou 4 cartes `.concept`. Supprime celles qui répètent le résumé.
5. **Les sections** : une idée par H2.
   - Les H2 `## Watch out` isolés (plusieurs dans les notes Évaluation) deviennent des notes `.column-margin` rattachées à la section qu'ils concernent, une par section au plus. S'il y en a plus, garde-les dans un `callout-warning` dans la section.
   - Les blocs de code de plus de 12 lignes passent en `.code-step`.
   - Le mermaid de la note qui fait doublon avec le visuel de synthèse peut être retiré. Garde les autres.
6. **Remember** : 3 à 5 puces.
7. **Check yourself** : 2 ou 3 questions `details.quiz`, dont la réponse est dans la note.
8. **Sources**, repliées.

Les notes Évaluation font 2 300 à 3 400 mots. **Ne les découpe pas** : dresse plutôt, dans ton résumé final, la liste de celles qui gagneraient à être coupées en deux, avec l'endroit de la coupe.

Procède **thème par thème** (Agents, puis Evaluating agents, Evaluating LLMs, Guardrails, LLMs), avec un commit par thème. Après chaque thème, vérifie par un diff que les blocs de code, les URL de sources et les nombres sont tous toujours présents.

## C. L'agent : que les prochaines notes sortent dans ce format

Lis d'abord `agent/README.md`, `agent/STYLE.md`, `agent/carnet_agent/prompts.py`, `state.py`, `site.py`, `article.py` et `config.py`.

1. **`STYLE.md`**
   - Décris le nouveau squelette.
   - Remplace la règle « Warning : `::: {.callout-warning}` avec `## Watch out` » par la note de marge `::: {.column-margin}`, une par partie au plus.
   - Ajoute le composant `.code-step` pour le code de plus de 12 lignes.
   - Interdis les H2 « Watch out » isolés.
2. **`state.py` → `Synthesis`**
   - Remplace `tldr` par `in_30_seconds: list[str]` (exactement 3, 25 mots maximum chacun).
   - Ramène `concepts` à 3 ou 4 et `remember` à 3 à 5.
   - Ajoute `quiz: list[QuizItem]` (2 ou 3, question et réponse) et `visual_caption: str`.
   - Dans `ArticlePlan`, ajoute `visual_idea: str` : une phrase qui décrit le schéma de synthèse. Le bibliothécaire la propose, et elle s'affiche dans le plan posté sur l'issue (`describe_plan`), pour que je la valide avec `/approve`.
3. **`prompts.py`**
   - **Éditeur** : produit les nouveaux champs. Le prompt interdit « This page explains » et toute répétition entre les puces, les cartes et le Remember.
   - **Rédacteurs** : utilisent la note de marge pour les mises en garde et `.code-step` pour le code long.
   - **Bibliothécaire** : remplit `visual_idea`.
4. **Nouveau rôle : illustrateur** (`article.py`, nœud entre `edit` et `assemble`).
   - **Il reçoit** : le titre, le thème, `visual_idea`, les puces In 30 seconds et les titres des parties. Jamais la source brute.
   - **Il produit** : un SVG qui suit la grammaire de `reference/vis.py`.
     - `viewBox="0 0 520 300"` et fond = couleur douce du thème.
     - Cases blanches à bord `#d9dee8` et coins de 10 px.
     - Un ou deux éléments pleins dans la couleur du thème.
     - Texte en Inter de 10 à 15 px, et au moins 10 px de marge intérieure partout.
     - Couleurs prises uniquement dans la palette de `vis.py` : `C`, `INK`, `MUTED`, `LINE`, `OK`, `WARN`, `BAD` et leurs versions douces.
     - Il réutilise un exemple concret de la note quand il y en a un, avec de vrais noms et de vrais chiffres.
   - Mets dans le prompt 2 ou 3 SVG de `assets/visuals/` comme exemples.
   - **Validation par le code** (nouvelle fonction testée) :
     - XML valide, bon `viewBox`, moins de 15 Ko ;
     - aucun `<script>`, `foreignObject`, `<image>` ni `href` externe, aucun attribut `on*` ;
     - couleurs dans la palette ;
     - coordonnées des `<text>` à l'intérieur de 0–520 × 0–300.
   - En cas d'échec : **une** nouvelle tentative avec l'erreur. Si elle échoue aussi, pas de visuel, et un avertissement dans la description de la PR.
   - **Il écrit** `assets/visuals/<slug>.svg` et ajoute `image:` au front matter.
   - Pour une page qu'on complète (« update ») : garde le visuel existant, sauf si le plan indique `visual: new`.
   - Modèle configurable dans `config.py` (`ILLUSTRATOR_MODEL`), par défaut celui de l'éditeur.
   - Le SVG doit être commité dans la même PR que la note, pour être visible dans l'aperçu.
5. **`site.py` → `render_synthesis_blocks` et `article.py` → `assemble`** produisent le nouvel ordre des blocs : visuel, In 30 seconds, concepts, parties, Remember, Check yourself, sources. Le code qui « complète » une page existante doit reconnaître l'ancien bloc `.tldr` et le remplacer par `.in30`.
6. **Tests** (`agent/tests/test_offline.py`) : ajoute des tests pour
   - le validateur SVG (un bon SVG passe ; un `<script>`, une couleur hors palette ou un texte hors cadre échouent) ;
   - l'ordre des blocs de `assemble` ;
   - le remplacement `.tldr` → `.in30` sur une page existante.
7. **`agent/README.md`** : ajoute l'illustrateur au schéma des rôles et au tableau, et mets à jour la description de l'éditeur.

## Résumé final attendu

À la fin, donne-moi :

- la liste des commits ;
- les choix que tu as faits sans moi ;
- les notes à découper, avec l'endroit de la coupe ;
- les pages où un visuel ou une légende te semble faux par rapport au contenu ;
- comment tester l'illustrateur sur une vraie source (la commande `python -m carnet_agent.run …` à lancer en local).
