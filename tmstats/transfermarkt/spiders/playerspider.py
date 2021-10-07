import pandas as pd
import scrapy
from ..items import Playeritem, GKitem
from ..settings import player_fields


# Create the spider class
# noinspection PyMethodMayBeStatic
class Playerspider(scrapy.Spider):
    name = 'playerspider'
    # set export fields and pipeline to modify name column
    custom_settings = {'FEED_EXPORT_FIELDS': player_fields,
                       'ITEM_PIPELINES': {
                           'transfermarkt.pipelines.PlayerPipeline': 100}
                       }

    def __init__(self, league=None, year=None, *args, **kwargs):
        super(Playerspider, self).__init__(*args, **kwargs)
        site = 'https://www.transfermarkt.com/'
        # get DataFrame with league players and links to their profiles
        links = pd.read_csv(f'{str(league)}/'
                            f'{str(league)}_players_{str(year)}.csv',
                            usecols=['id', 'name', 'positionId', 'link'],
                            dtype='str')
        # extract names as in the links
        links['url_name'] = [link.split('/')[1] for link in links['link']]
        for name in links['name'].values:
            # slice a row for a single player
            player = links.loc[links['name'] == name]
            player_id = player['id']
            player_name = player['url_name']
            player_position = player['positionId'].values[0]
            # make individual player's URL to overall stats page
            player_url = f'{site}{player_name.values[0]}/leistungsdaten/' \
                         f'spieler/{player_id.values[0]}/plus/0?' \
                         f'saison={str(year)}'
            # join individual URLs with position IDs to identify Goalkeepers
            self.start_urls.append([player_url, player_position])
    # use shell command:scrapy crawl playerspider -a league=<..> -a year=<..>

    # start_requests method
    def start_requests(self):
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:48.0) '
                          'Gecko/20100101 Firefox/48.0'}
        # separate Goalkeepers from others with position ID
        for u in self.start_urls:
            if u[1] == '1':
                yield scrapy.Request(url=u[0],
                                     headers=headers,
                                     callback=self.gkparse)
            else:
                yield scrapy.Request(url=u[0],
                                     headers=headers,
                                     callback=self.parse)

    # par+e method for goalkeepers: with "conceded" and "clean sheets" fields
    def gkparse(self, response, **kwargs):
        items = GKitem()
        body = '//*[@id="yw2"]/table/tbody/tr[1]'
        items['player_name'] = response.xpath(
            '//h1[@itemprop="name"]//text()').extract()
        items['number'] = response.xpath(
            '//span[@class="dataRN"]//text()').extract()
        items['position'] = response.xpath(
            '//div[2]/p[2]/'
            'span[@class="dataValue"]//text()').extract()[0].strip()
        items['club'] = response.xpath(
            '//span[@class="hauptpunkt"]//text()').extract()
        items['league'] = response.xpath(
            body + '/td[2]/a/text()').extract()
        items['played'] = response.xpath(
            body + '/td[3]/a/text()').extract()
        items['goals'] = response.xpath(
            body + '/td[4]/text()').extract()
        items['yellow_cards'] = response.xpath(
            body + '/td[5]/text()').extract()
        items['second_yellows'] = response.xpath(
            body + '/td[6]/text()').extract()
        items['red_cards'] = response.xpath(
            body + '/td[7]/text()').extract()
        items['conceded'] = response.xpath(
            body + '/td[8]/text()').extract()
        items['clean_sheets'] = response.xpath(
            body + '/td[9]/text()').extract()
        items['minutes'] = response.xpath(
            body + '/td[10]/text()').extract()
        yield items

    # parse method for field players
    def parse(self, response, **kwargs):
        items = Playeritem()
        body = '//*[@id="yw2"]/table/tbody/tr[1]'
        items['player_name'] = response.xpath(
            '//h1[@itemprop="name"]//text()').extract()
        items['number'] = response.xpath(
            '//span[@class="dataRN"]//text()').extract()
        items['position'] = response.xpath(
            '//div[2]/p[2]/'
            'span[@class="dataValue"]//text()').extract()[0].strip()
        items['club'] = response.xpath(
            '//span[@class="hauptpunkt"]//text()').extract()
        items['league'] = response.xpath(
            body + '/td[2]/a/text()').extract()
        items['played'] = response.xpath(
            body + '/td[3]/a/text()').extract()
        items['goals'] = response.xpath(
            body + '/td[4]/text()').extract()
        items['assists'] = response.xpath(
            body + '/td[5]/text()').extract()
        items['yellow_cards'] = response.xpath(
            body + '/td[6]/text()').extract()
        items['second_yellows'] = response.xpath(
            body + '/td[7]/text()').extract()
        items['red_cards'] = response.xpath(
            body + '/td[8]/text()').extract()
        items['minutes'] = response.xpath(
            body + '/td[9]/text()').extract()
        yield items
