# GeekNews Server — local MCP environment

GeekNews Server는 GeekNews(국내 개발자 커뮤니티)에서 제공되는 아티클 피드(top/new/ask/show)와 주간 뉴스(weekly)를 조회할 수 있게 하는 읽기 전용 API 백엔드이다. 백엔드는 피드별 아티클 목록과 주간 뉴스 본문/항목을 저장·캐시하며, 최신 데이터를 주기적으로 수집(동기화)해 API 요청에 빠르게 응답한다.

Repository: https://github.com/the0807/GeekNews-MCP-Server
Homepage: https://smithery.ai/server/@the0807/geeknews-mcp-server

## Datastore

- `articles.json` — GeekNews의 개별 아티클(피드에 노출되는 글) 메타데이터. get_articles(type, limit)의 반환 목록을 구성한다. (18 rows; fields: ['id', 'geeknews_id', 'title', 'url', 'geeknews_url', 'author_name', 'points', 'comment_count', 'tags', 'published_at', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'deleted']
  - constraint: unique(geeknews_id)
  - constraint: points >= 0
  - constraint: comment_count >= 0
  - constraint: geeknews_url LIKE 'http%'
- `article_feeds.json` — 피드 타입(top/new/ask/show)별로 아티클을 노출 순서대로 매핑. get_articles(type, limit)는 이 테이블을 기준으로 정렬/리밋한다. (18 rows; fields: ['id', 'feed_type', 'article_id', 'rank', 'snapshot_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale']
  - constraint: rank BETWEEN 1 AND 500
  - constraint: unique(feed_type, snapshot_at, rank)
  - constraint: unique(feed_type, snapshot_at, article_id)
  - constraint: FK(article_id) references articles(id) ON DELETE CASCADE
- `weekly_news.json` — GeekNews 주간 뉴스 헤더(주차 단위). get_weekly_news(weekly_id)가 빈 문자열이면 가장 최근 주간 뉴스를 반환한다. (18 rows; fields: ['id', 'weekly_id', 'title', 'geeknews_url', 'start_date', 'end_date', 'published_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: unique(weekly_id)
  - constraint: geeknews_url LIKE 'http%'
  - constraint: start_date IS NULL OR end_date IS NULL OR start_date <= end_date
- `weekly_news_items.json` — 주간 뉴스의 본문 항목(섹션/링크/요약). 필요 시 아티클과 연결해 재사용 가능. (18 rows; fields: ['id', 'weekly_news_id', 'position', 'section', 'title', 'url', 'summary', 'article_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: position >= 1
  - constraint: unique(weekly_news_id, position)
  - constraint: FK(weekly_news_id) references weekly_news(id) ON DELETE CASCADE
  - constraint: article_id IS NULL OR FK(article_id) references articles(id) ON DELETE SET NULL
- `sync_runs.json` — GeekNews 원본으로부터 피드/주간뉴스를 수집해 캐시를 갱신하는 동기화 실행 기록(운영/디버깅/관측용). 직접 툴로 노출되진 않지만, API 응답 데이터의 최신성/수집 실패를 관리하는 데 필요. (17 rows; fields: ['id', 'job_type', 'feed_type', 'target_weekly_id', 'status', 'started_at', 'finished_at', 'fetched_count', 'error_message', 'source_etag', 'source_last_modified', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fetched_count >= 0
  - constraint: job_type='articles_feed' implies feed_type is not null
  - constraint: job_type='weekly_news' implies target_weekly_id may be null
  - constraint: started_at IS NULL OR finished_at IS NULL OR started_at <= finished_at

## Business rules enforced by the tools

- get_articles.type은 {'top','new','ask','show'} 중 하나여야 하며, 그 외 값이면 ValueError에 해당하는 4xx 에러를 반환한다.
- get_articles.limit은 1 이상 30 이하여야 하며, 범위를 벗어나면 30으로 clamp 또는 4xx로 거부(구현 정책 중 하나를 고정)한다. 백엔드는 저장 시 rank/스냅샷 기준으로 최대 30개까지만 빠르게 조회 가능하도록 인덱싱한다.
- get_articles는 article_feeds에서 feed_type=요청 type AND status='active'인 최신 snapshot_at(최대값) 세트를 선택하고, rank 오름차순으로 limit만큼 조인(articles)해 반환한다. articles.status!='active'인 경우 결과에서 제외한다.
- get_weekly_news.weekly_id가 빈 문자열이면 weekly_news.status='active' 중 published_at 내림차순(또는 end_date 내림차순, 둘 다 없으면 updated_at 내림차순)으로 1건을 반환한다.
- get_weekly_news.weekly_id가 주어지면 weekly_news.weekly_id로 단건 조회하며, 없으면 404에 해당하는 응답을 반환한다.
- weekly_news 응답에는 weekly_news_items를 position 오름차순으로 포함해야 하며, weekly_news_items.status='active'만 포함한다.
- 동기화 실행(sync_runs)은 queued->running->(succeeded|failed|cancelled) 전이만 허용한다. running 상태에서만 started_at 설정이 가능하고, 종료 상태로 전이 시 finished_at이 설정되어야 한다.
- 동기화가 성공하면 해당 feed_type의 기존 article_feeds.status='active' 레코드는 stale로 마킹하고, 동일 snapshot_at으로 새 active 세트를 삽입한다(스냅샷 단위 원자적 갱신).
- articles.geeknews_id 및 weekly_news.weekly_id는 전역 유일해야 하며, 중복 수집 시 upsert로 title/url/points/comment_count/tags/published_at/last_seen_at/updated_at만 갱신한다.
- FK 무결성: article_feeds.article_id와 weekly_news_items.weekly_news_id는 반드시 존재해야 하며, 부모 삭제 시 자식은 CASCADE로 삭제된다.