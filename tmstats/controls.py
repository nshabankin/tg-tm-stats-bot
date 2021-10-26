import pathlib
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from .transfermarkt import settings

#from transfermarkt.settings import team_fields, table_fields, league_fields, \
#    player_fields
from .transfermarkt.spiders.leaguespider import Leaguespider
from .transfermarkt.spiders.teamspider import Teamspider
from .transfermarkt.spiders.playerspider import Playerspider
from .transfermarkt.spiders.tablespider import Tablespider
import sys
sys.path.append('D:/Python Projects/tg-tm-stats-bot/'
                'getfootballstats/tmstats/')


class GetData:

    def __init__(self, league=None, year=None):
        """
        Receive a league name and a year to process throughout.
        """
        self.league = league
        self.year = year

        # make a dict with league names and their URL shortcuts
        self.leagues = {'epl': 'GB1',
                        'serie_a': 'IT1',
                        'la_liga': 'ES1',
                        'bundesliga': 'L1',
                        'ligue_1': 'FR1',
                        'liga_bwin': 'PO1',
                        'rpl': 'RU1',
                        'eredivisie': 'NL1'}

        # make a dict with league names and their URL aliases
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
        Run the spider to export a list of teams and their URLs to .csv,
        thus forming a pool of URLs for the next spider to crawl over.
        """
        settings_teams = get_project_settings()  # from settings.py
        # set export fields for teams
        settings_teams['FEED_EXPORT_FIELDS'] = settings.league_fields
        # set filepath and filename for the .csv output
        settings_teams['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_teams_{str(self.year)}.csv'):  # file name
                                       {'format': 'csv',  # format
                                        'overwrite': True}}  # allow overwrite
        # process_teams
        process = CrawlerProcess(settings_teams)
        process.crawl(Leaguespider,  # refer to the spider for teams crawling
                      input='inputargument',
                      # receive from leagues dict with league as the key
                      league_site=self.leagues[self.league])
        process.start()

    def table(self):
        """
        Run the spider to export an up-to-date league table in a .csv file.
        """
        settings_table = get_project_settings()  # from settings.py
        # set export fields for league table
        settings_table['FEED_EXPORT_FIELDS'] = settings.table_fields
        # set filepath and filename for the .csv output
        settings_table['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_table_{str(self.year)}.csv'):  # file name
                                       {'format': 'csv',  # format
                                        'overwrite': True}}  # allow overwrite
        # process_teams
        process = CrawlerProcess(settings_table)
        process.crawl(Tablespider,  # refer to the spider for table crawling
                      input='inputargument',
                      # received from the tables dict with league as the key
                      table=self.tables[self.league],
                      # received from leagues dict with league as the key
                      league_site=self.leagues[self.league],
                      # received with class initiation
                      year=self.year)
        process.start()

    def players(self):
        """
        Form a .csv table with every player URLs for the next spider
        to crawl over.
        """
        settings_players = get_project_settings()  # from settings.py
        # set export fields for players table
        settings_players['FEED_EXPORT_FIELDS'] = settings.team_fields
        # set filepath and filename for the .csv output
        settings_players['FEEDS'] = {pathlib.Path(
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_players_{str(self.year)}.csv'):  # file name
                                         {'format': 'csv',  # format
                                          'overwrite': True}}
        # process_players
        process = CrawlerProcess(settings_players)
        process.crawl(Teamspider,  # refer to the spider for players crawling
                      input='inputargument',
                      # league name and year as arguments
                      league=self.league,
                      year=self.year)
        process.start()

    def stats(self):
        """
        Crawl over the list of players and return their stats in a .csv file.
        """
        settings_stats = get_project_settings()  # from settings.py
        # set export fields for player stats
        settings_stats['FEED_EXPORT_FIELDS'] = settings.player_fields
        # set filepath and filename for the .csv output
        settings_stats['FEEDS'] = {pathlib.Path(
            f'tmstats/'
            f'{str(self.league)}/'  # folder name
            f'{str(self.league)}_stats_{str(self.year)}.csv'):  # file name
                                       {'format': 'csv',  # format
                                        'overwrite': True}}
        # process_stats
        process = CrawlerProcess(settings_stats)
        process.crawl(Playerspider,  # refer to the spider for player stats
                      input='inputargument',
                      # league name and year as arguments
                      league=self.league,
                      year=self.year)
        process.start()
