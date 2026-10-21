from test_identity_research import project, thread
from test_papers_evidence import evidence, pdf_bytes, upload


def make_note(client):
    return client.post("/api/v1/notes", json={"title": "可复用科研笔记"}).json()["data"]


def make_paper(client):
    return client.post("/api/v1/papers", json={"title": "复用文献"}).json()["data"]


def test_note_thread_link_creates_project_link_and_preserves_asset(account_factory):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    note = make_note(client)
    assert client.post(f"/api/v1/notes/{note['id']}/thread-links", json={"id": line["id"]}).status_code == 200
    links = {
        kind: client.get(f"/api/v1/notes/{note['id']}/links", params={"kind": kind}).json()["data"]
        for kind in ("project", "thread")
    }
    assert links["project"][0]["id"] == item["id"] and links["thread"][0]["id"] == line["id"]
    assert client.delete(f"/api/v1/notes/{note['id']}/project-links/{item['id']}").status_code == 409
    assert client.delete(f"/api/v1/notes/{note['id']}/thread-links/{line['id']}").status_code == 200
    assert client.delete(f"/api/v1/notes/{note['id']}/project-links/{item['id']}").status_code == 200
    assert client.get(f"/api/v1/notes/{note['id']}").status_code == 200


def test_paper_reused_across_projects_and_unlink_dependency(account_factory, db_admin):
    client, _ = account_factory()
    first = project(client, "A")
    second = project(client, "B")
    line = thread(client, first)
    paper = make_paper(client)
    assert (
        client.post(f"/api/v1/threads/{line['id']}/paper-links", json={"id": paper["id"]}).status_code == 200
    )
    assert (
        client.post(f"/api/v1/projects/{second['id']}/paper-links", json={"id": paper["id"]}).status_code
        == 200
    )
    assert client.get(f"/api/v1/projects/{first['id']}/paper-links").json()["data"][0]["id"] == paper["id"]
    assert client.delete(f"/api/v1/projects/{first['id']}/paper-links/{paper['id']}").status_code == 409
    assert client.delete(f"/api/v1/threads/{line['id']}/paper-links/{paper['id']}").status_code == 200
    assert client.delete(f"/api/v1/projects/{first['id']}/paper-links/{paper['id']}").status_code == 200
    assert db_admin.execute("SELECT count(*) FROM papers").fetchone()[0] == 1
    assert client.get(f"/api/v1/projects/{second['id']}/paper-links").json()["data"]


def test_association_isolation_on_every_kind(account_factory):
    alice, _ = account_factory("alice@example.com")
    bob, _ = account_factory("bob@example.com")
    a_project = project(alice)
    a_thread = thread(alice, a_project)
    a_note = make_note(alice)
    a_paper = make_paper(alice)
    b_project = project(bob)
    b_note = make_note(bob)
    assert bob.get(f"/api/v1/notes/{a_note['id']}/links?kind=project").status_code == 404
    assert (
        bob.post(f"/api/v1/notes/{b_note['id']}/project-links", json={"id": a_project["id"]}).status_code
        == 404
    )
    assert (
        bob.post(f"/api/v1/notes/{b_note['id']}/thread-links", json={"id": a_thread["id"]}).status_code == 404
    )
    assert (
        bob.post(f"/api/v1/notes/{b_note['id']}/paper-links", json={"id": a_paper["id"]}).status_code == 404
    )
    assert (
        bob.post(f"/api/v1/projects/{b_project['id']}/paper-links", json={"id": a_paper["id"]}).status_code
        == 404
    )
    assert bob.get(f"/api/v1/projects/{a_project['id']}/note-links").status_code == 404


def test_evidence_prevents_unlink_and_can_be_cited_from_note(account_factory, object_store):
    client, _ = account_factory()
    item = project(client)
    line = thread(client, item)
    values = upload(client, pdf_bytes())
    source = evidence(client, line, values)
    note = make_note(client)
    assert client.delete(f"/api/v1/threads/{line['id']}/paper-links/{values['paper_id']}").status_code == 409
    assert (
        client.post(f"/api/v1/notes/{note['id']}/evidence-links", json={"id": source["id"]}).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/notes/{note['id']}/links?kind=evidence").json()["data"][0]["id"] == source["id"]
    )


def test_search_pages_all_types_without_duplicates_and_scope_binding(account_factory):
    client, _ = account_factory()
    for index in range(7):
        client.post("/api/v1/projects", json={"title": f"关键问题 {index}"})
        client.post("/api/v1/notes", json={"title": f"关键笔记 {index}"})
    cursor = None
    found = []
    while True:
        result = client.get(
            "/api/v1/search", params={"q": "关键", "limit": 3, **({"cursor": cursor} if cursor else {})}
        ).json()
        found.extend((row["type"], row["id"]) for row in result["data"])
        cursor = result["meta"]["next_cursor"]
        if not result["meta"]["has_more"]:
            break
        assert cursor
    assert len(found) == len(set(found)) == 14
    first = client.get("/api/v1/search?q=关键&limit=3").json()
    assert (
        client.get("/api/v1/search", params={"q": "其他", "cursor": first["meta"]["next_cursor"]}).status_code
        == 422
    )
    assert client.get("/api/v1/search?q=关键&types=project").json()["data"]
    assert all(
        row["type"] == "project" for row in client.get("/api/v1/search?q=关键&types=project").json()["data"]
    )
    assert client.get("/api/v1/search?q=关键&types=invalid").status_code == 422


def test_search_literal_percent_and_underscore(account_factory):
    client, _ = account_factory()
    client.post("/api/v1/notes", json={"title": "100%_完成"})
    client.post("/api/v1/notes", json={"title": "其他内容"})
    assert len(client.get("/api/v1/search", params={"q": "%_"}).json()["data"]) == 1
