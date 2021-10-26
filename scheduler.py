from rq import Queue, Worker, Connection
from worker import conn
from tmstats import GetData

q = Queue(connection=conn)
# run update in the background
update_epl = q.enqueue(GetData.stats(self=GetData(
    'epl', '2021')),
    'epl', '2021')
update_bundesliga = q.enqueue(GetData.stats(self=GetData(
    'bundesliga', '2021')),
    'bundesliga', '2021')
update_serie_a = q.enqueue(GetData.stats(self=GetData(
    'serie_a', '2021')),
    'serie_a', '2021')
update_la_liga = q.enqueue(GetData.stats(self=GetData(
    'la_liga', '2021')),
    'la_liga', '2021')
update_ligue_1 = q.enqueue(GetData.stats(self=GetData(
    'ligue_1', '2021')),
    'ligue_1', '2021')
update_rpl = q.enqueue(GetData.stats(self=GetData(
    'rpl', '2021')),
    'rpl', '2021')

update = [update_epl, update_bundesliga, update_serie_a, update_la_liga,
          update_ligue_1, update_rpl]
with Connection(conn):
    for league in update:
        w = Worker(league)
        w.work()
