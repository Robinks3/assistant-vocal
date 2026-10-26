#!/usr/bin/env bash
# Garde-fou contre les fuites : secrets, données personnelles et gros binaires.
#   .githooks/garde-fou.sh --index       fichiers indexés (crochets pre-commit et pre-merge-commit)
#   .githooks/garde-fou.sh --pousse      commits envoyés (crochet pre-push, lit l'entrée standard de git)
#   .githooks/garde-fou.sh --historique  tout l'historique de toutes les branches, avant un partage
# Activation, une fois par clone : git config core.hooksPath .githooks
# Faux positif : ajouter le commentaire "garde-fou: ignorer" sur la ligne concernée (jamais valable pour
# les mots interdits ci-dessous).
# Mots interdits : config/mots-interdits.txt (fichier privé, ignoré par git), une chaîne par ligne, lignes vides et
# lignes commençant par # ignorées, casse ignorée. Chaque chaîne est refusée dans les chemins indexés et dans le
# contenu texte des lignes ajoutées. Fichier absent : avertissement sur stderr, les autres contrôles tournent.
# Contournement ponctuel, sur décision du propriétaire seulement : git commit --no-verify
# Les valeurs trouvées ne sont jamais affichées (les sorties des agents finissent dans des journaux).

set -u
export LC_ALL=C
cd "$(git rev-parse --show-toplevel)" || exit 1

TAILLE_MAX_MO=${GARDE_FOU_TAILLE_MAX_MO:-5}
TAILLE_MAX=$((TAILLE_MAX_MO * 1024 * 1024))

# Fichiers à ne jamais versionner, voir .gitignore. Les modèles (*.exemple) restent permis.
CHEMINS_INTERDITS='(^|/)\.env($|\.)|(^|/)local\.properties$|(^|/)keystore\.properties$|\.(jks|keystore|p12|pfx|pem|key|crt|cer|der|csr)$|(^|/)poc/tls/|(^|/)maison\.json$|^(config|maison)/|(^|/)poc/commandes\.yaml$|^android/app/src/main/assets/(dictionnaire\.json|maison3d/vue3d\.html)$|^carte/(pieces|meubles|lampes)\.json$|(^|/)journal/|(^|/)commandes_apprises\.yaml$|(^|/)dictionnaire_appris\.json$|(^|/)appareils\.json$|\.(apk|aab|apks)$|\.(wav|mp3|m4a|flac|ogg|opus|aac|amr|3gp|webm|mp4|mov|mkv|avi)$|\.(gguf|litertlm|safetensors|pt|pth|ckpt|npy|npz)$|\.(db|sqlite|sqlite3)$|(^|/)docs/captures/|(^|/)test-(canary|reveil)/'
CHEMINS_PERMIS='\.(exemple|example)$|^config-exemple/maison\.json$|^android/app/src/main/res/raw/ecoute_[a-z_]+\.wav$'

# Secrets reconnaissables à leur forme : jeton Home Assistant (JWT), clés Anthropic, OpenAI, GitHub,
# AWS, Slack, clés privées, et variables de poc/.env suivies d'une valeur en fin de ligne.
Q="[\"']"
MOTIFS_SECRETS="eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
MOTIFS_SECRETS+="|sk-ant-[A-Za-z0-9_-]{20,}|(^|[^A-Za-z0-9])sk-(proj-)?[A-Za-z0-9_-]{32,}"
MOTIFS_SECRETS+="|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}"
MOTIFS_SECRETS+="|-----BEGIN [A-Z ]*PRIVATE KEY-----"
MOTIFS_SECRETS+="|(HA_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|MISTRAL_API_KEY|STT_API_CLE|SANTE_JETON|SATELLITE_JETON[A-Z_]*)[[:space:]]*[=:][[:space:]]*$Q?[A-Za-z0-9._~+/=-]{8,}$Q?[[:space:]]*(\$|#)"
# Forme générique : mot-clé de secret suivi d'une longue valeur entre guillemets, hors valeurs de test.
MOTIF_GENERIQUE="(api[_-]?key|secret|token|password|passwd|mot_de_passe|jeton)$Q?[[:space:]]*[=:][[:space:]]*$Q[A-Za-z0-9._~+/=-]{20,}$Q"
MOTS_FACTICES='test|exemple|example|invent|faux|fake|dummy|xxx|changeme|placeholder'

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Mots interdits : une chaîne par ligne, sans espaces de bord, sans retour chariot.
FICHIER_MOTS=config/mots-interdits.txt
: > "$TMP/mots"
if [ -f "$FICHIER_MOTS" ]; then
    tr -d '' < "$FICHIER_MOTS" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -v -e '^$' -e '^#' > "$TMP/mots" || true
else
    echo "Garde-fou : $FICHIER_MOTS absent, les mots interdits ne sont pas contrôlés (seuls les contrôles génériques tournent)." >&2
fi
# Script sed qui masque chaque mot interdit dans les sorties.
sed -e 's/[][\.*^$/]/\\&/g' -e 's|.*|s/&/***/Ig|' "$TMP/mots" > "$TMP/masque.sed"

masquer() {
    if [ -s "$TMP/masque.sed" ]; then sed -f "$TMP/masque.sed"; else cat; fi
}

# Lignes ajoutées d'un diff, au format "[commit ]chemin:ligne<TAB>contenu".
lignes_ajoutees() {
    awk '
        /^commit / { c = $2 " "; next }
        /^diff --git / { entete = 1; next }
        entete && /^\+\+\+ / { f = substr($0, 7); entete = 0; next }
        /^@@ / { entete = 0; match($0, /\+[0-9]+/); n = substr($0, RSTART + 1, RLENGTH - 1) + 0; next }
        !entete && /^\+/ { print c f ":" n "\t" substr($0, 2); n++ }
    '
}

verifier() {
    # $1 : chemins (un par ligne), $2 : lignes ajoutées, $3 : gros fichiers déjà repérés
    grep -E "$CHEMINS_INTERDITS" "$1" | grep -v -E "$CHEMINS_PERMIS" | sort -u > "$TMP/r_chemins"
    grep -v 'garde-fou: ignorer' "$2" > "$TMP/lignes"
    {
        grep -E "$MOTIFS_SECRETS" "$TMP/lignes"
        grep -i -E "$MOTIF_GENERIQUE" "$TMP/lignes" | grep -v -i -E "$MOTS_FACTICES"
    } | cut -f1 | sort -u > "$TMP/r_secrets"
    : > "$TMP/r_mots_chemins"
    : > "$TMP/r_mots_lignes"
    if [ -s "$TMP/mots" ]; then
        LC_ALL=C.UTF-8 grep -i -F -f "$TMP/mots" "$1" | sort -u > "$TMP/r_mots_chemins"
        LC_ALL=C.UTF-8 grep -i -F -f "$TMP/mots" "$2" | cut -f1 | sort -u > "$TMP/r_mots_lignes"
    fi
    refus=0
    if [ -s "$TMP/r_mots_chemins" ]; then
        refus=1
        echo "Chemins qui contiennent un mot de $FICHIER_MOTS (mot masqué) :"
        masquer < "$TMP/r_mots_chemins" | sed 's/^/  /'
    fi
    if [ -s "$TMP/r_mots_lignes" ]; then
        refus=1
        echo "Lignes ajoutées qui contiennent un mot de $FICHIER_MOTS (mot masqué) :"
        masquer < "$TMP/r_mots_lignes" | sed 's/^/  /'
    fi
    if [ -s "$TMP/r_chemins" ]; then
        refus=1
        echo "Fichiers à ne jamais versionner (secrets, données personnelles, binaires produits) :"
        sed 's/^/  /' "$TMP/r_chemins"
    fi
    if [ -s "$TMP/r_secrets" ]; then
        refus=1
        echo "Motifs de secrets dans des lignes ajoutées (valeurs masquées) :"
        sed 's/^/  /' "$TMP/r_secrets"
    fi
    if [ -s "$3" ]; then
        refus=1
        echo "Fichiers de plus de $TAILLE_MAX_MO Mo (GitHub refuse au-delà de 100 Mo, et l'historique les garde pour toujours) :"
        sed 's/^/  /' "$3"
    fi
    return $refus
}

gros_objets() {
    # Objets de l'historique demandé ($@ : arguments de rev-list) au-delà de la limite.
    git rev-list --objects "$@" |
        git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' |
        awk -v m="$TAILLE_MAX" '$1 == "blob" && $2 > m { t = int($2 / 1048576); $1 = ""; $2 = ""; sub(/^  /, ""); print $0 " (" t " Mo)" }' |
        sort -u
}

verifier_plage() {
    # $@ : arguments de rev-list (plage de commits)
    git -c core.quotepath=false log --format= --name-only --diff-filter=AMR "$@" | sort -u > "$TMP/chemins"
    git -c core.quotepath=false log -p -U0 --no-color --no-ext-diff --format='commit %h' "$@" | lignes_ajoutees > "$TMP/ajouts"
    gros_objets "$@" > "$TMP/gros"
    verifier "$TMP/chemins" "$TMP/ajouts" "$TMP/gros"
}

case "${1:---index}" in
    --index)
        git -c core.quotepath=false diff --cached --name-only --diff-filter=ACMR > "$TMP/chemins"
        [ -s "$TMP/chemins" ] || exit 0
        git -c core.quotepath=false diff --cached -U0 --no-color --no-ext-diff --diff-filter=ACMR | lignes_ajoutees > "$TMP/ajouts"
        : > "$TMP/gros"
        git diff --cached --name-only -z --diff-filter=ACMR | while IFS= read -r -d '' f; do
            t=$(git cat-file -s ":$f" 2>/dev/null) || continue
            [ "$t" -gt "$TAILLE_MAX" ] && echo "$f ($((t / 1048576)) Mo)" >> "$TMP/gros"
        done
        if ! verifier "$TMP/chemins" "$TMP/ajouts" "$TMP/gros"; then
            echo
            echo "Garde-fou : commit refusé. Retirer ces éléments de l'index (git restore --staged <fichier>)."
            if grep -q -E '(^|/)\.env($|\.)' "$TMP/r_chemins"; then
                # Un .env indexé : le retirer du suivi, il garde les secrets sur la machine.
                echo "Un fichier .env déjà suivi se retire par git rm --cached <fichier>."
            fi
            [ -s "$TMP/r_secrets" ] && echo "Mettre les secrets dans poc/.env."
            echo "Puis recommencer."
            exit 1
        fi
        ;;
    --pousse)
        statut=0
        while read -r ref_locale sha_local ref_distante sha_distant; do
            case "$sha_local" in *[!0]*) ;; *) continue ;; esac
            case "$sha_distant" in
                *[!0]*) if git cat-file -e "$sha_distant^{commit}" 2>/dev/null; then plage=("$sha_local" "^$sha_distant"); else plage=("$sha_local" --not --remotes); fi ;;
                *) plage=("$sha_local" --not --remotes) ;;
            esac
            if ! verifier_plage "${plage[@]}"; then
                echo
                echo "Garde-fou : envoi de $ref_locale vers $ref_distante refusé. Un commit envoyé contient ce qui précède."
                echo "Le retirer des commits à envoyer (git commit --amend, ou git rebase sur les commits pas encore envoyés), ne pas contourner."
                statut=1
            fi
        done
        exit $statut
        ;;
    --historique)
        if verifier_plage --all; then
            echo "Garde-fou : rien trouvé dans l'historique de toutes les branches."
        else
            echo
            echo "Garde-fou : l'historique contient ce qui précède. Ne pas partager ce dépôt tel quel : publier un instantané sans historique."
            exit 1
        fi
        ;;
    *)
        echo "Usage : $0 [--index | --pousse | --historique]" >&2
        exit 2
        ;;
esac
