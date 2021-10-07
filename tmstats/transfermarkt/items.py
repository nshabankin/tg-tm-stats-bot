# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class Leagueitem(scrapy.Item):
    id = scrapy.Field()
    name = scrapy.Field()
    link = scrapy.Field()


class Tableitem(scrapy.Item):
    rank = scrapy.Field()
    club = scrapy.Field()
    played = scrapy.Field()
    wins = scrapy.Field()
    draws = scrapy.Field()
    losses = scrapy.Field()
    goals = scrapy.Field()
    diff = scrapy.Field()
    points = scrapy.Field()


class Teamitem(scrapy.Item):
    id = scrapy.Field()
    name = scrapy.Field()
    shirtNumber = scrapy.Field()
    positionId = scrapy.Field()
    link = scrapy.Field()


class Playeritem(scrapy.Item):
    player_name = scrapy.Field()
    number = scrapy.Field()
    position = scrapy.Field()
    club = scrapy.Field()
    league = scrapy.Field()
    played = scrapy.Field()
    goals = scrapy.Field()
    assists = scrapy.Field()
    yellow_cards = scrapy.Field()
    second_yellows = scrapy.Field()
    red_cards = scrapy.Field()
    minutes = scrapy.Field()


class GKitem(scrapy.Item):
    player_name = scrapy.Field()
    number = scrapy.Field()
    position = scrapy.Field()
    club = scrapy.Field()
    league = scrapy.Field()
    played = scrapy.Field()
    goals = scrapy.Field()
    yellow_cards = scrapy.Field()
    second_yellows = scrapy.Field()
    red_cards = scrapy.Field()
    conceded = scrapy.Field()
    clean_sheets = scrapy.Field()
    minutes = scrapy.Field()
