# Import scrapy library
import json

import pandas as pd
import scrapy
from itemloaders import ItemLoader
from itemloaders.processors import MapCompose, Join, SelectJmes
from ..items import Teamitem
from ..settings import team_fields


# Create the spider class
class Teamspider(scrapy.Spider):

    name = 'teamspider'
    custom_settings = {'FEED_EXPORT_FIELDS': team_fields}
    jmes_paths = {'id': 'id',
                  'name': 'name',
                  'shirtNumber': 'shirtNumber',
                  'positionId': 'positionId',
                  'link': 'link'}

    def __init__(self, league=None, year=None, *args, **kwargs):
        super(Teamspider, self).__init__(*args, **kwargs)
        site = 'https://www.transfermarkt.com/quickselect/players/'
        links = pd.read_csv(f'{str(league)}/'
                            f'{str(league)}_teams_{str(year)}.csv',
                            usecols=['id'],
                            dtype='str')
        self.start_urls = [(site + link) for link in links['id']]
        # scrapy crawl Teamspider -a league=epl

    # start_requests method
    def start_requests(self):
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:48.0) '
                          'Gecko/20100101 Firefox/48.0'}
        for url in self.start_urls:
            yield scrapy.Request(url=url,
                                 headers=headers,
                                 callback=self.parse)

    # parse method
    def parse(self, response, **kwargs):

        jsonresponse = json.loads(response.text)

        for player in jsonresponse:
            loader = ItemLoader(item=Teamitem())
            loader.default_input_processor = MapCompose(str)
            loader.default_output_processor = Join(' ')

            for (field, path) in self.jmes_paths.items():
                loader.add_value(field, SelectJmes(path)(player))

            yield loader.load_item()
