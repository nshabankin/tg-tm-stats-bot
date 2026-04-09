from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueSpec:
    key: str
    site_id: str
    table_slug: str
    label: str
    button_label: str


ENGLAND_FLAG = (
    '\U0001F3F4'
    '\U000E0067'
    '\U000E0062'
    '\U000E0065'
    '\U000E006E'
    '\U000E0067'
    '\U000E007F'
)


LEAGUES = {
    'epl': LeagueSpec('epl', 'GB1', 'premier-league',
                      'Premier League', f'{ENGLAND_FLAG} Premier League'),
    'la_liga': LeagueSpec('la_liga', 'ES1', 'laliga',
                          'La Liga', '🇪🇸 La Liga'),
    'serie_a': LeagueSpec('serie_a', 'IT1', 'serie-a',
                          'Serie A', '🇮🇹 Serie A'),
    'bundesliga': LeagueSpec('bundesliga', 'L1', 'bundesliga',
                             'Bundesliga', '🇩🇪 Bundesliga'),
    'ligue_1': LeagueSpec('ligue_1', 'FR1', 'ligue-1',
                          'Ligue 1', '🇫🇷 Ligue 1'),
    'rpl': LeagueSpec('rpl', 'RU1', 'premier-liga',
                      'Russian Premier League', '🇷🇺 Russian Premier League'),
}

LEAGUE_KEYS = tuple(LEAGUES.keys())
