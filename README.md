# AI NEWSPOST

### Sources

HN: official Firebase/Algolia API, or filtered RSS (hnrss.org with points thresholds and AI keywords)
Arize blog, DeepLearning.ai The Batch, Edith Yeung’s newsletter: RSS/Substack/Beehiiv feeds
Frontier lab research pages (OpenAI, Anthropic, DeepMind, Meta AI, etc.): some have RSS, others don’t, so these need a small scraper or a “page-change watcher”


## Setup Commands

uv sync

uv run playwright install chromium 

docker compose up -d

### Check that the container is up and the schema was applied.
docker exec -it ai-digest-db psql -U digest -d digest -c "\dt"

---

## Other Commands

### Check config file
uv run python -c "from digest.config import load_sources; print(load_sources())"

### Check that db file
uv run python -c "from digest import db; c = db.connect(); print(c.execute('select count(*) from items').fetchone()); c.close()"

### Check LLm file
uv run python -c "from digest import llm; v=llm.embed_one('hello'); print(len(v)); print(llm.usage_report())"

### Check HN
uv run python -c "from digest.config import load_sources; from digest.ingest import hn; src=[s for s in load_sources() if s['id']=='hn'][0]; items=hn.fetch(src); print(len(items)); [print(i['points'], i['title']) for i in items[:5]]"

### Check HN+DB
uv run python -c "from digest import db; from digest.config import load_sources; from digest.ingest import hn; src=[s for s in load_sources() if s['id']=='hn'][0]; items=hn.fetch(src); c=db.connect(); db.sync_sources(c, load_sources()); n=sum(1 for i in items if db.insert_item(c,i)); db.record_fetch(c,'hn','ok',len(items)); c.commit(); c.close(); print(n,'saved')"

### Test Feed Sources
(ai-digest) D:\SCRIPTS\ainewspost>uv run python -c "import feedparser; [print(u, '|', len((d:=feedparser.parse(u)).entries), 'entries | status', d.get('status'), '|', d.get('bozo_exception')) for u in ['https://openai.com/news/rss.xml','https://deepmind.google/blog/feed/basic/','https://edithyeung.substack.com/feed','https://arize.com/blog/feed/']]"

```text
https://openai.com/news/rss.xml | 1259 entries | status 200 | None
https://deepmind.google/blog/feed/basic/ | 100 entries | status 302 | document declared as us-ascii, but parsed as utf-8
https://edithyeung.substack.com/feed | 20 entries | status 200 | None
https://arize.com/blog/feed/ | 10 entries | status 200 | None

```

### Check RSS+DB
uv run python -c "from digest import db; from digest.config import load_sources; from digest.ingest import rss; c=db.connect(); db.sync_sources(c, load_sources(include_todo=True)); [print(s['id'], sum(1 for i in rss.fetch(s) if db.insert_item(c,i)), 'saved') for s in load_sources() if s['type']=='rss']; c.commit(); c.close()"

### Check Extraction
uv run python -c "from digest import db, extract; c=db.connect(); print(extract.extract_pending(c)); c.commit(); c.close()"

### Check Extraction Docker
docker exec -it ai-digest-db psql -U digest -d digest -c "select source_id, count(*) filter (where content <> '') as with_text, count(*) filter (where content = '') as empty, count(*) filter (where content is null) as pending from items group by 1"

### Check Empty items in DB
docker exec -it ai-digest-db psql -U digest -d digest -c "select url from items where content = ''"


### Check AI Clustering
#### with llm usage reporting
uv run python -c "from digest import db, dedup, llm; c=db.connect(); print(dedup.embed_pending(c)); print(dedup.cluster_new_items(c)); c.commit(); c.close(); print(llm.usage_report())"

#### without llm usage reporting
uv run python -c "from digest import db, dedup; c=db.connect(); print(dedup.embed_pending(c)); print(dedup.cluster_new_items(c)); c.commit(); c.close()"

### View merged clusters
docker exec -it ai-digest-db psql -U digest -d digest -c "select cluster_id, count(*) n, string_agg(left(title,40), ' | ') from items group by 1 having count(*)>1"


### Check Closest Pairs
docker exec -it ai-digest-db psql -U digest -d digest -c "select round((1-(a.title_embedding<=>b.title_embedding))::numeric,3) sim, left(a.title,45) a, left(b.title,45) b from items a join items b on a.id<b.id order by a.title_embedding<=>b.title_embedding limit 8"

uv run tmp_titles.py

### Perform Recluster
docker exec -it ai-digest-db psql -U digest -d digest -c "update items set cluster_id=null"


### Check Search
uv run python -c "from digest import db, search; c=db.connect(); [print(round(r['score'],4), r['source_id'], r['title'][:60]) for r in search.search(c,'agent evaluation')]; c.close()"