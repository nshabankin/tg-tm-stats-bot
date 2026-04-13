from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueSpec:
    key: str
    site_id: str
    table_slug: str
    label: str
    button_label: str
    logo_url: str

def competition_logo_url(site_id: str) -> str:
    return (
        'https://tmssl.akamaized.net//images/logo/homepageWappen150x150/'
        f'{site_id.lower()}.png'
    )


LEAGUES = {
    'epl': LeagueSpec('epl', 'GB1', 'premier-league',
                      'Premier League', 'Premier League',
                      competition_logo_url('GB1')),
    'la_liga': LeagueSpec('la_liga', 'ES1', 'laliga',
                          'La Liga', 'La Liga',
                          competition_logo_url('ES1')),
    'serie_a': LeagueSpec('serie_a', 'IT1', 'serie-a',
                          'Serie A', 'Serie A',
                          competition_logo_url('IT1')),
    'bundesliga': LeagueSpec('bundesliga', 'L1', 'bundesliga',
                             'Bundesliga', 'Bundesliga',
                             competition_logo_url('L1')),
    'ligue_1': LeagueSpec('ligue_1', 'FR1', 'ligue-1',
                          'Ligue 1', 'Ligue 1',
                          competition_logo_url('FR1')),
    'rpl': LeagueSpec('rpl', 'RU1', 'premier-liga',
                      'Russian Premier League', 'Russian Premier League',
                      competition_logo_url('RU1')),
}

LEAGUE_KEYS = tuple(LEAGUES.keys())
