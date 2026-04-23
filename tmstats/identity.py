import re
from typing import Dict, Iterable, List


def normalize_text(value) -> str:
    if value is None:
        return ''
    return ' '.join(str(value).replace('\xa0', ' ').split())


def club_identity(value: str) -> str:
    normalized = normalize_text(value).lower()
    return re.sub(r'[^a-z0-9]+', '', normalized)


CLUB_ALIASES: Dict[str, List[str]] = {
    'afcbournemouth': ['bournemouth'],
    'arsenalfc': ['arsenal'],
    'brightonhovealbion': ['brighton', 'brightonhove'],
    'brentfordfc': ['brentford'],
    'evertonfc': ['everton'],
    'leedsunited': ['leeds'],
    'liverpoolfc': ['liverpool'],
    'manchestercity': ['mancity'],
    'manchesterunited': ['manutd', 'manunited'],
    'newcastleunited': ['newcastle'],
    'nottinghamforest': ['nottmforest', 'nottmforest'],
    'sunderlandafc': ['sunderland'],
    'tottenhamhotspur': ['tottenham'],
    'westhamunited': ['westham'],
    'wolverhamptonwanderers': ['wolves'],
    'fckrasnodar': ['krasnodar', 'krsndr'],
    'fcparinizhniynovgorod': ['pari', 'parinn'],
    'dynamomoscow': ['dynamo'],
    'dinamomakhachkala': ['dinm', 'dinamomakhach', 'dinamomakhachk'],
    'akhmatgrozny': ['akhmat'],
    'fcsochi': ['fksochi', 'sochi'],
    'rubinkazan': ['rubin'],
    'lokomotivmoscow': ['loko', 'lokomoscow'],
    'zenitstpetersburg': ['zenit', 'zenitspb'],
    'baltikakaliningrad': ['balt', 'baltika'],
    'akrontolyatti': ['akron'],
    'krylyasovetovsamara': ['kssamara', 'samara'],
    'atalantabc': ['atalanta'],
    'bolognafc1909': ['bolo', 'bologna'],
    'cagliaricalcio': ['caglia', 'cagliari'],
    'intermilan': ['inter'],
    'juventusfc': ['juve', 'juventus'],
    'sscnapoli': ['napoli'],
    'udinesecalcio': ['udine', 'udinese'],
    'ussassuolo': ['sassuo', 'sassuolo'],
    'hellasverona': ['hellas'],
    'acfiorentina': ['fiorentina'],
    'parmacalcio1913': ['parma'],
    'uscremonese': ['cremonese'],
    'uslecce': ['lecce'],
    'athleticbilbao': ['athleticclub'],
    'fcbarcelona': ['barca', 'bara'],
    'parissaintgermain': ['psg'],
}

ALIAS_TO_CANONICAL = {
    alias: canonical
    for canonical, aliases in CLUB_ALIASES.items()
    for alias in aliases
}


def canonical_club_identity(value: str) -> str:
    identity = club_identity(value)
    return ALIAS_TO_CANONICAL.get(identity, identity)


def dedupe_team_names(names: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    seen_indices: Dict[str, int] = {}

    for raw_name in names:
        name = normalize_text(raw_name)
        if not name:
            continue
        identity = canonical_club_identity(name)
        if not identity:
            continue
        existing_index = seen_indices.get(identity)
        if existing_index is None:
            seen_indices[identity] = len(deduped)
            deduped.append(name)
            continue

        if len(name) > len(deduped[existing_index]):
            deduped[existing_index] = name

    return deduped


def name_tokens(value: str) -> List[str]:
    return [
        token for token in re.split(r'[^a-z0-9]+', normalize_text(value).casefold())
        if token
    ]


def names_loosely_match(left: str, right: str) -> bool:
    left_tokens = name_tokens(left)
    right_tokens = name_tokens(right)
    if not left_tokens or not right_tokens:
        return False

    if all(
        any(
            left_token.startswith(right_token)
            or right_token.startswith(left_token)
            for right_token in right_tokens
        )
        for left_token in left_tokens
    ):
        return True

    if all(
        any(
            left_token.startswith(right_token)
            or right_token.startswith(left_token)
            for left_token in left_tokens
        )
        for right_token in right_tokens
    ):
        return True

    return False
