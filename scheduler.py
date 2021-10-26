from rq import Queue, Worker, Connection
from worker import conn
from tmstats.controls import GetData

q = Queue(connection=conn)
# run update in the background
update = q.enqueue(GetData.stats(self=GetData('serie_a', '2021')),
                   'serie_a', '2021')

with Connection(conn):
    w = Worker(update)
    w.work()
