from dataclasses import dataclass


@dataclass(frozen=True)
class LeagueSpec:
    key: str
    site_id: str
    table_slug: str
    label: str
    button_label: str
    logo_url: str
    tm_scope: str = 'wettbewerb'
    family: str = 'domestic'
    table_label: str = 'Table'
    supports_bracket: bool = False
    supports_third_place: bool = False
    default_season_start_year: int = None

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
    'ucl': LeagueSpec('ucl', 'CL', 'champions-league',
                      'Champions League', 'Champions League',
                      competition_logo_url('CL'),
                      tm_scope='pokalwettbewerb',
                      family='uefa',
                      table_label='League Phase',
                      supports_bracket=True),
    'uel': LeagueSpec('uel', 'EL', 'europa-league',
                      'Europa League', 'Europa League',
                      competition_logo_url('EL'),
                      tm_scope='pokalwettbewerb',
                      family='uefa',
                      table_label='League Phase',
                      supports_bracket=True),
    'uecl': LeagueSpec('uecl', 'UCOL', 'uefa-conference-league',
                       'Conference League', 'Conference League',
                       competition_logo_url('UCOL'),
                       tm_scope='pokalwettbewerb',
                       family='uefa',
                       table_label='League Phase',
                       supports_bracket=True),
    'world_cup': LeagueSpec('world_cup', 'FIWC', 'world-cup',
                            'World Cup 2026', 'World Cup',
                            competition_logo_url('FIWC'),
                            tm_scope='pokalwettbewerb',
                            family='international_tournament',
                            table_label='Groups',
                            supports_bracket=True,
                            supports_third_place=True,
                            default_season_start_year=2025),
}

LEAGUE_KEYS = tuple(LEAGUES.keys())
