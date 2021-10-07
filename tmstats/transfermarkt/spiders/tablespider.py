# Import modules
import scrapy
from ..items import Tableitem
from ..settings import table_fields


class Tablespider(scrapy.Spider):

    name = 'tablespider'

    # set export fields and pipeline to modify name column
    custom_settings = {'FEED_EXPORT_FIELDS': table_fields,
                       'ROBOTSTXT_OBEY': False}

    def __init__(self, table=None, league_site=None, year=None,
                 *args, **kwargs):
        super(Tablespider, self).__init__(*args, **kwargs)
        self.start_urls = f'https://www.transfermarkt.com/' \
                          f'{str(table)}/spieltagtabelle/' \
                          f'wettbewerb/{str(league_site)}/' \
                          f'saison_id/{str(year)}'
        # scrapy crawl tablespider -a league=<..>

    # start_requests method
    def start_requests(self):
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:48.0) '
                          'Gecko/20100101 Firefox/48.0'}
        yield scrapy.Request(url=self.start_urls,
                             headers=headers,
                             callback=self.parse)

    # parse method for field players
    def parse(self, response, **kwargs):
        # set table body XPath
        body = '//*[@id="main"]/div[10]/div[1]/div[3]/table/tbody/'
        # get list of teams in the league
        teams = response.xpath(body + '/tr/td[3]/a/text()').extract()
        items = []  # empty list for every row of items
        item = Tableitem()  # an items is a row of the table
        for row in range(1, len(teams) + 1):  # iterate over every team
            item['rank'] = response.xpath(
                body + f'tr[{row}]/td[1]/text()').extract()
            item['club'] = response.xpath(
                body + f'tr[{row}]/td[3]/a/text()').extract()
            item['played'] = response.xpath(
                body + f'tr[{row}]/td[4]/text()').extract()
            item['wins'] = response.xpath(
                body + f'tr[{row}]/td[5]/text()').extract()
            item['draws'] = response.xpath(
                body + f'tr[{row}]/td[6]/text()').extract()
            item['losses'] = response.xpath(
                body + f'tr[{row}]/td[7]/text()').extract()
            item['goals'] = response.xpath(
                body + f'tr[{row}]/td[8]/text()').extract()
            item['diff'] = response.xpath(
                body + f'tr[{row}]/td[9]/text()').extract()
            item['points'] = response.xpath(
                body + f'tr[{row}]/td[10]/text()').extract()
            yield item
            items.append(item)
