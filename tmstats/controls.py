import os
import pathlib
from scrapy.crawler import CrawlerProcess
from .transfermarkt.spiders import Playerspider, Teamspider, \
    Tablespider, Leaguespider
from scrapy.utils.project import get_project_settings
from .transfermarkt.settings import team_fields, table_fields, \
    league_fields, player_fields


class GetData:

    def __init__(self, league=None, year=None):
        self.league = league
        self.year = year
        # make a dict with league names and their URL aliases
        self.leagues = {'epl': 'GB1',
                        'serie_a': 'IT1',
                        'la_liga': 'ES1',
                        'bundesliga': 'L1',
                        'ligue_1': 'FR1',
                        'liga_bwin': 'PO1',
                        'rpl': 'RU1',
                        'eredivisie': 'NL1'}

        self.tables = {'epl': 'premier-league',
                       'serie_a': 'serie-a',
                       'la_liga': 'laliga',
                       'bundesliga': 'bundesliga',
                       'ligue_1': 'ligue-1',
                       'liga_bwin': 'liga-nos',
                       'rpl': 'premier-liga',
                       'eredivisie': 'eredivisie'}

    def teams(self):
        """
        Runs the spider to export the list of teams and their URLs to .csv
        :return:

        """
        settings_teams = get_project_settings()
        # set export fields for teams table
        settings_teams['FEED_EXPORT_FIELDS'] = league_fields
        # set filepath and filename for the .csv output
        settings_teams['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_teams_{str(self.year)}.csv'):  # file name
                                       {'format': 'csv',  # format
                                        'overwrite': True}}
        # process_teams
        process = CrawlerProcess(settings_teams)
        process.crawl(Leaguespider,
                      input='inputargument',
                      # put a short league alias as the only argument
                      league_site=self.leagues[self.league])
        process.start()

    def table(self):
        """
        Runs the spider to export the list of teams and their URLs to .csv
        :return:

        """
        settings_table = get_project_settings()
        # set export fields for teams table
        settings_table['FEED_EXPORT_FIELDS'] = table_fields
        # set filepath and filename for the .csv output
        settings_table['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_table_{str(self.year)}.csv'):  # file name
                                       {'format': 'csv',  # format
                                        'overwrite': True}}
        # process_teams
        process = CrawlerProcess(settings_table)
        process.crawl(Tablespider,
                      input='inputargument',
                      # put a short league alias as the only argument
                      table=self.tables[self.league],
                      league_site=self.leagues[self.league],
                      year=self.year)
        process.start()

    def players(self):
        settings_players = get_project_settings()
        # set export fields for players table
        settings_players['FEED_EXPORT_FIELDS'] = team_fields
        # set filepath and filename for the .csv output
        settings_players['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_players_{str(self.year)}.csv'):  # file name
                                         {'format': 'csv',  # format
                                          'overwrite': True}}
        # process_players
        process = CrawlerProcess(settings_players)
        process.crawl(Teamspider,
                      input='inputargument',
                      # league name and year as arguments
                      league=self.league,
                      year=self.year)
        process.start()

    def stats(self):
        settings_stats = get_project_settings()
        # set export fields for stats table
        settings_stats['FEED_EXPORT_FIELDS'] = player_fields
        # set filepath and filename for the .csv output
        settings_stats['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_stats_{str(self.year)}.csv'):  # file name
                                       {'format': 'csv',  # format
                                        'overwrite': True}}
        # process_stats
        process = CrawlerProcess(settings_stats)
        process.crawl(Playerspider,
                      input='inputargument',
                      # league name and year as arguments
                      league=self.league,
                      year=self.year)
        process.start()

    def list_files(self, startpath='D:/Python Projects/'
                                   'Football Stats Parsing'):
        with open('dirs.txt', 'w') as d:
            for root, dirs, files in os.walk(startpath):
                level = root.replace(startpath, '').count(os.sep)
                indent = ' ' * 4 * level
                print(f'{indent}{os.path.basename(root)}/')
                subindent = ' ' * 4 * (level + 1)
                for f in files:
                    print(f'{subindent}{f}')
        d.write('dirs')
        return self
