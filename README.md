# OSCQueryRemote

Script de contrôle (Remote Script) Python pour Ableton Live qui expose le set en OSC avec découverte OSCQuery.
Un client OSCQuery (Kadran, Chataigne, un navigateur) trouve le set tout seul, lit l'arbre en JSON, écoute les
changements par WebSocket (`LISTEN`) et écrit en OSC/UDP.

Nom de travail. Code écrit d'après le modèle d'objets de Live, rien repris d'AbletonOSC (ports différents : les deux
peuvent tourner ensemble).

## Installation

Copier le dossier `OSCQueryRemote/` dans `~/Music/Ableton/User Library/Remote Scripts/`, redémarrer Live, puis
Réglages > Link, Tempo & MIDI > Control Surface > `OSCQueryRemote`. Le journal de Live (`Log.txt`) dit les ports.

- HTTP + WebSocket OSCQuery : TCP 9101 (le système en choisit un autre si occupé, `HOST_INFO` le dit)
- OSC entrant : UDP 9100
- Annonce Bonjour `_oscjson._tcp` via `dns-sd` (macOS, Windows avec Bonjour) ou `avahi-publish-service` (Linux).
  Sans l'un d'eux, pas d'annonce : saisir l'adresse à la main.

## Arbre (chemins par index, le nom est une valeur)

| Chemin | Contenu |
|---|---|
| `/transport/` | play, stop, continue, stop_all_clips, record, session_record, overdub, loop, metronome, tempo, position, signature_*, tap_tempo, undo, redo |
| `/tracks/N/` | name, volume, pan, mute, solo, arm (si armable), stop, `sends/K`, `devices/M/parameters/K`, `clips/S/{fire,stop,has_clip,playing,triggered,name,color,looping,length}` |
| `/returns/N/` | name, volume, pan, mute, solo, devices |
| `/master/` | volume, pan, cue_volume, devices |
| `/scenes/S/` | name, color, fire |
| `/view/` | selected_track, selected_scene, `selected_device/parameters/K` (macros du dispositif sélectionné) |

Types : `f` flottant, `i` entier, `T` booléen, `s` texte, `I` déclencheur (envoyer le message sans argument).
`RANGE` vient de `min`/`max` du paramètre (volume 0..1, pan -1..1, tempo 20..999). Les paramètres de dispositif
sont leur valeur brute.

## Fonctionnement

- Un seul fil : tout est appelé depuis `update_display()` (environ 100 ms) car l'API de Live n'est utilisable que
  sur son fil principal. Latence de commande de l'ordre de la tick.
- Aucun écouteur Live : les valeurs sont lues à la demande, et interrogées à chaque tick pour les clients qui
  font `LISTEN`. Pas d'écouteur à nettoyer.
- L'arbre est reconstruit (toutes les ~0,5 s si la signature change : pistes, scènes, dispositifs, dispositif
  sélectionné) et les clients reçoivent `PATH_ADDED` / `PATH_REMOVED`.
- WebSocket refusé si l'en-tête `Origin` n'est pas local (une page web quelconque ne peut pas piloter Live).
- Pas d'authentification : à utiliser sur un réseau de confiance.

## Tests

```
python3 -I tests/test_all.py
```
Un faux Live (`tests/mock_live.py`) et de vrais sockets : HTTP, attributs, écritures UDP, WebSocket LISTEN/IGNORE,
`PATH_REMOVED`, OSC par WebSocket, refus d'Origin.

## Pas encore fait / non vérifié

- **Jamais lancé dans un vrai Live** (pas installé sur cette machine) : les noms de l'API sont ceux de la
  documentation du modèle d'objets (Live 11/12), à valider. Code écrit pour Python 3.7 (Live 11) mais testé en 3.14.
- Pas de niveaux de sortie (meters), pas de MIDI/automation, pas de pistes de groupe dépliables.
- Annonce Bonjour : un répondeur mDNS en pur Python serait nécessaire pour Windows sans Bonjour.
- Les couleurs sont des entiers RGB (`i`), pas encore `r`.
- Réécritures d'index : supprimer une piste décale les chemins suivants (c'est le prix des chemins par index).
