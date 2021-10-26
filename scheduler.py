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
with Connection(conn):
    w = Worker(update_epl)
    w.work()
update_bundesliga = q.enqueue(bundesliga, 'bundesliga', '2021')
with Connection(conn):
    w = Worker(update_bundesliga)
    w.work()
update_serie_a = q.enqueue(serie_a, 'serie_a', '2021')
with Connection(conn):
    w = Worker(update_serie_a)
    w.work()
update_la_liga = q.enqueue(la_liga, 'la_liga', '2021')
with Connection(conn):
    w = Worker(update_la_liga)
    w.work()
update_ligue_1 = q.enqueue(ligue_1, 'ligue_1', '2021')
with Connection(conn):
    w = Worker(update_ligue_1)
    w.work()
update_rpl = q.enqueue(rpl, 'rpl', '2021')
with Connection(conn):
    w = Worker(update_rpl)
    w.work()
update = [update_epl, update_bundesliga, update_serie_a, update_la_liga,
          update_ligue_1, update_rpl]
