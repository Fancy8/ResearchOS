# Implementation decisions and evidence

- Four initial schema phases consolidate the design's M001–M012 domain order
  into dependency-safe immutable revisions. Revision 0005 separates history
  privileges. The table count remains 35; executed revisions are not rewritten.
- Windows psycopg async operation uses a SelectorEventLoop in the launcher and
  tests. Web services remain async; workers use separate synchronous sessions.
  [Official psycopg constraint](https://www.psycopg.org/psycopg3/docs/advanced/async.html).
- MinIO's Windows binary URL returned HTTP 410. Local persistent object storage
  uses the official SeaweedFS 4.48 Windows release behind the same S3 adapter.
  Anonymous access was checked to return 403. No mock storage replaces runtime
  files. [SeaweedFS source](https://github.com/seaweedfs/seaweedfs).
- Redis Windows is a community build used only for local development. Celery
  uses solo locally; production manifests must use supported Linux processes.
  [Redis Windows scope](https://github.com/redis-windows/redis-windows).
- Upload completion returns 202 before background validation; the new file
  becomes current only after size/hash/PDF/page validation and parsing succeed.
  Each attempt writes a distinct final candidate key, preventing stale workers
  from overwriting an accepted file. Old evidence never rebinds to a new PDF.
- PDF.js 6 removed older proxy methods. The reader retains/destroys loading
  tasks and imports only scoped TextLayer CSS, preventing its stock viewer
  sidebar rules from changing ResearchOS layout.
- Development is invitation-only; credentials are generated under gitignored
  runtime/. No remote repository, public deployment or third-party AI transmission
  has been created by this implementation.
