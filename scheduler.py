from rq import Queue, Worker, Connection
from worker import conn
from tmstats import GetData

q = Queue(connection=conn)
# run update in the background
epl = GetData.stats(GetData('epl', '2021'))
bundesliga = GetData.stats(GetData('bundesliga', '2021'))
serie_a = GetData.stats(GetData('serie_a', '2021'))
la_liga = GetData.stats(GetData('la_liga', '2021'))
ligue_1 = GetData.stats(GetData('ligue_1', '2021'))
rpl = GetData.stats(GetData('rpl', '2021'))

update_epl = q.enqueue(epl, 'epl', '2021')
update_bundesliga = q.enqueue(bundesliga, 'bundesliga', '2021')
update_serie_a = q.enqueue(serie_a, 'serie_a', '2021')
update_la_liga = q.enqueue(la_liga, 'la_liga', '2021')
update_ligue_1 = q.enqueue(ligue_1, 'ligue_1', '2021')
update_rpl = q.enqueue(rpl, 'rpl', '2021')

update = [update_epl, update_bundesliga, update_serie_a, update_la_liga,
          update_ligue_1, update_rpl]

with Connection(conn):
    for league in update:
        w = Worker(league)
        w.work()
