# Import scrapy library
import json
import scrapy
from itemloaders import ItemLoader
from itemloaders.processors import MapCompose, Join, SelectJmes
from getfootballstats.tmstats.transfermarkt.items import Leagueitem
from getfootballstats.tmstats.transfermarkt.settings import league_fields


# Create the spider class
class Leaguespider(scrapy.Spider):

    name = 'leaguespider'
    custom_settings = {'FEED_EXPORT_FIELDS': league_fields}
    jmes_paths = {'id': 'id',
                  'name': 'name',
                  'link': 'link'}

    def __init__(self, league_site=None, *args, **kwargs):
        super(Leaguespider, self).__init__(*args, **kwargs)
        self.start_urls = f'https://www.transfermarkt.com/' \
                          f'quickselect/teams/{str(league_site)}'
        # scrapy crawl leaguespider -a league=<..>

    # start_requests method
    def start_requests(self):
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:48.0) '
                          'Gecko/20100101 Firefox/48.0'}
        yield scrapy.Request(url=self.start_urls,
                             headers=headers,
                             callback=self.parse)

    # parse method
    def parse(self, response, **kwargs):

        jsonresponse = json.loads(response.text)

        for club in jsonresponse:
            loader = ItemLoader(item=Leagueitem())
            loader.default_input_processor = MapCompose(str)
            loader.default_output_processor = Join(' ')

            for (field, path) in self.jmes_paths.items():
                loader.add_value(field, SelectJmes(path)(club))

            yield loader.load_item()
