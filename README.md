# Comap chauffage — application Android autonome

Version mobile de `comap_dashboard.py` : une application Android (APK) qui interroge Comap et Open-Meteo
directement depuis le téléphone, sans PC ni navigateur. Le code Python tourne dans l'application (Chaquopy)
et la page s'affiche dans une WebView intégrée.

## Ce que l'application affiche
- en haut : température intérieure, état du chauffage, consigne, température extérieure et niveau des piles ;
- le graphique (6 h, 24 h, 3 jours, 7 jours) avec la courbe de température intérieure, la **consigne** (en escalier,
  tirets) et le bouton « Météo » (48 h, 7 jours) ;
- la lecture des valeurs : toucher le graphique affiche l'heure et les valeurs dans une barre située **au-dessus** du
  graphique (elle reste affichée après avoir levé le doigt) ;
- en mode paysage : valeurs à gauche, graphique en pleine hauteur à droite, barre d'état masquée.

Pas de barre de titre : l'engrenage (en haut à droite) ouvre les réglages, la flèche circulaire actualise
(tirer l'écran vers le bas depuis le haut fonctionne aussi). La stratégie du lendemain a été retirée.

## Ce qui a été retiré par rapport à la version PC
- tous les accès aux fichiers (journal des mesures, périodes de chauffe enregistrées, export CSV,
  clé d'accès réseau) : tout reste en mémoire ;
- les tableaux « Durée de chauffe par jour / par semaine » (et le bouton €), « Périodes de chauffe »
  et « Dernières mesures » ;
- les options de ligne de commande (`--decouvrir`, `--surveiller`, `--exporter`).

Conséquence : sans enregistrement, l'application ne tourne que lorsqu'elle est ouverte (rien à
faire en arrière-plan, pas de notification permanente). L'historique affiché vient de Comap.

## Réglages
Au premier lancement, un formulaire demande : e-mail et mot de passe Comap, numéro de série du thermostat
(ou identifiant de zone), latitude/longitude pour la météo et les deux corrections de 0,5 °C.
Ils sont conservés dans le stockage privé de l'application (engrenage de l'écran principal pour les modifier).
Le numéro de série se trouvait avec `python comap_dashboard.py --decouvrir` sur le PC.

## Fabriquer l'APK

### Option A — sans rien installer : GitHub Actions
1. Créez un dépôt GitHub **privé** et poussez-y le contenu de ce dossier.
2. Onglet *Actions* → « Build APK » → *Run workflow* (il se lance aussi à chaque push).
3. Téléchargez l'artefact `comap-chauffage-apk` (`app-debug.apk`).

### Option B — Android Studio
Ouvrez le dossier, laissez Gradle se synchroniser, puis *Build > Build APK(s)*.
Python 3.12 doit être installé sur l'ordinateur (Chaquopy s'en sert pour télécharger les paquets).

### Installer
Copiez l'APK sur le téléphone, ouvrez-le et autorisez l'installation depuis cette source.
L'APK est signé avec la clé de débogage : suffisant pour un usage personnel.

## Remarques
- L'APK est assez volumineux (~50 Mo) : il embarque Python et boto3 (connexion Comap).
- Versions utilisées : Chaquopy 17.0.0, Android Gradle Plugin 8.7.3, Gradle 8.9, Python 3.12, minSdk 24.
- Programme non officiel : Comap peut modifier son service à tout moment. Lecture seule.
