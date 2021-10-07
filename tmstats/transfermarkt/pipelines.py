# Define your item pipelines here
#
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html
# useful for handling different item types with a single interface


class PlayerPipeline:
    # noinspection PyMethodMayBeStatic, PyUnusedLocal
    def process_item(self, item, spider):
        player_name = item['player_name']
        if len(player_name) == 2:  # <-- For first and last names
            item['player_name'] = player_name[0] + player_name[1]
            return item
        else:  # <-- There could be a player with a one-word name
            return item
