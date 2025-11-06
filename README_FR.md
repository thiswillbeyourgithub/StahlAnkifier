**Français** | **[English](README.md)**

# Stahl Ankifier

Un script Python pour convertir le PDF de Stahl's Essential Psychopharmacology en cartes Anki pour une mémorisation efficace.

**Remarque :** Cet outil est conçu pour les personnes qui ont légalement acheté la version PDF de Stahl's Essential Psychopharmacology. Ce script ne contient ni ne distribue aucun contenu protégé par des droits d'auteur du livre - il fournit uniquement des fonctionnalités pour transformer votre propre PDF acheté en cartes Anki à des fins d'étude personnelle.

## Vue d'ensemble

Ce script analyse la structure PDF de Stahl's Essential Psychopharmacology et génère automatiquement des cartes Anki organisées par :
- Nom du médicament
- Sections principales (en-têtes H1)
- Sujets spécifiques (en-têtes H2)

Chaque carte comprend :
- La question/le sujet
- Le contenu de la réponse avec formatage préservé
- Images des pages sources pour référence
- Tags hiérarchiques pour l'organisation

Créé avec l'assistance de [aider.chat](https://github.com/Aider-AI/aider/).

## 🤝 Pas à l'aise avec Python ?

**Si vous n'êtes pas à l'aise avec Python ou rencontrez des difficultés pour exécuter ce script, ne vous inquiétez pas !**

Vous pouvez me contacter et si vous fournissez une preuve que vous possédez le PDF, je serai heureux de vous envoyer directement le paquet Anki pré-converti.

Contactez-moi via :
- **GitHub Issues** : Ouvrez un ticket sur ce dépôt
- **Email** : Contactez-moi via mon site web à [https://olicorne.org](https://olicorne.org)

De cette façon, toute personne possédant le livre peut bénéficier des cartes mémoire, quel que soit son niveau technique :)

## Fonctionnalités

- **Détection automatique de la structure** : Identifie les chapitres sur les médicaments et les sections hiérarchiques
- **Deux types de cartes** :
  - Cartes Q&R basiques (par défaut)
  - Cartes à suppression de texte à trous (`--cloze`)
- **Référence visuelle** : Inclut les images des pages sources sur chaque carte
- **Formatage intelligent** :
  - Préserve le formatage important (gras, italique, liens)
  - Fusionne les paragraphes divisés par le retour à la ligne du PDF
  - Supprime les en-têtes de page et le balisage superflu
- **Marquage organisé** : Les cartes sont marquées par médicament et section pour un filtrage facile

## Installation

Ce script utilise les métadonnées de script inline [PEP 723](https://peps.python.org/pep-0723/), vous pouvez donc l'exécuter directement avec `uv` :

```bash
uv run stahl_ankifier.py <chemin_vers_votre_pdf>
```

Le script installera automatiquement toutes les dépendances requises lors de la première exécution.

### Installation manuelle

Si vous préférez installer les dépendances manuellement :

```bash
pip install fire pymupdf beautifulsoup4 loguru tqdm genanki Pillow
```

## Utilisation

### Cartes Q&R basiques (par défaut)

```bash
uv run stahl_ankifier.py votre_pdf_stahl.pdf
```

Cela crée un paquet avec des champs séparés pour le nom du médicament, la section, la question et la réponse.

### Cartes à suppression de texte à trous

```bash
uv run stahl_ankifier.py votre_pdf_stahl.pdf --cloze
```

Cela crée des cartes à trous où le médicament/section/question sont affichés avec la réponse enveloppée dans la syntaxe de suppression à trous `{{c1::}}`.

### Sortie

Le script génère un fichier `.apkg` (par exemple, `stahl_drugs_v1.0.0.apkg`) qui peut être importé directement dans Anki.

## Avis juridique

**Cet outil est complètement légal pour les raisons suivantes :**

1. **Aucune distribution de contenu** : Ce script ne contient pas, ne distribue pas et ne fournit pas d'accès à du contenu protégé par des droits d'auteur de Stahl's Essential Psychopharmacology.

2. **Usage personnel uniquement** : L'outil est destiné uniquement aux personnes qui ont légalement acheté leur propre copie du PDF.

3. **Conversion de format** : Le script transforme simplement le contenu d'un format (PDF) à un autre (cartes Anki) à des fins d'étude personnelle - similaire à la prise de notes personnelles ou à la création de vos propres supports d'étude.

4. **Usage équitable** : La création de supports d'étude personnels à partir de contenu éducatif légalement acheté relève de la doctrine de l'usage équitable dans la plupart des juridictions.

## Support

Si vous rencontrez des problèmes ou avez des questions :

- **GitHub Issues** : Ouvrez un ticket sur ce dépôt
- **Email** : Contactez-moi via mon site web à [https://olicorne.org](https://olicorne.org)

## Licence

Ce projet est sous licence GNU General Public License v3.

Voir le fichier [LICENSE](LICENSE) pour le texte complet de la licence.

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à soumettre des pull requests ou à ouvrir des tickets pour les bugs et les demandes de fonctionnalités.

## Avertissement

Ce logiciel est fourni "tel quel" sans garantie d'aucune sorte. L'auteur n'est pas affilié à ou approuvé par les éditeurs de Stahl's Essential Psychopharmacology. Les utilisateurs sont responsables de s'assurer que leur utilisation de cet outil est conforme aux lois applicables sur les droits d'auteur dans leur juridiction.
