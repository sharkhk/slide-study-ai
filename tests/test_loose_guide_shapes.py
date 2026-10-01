"""
Bug 3 (nightly debug run): /api/chat/<job_id> answered 500 when a stored guide's
keyword dict had no 'term' (or other loose guide shapes) and when the question was
not a string. The question is now validated (400 code 'bad_request') and the
context builder skips / str()s malformed entries. The share route, the public
/s/<slug> page and /api/view/* had the same loose-shape crashes; valid guides
render exactly as before.

EVERYTHING IS OFFLINE: the LLM and Supabase are faked.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app as appmod


@pytest.fixture
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def _has_arabic(s):
    return any("؀" <= ch <= "ۿ" for ch in s or "")


# ── 3. chat / share / view tolerate loose guide shapes ─────────────────────────
def _store(guide, md="# T\n\n- a\n"):
    jid = appmod.uuid.uuid4().hex
    appmod.store_job(jid, b"%PDF-1.4 test", md, guide, None, "x_study_guide.pdf")
    return jid


@pytest.fixture
def chat_llm(monkeypatch):
    seen = {"prompts": [], "reply": {"answer": "It is a green pigment."}}

    def call(prompt, retries=3, num_predict=4096):
        seen["prompts"].append(prompt)
        return seen["reply"]
    monkeypatch.setattr(appmod, "_call_ollama", call)
    return seen


def test_chat_keyword_without_term_is_not_a_500(client, chat_llm):
    jid = _store({"title": "Plants", "keywords": [{"definition": "Green pigment in chloroplasts"}]})
    r = client.post(f"/api/chat/{jid}", json={"question": "What is chlorophyll?"})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert r.get_json()["answer"] == "It is a green pigment."
    assert "Green pigment in chloroplasts" in chat_llm["prompts"][0]


def test_chat_context_tolerates_loose_shapes(client, chat_llm):
    jid = _store({
        "title": 1984,
        "objectives": "Explain the light reactions",
        "sections": ["a bare string section", None,
                     {"title": None, "bullets": [None, 3, ["x"], {"fact": 9}, {"text": "Water is split"}]},
                     {"title": "Calvin cycle", "bullets": "Carbon is fixed"},
                     {"title": "Empty", "bullets": 7}],
        "keywords": [{"term": 7, "definition": ["not", "a", "string"]}, "ATP", None,
                     {"term": "Chlorophyll", "definition": "Green pigment"}, {"term": "NADPH"}],
    })
    r = client.post(f"/api/chat/{jid}", json={"question": "Summarise", "language": "en"})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    p = chat_llm["prompts"][0]
    for expected in ("Title: 1984", "- Explain the light reactions", "- Water is split", "- 3",
                     "[Calvin cycle]", "- Carbon is fixed", "Chlorophyll: Green pigment", "ATP", "NADPH"):
        assert expected in p, expected
    assert "- E\n- x" not in p                                # a string objective is not split into letters


def test_chat_valid_guide_context_is_unchanged(client, chat_llm):
    jid = _store({"title": "Photosynthesis", "objectives": ["Explain the light reactions"],
                  "sections": [{"title": "Light reactions", "bullets": ["Water is split", {"text": "ATP is made"}]}],
                  "keywords": [{"term": "Chlorophyll", "definition": "Green pigment"}, "Stroma"]})
    client.post(f"/api/chat/{jid}", json={"question": "q"})
    p = chat_llm["prompts"][0]
    assert ("Title: Photosynthesis\n\nObjectives:\n- Explain the light reactions\n\n\n[Light reactions]\n"
            "- Water is split\n- ATP is made\n\nKey terms:\nChlorophyll: Green pigment\nStroma") in p


@pytest.mark.parametrize("body", [{"question": 123}, {"question": None}, {"question": ["why?"]},
                                  {"question": {"q": "why?"}}, {"question": True}, {"question": "   "},
                                  {}, {"language": "en"}])
def test_chat_bad_question_is_400_bad_request(client, chat_llm, body):
    jid = _store({"title": "Plants"})
    r = client.post(f"/api/chat/{jid}", json=body)
    assert r.status_code == 400, r.get_data(as_text=True)[:300]
    d = r.get_json()
    assert d["code"] == "bad_request" and d["error"]
    assert chat_llm["prompts"] == []


@pytest.mark.parametrize("raw", ["[\"why?\"]", "\"why?\"", "7"])
def test_chat_non_object_body_is_400(client, chat_llm, raw):
    jid = _store({"title": "Plants"})
    r = client.post(f"/api/chat/{jid}", data=raw, content_type="application/json")
    assert r.status_code == 400 and r.get_json()["code"] == "bad_request"


def test_chat_empty_question_message_is_localized(client, chat_llm):
    jid = _store({"title": "Plants"})
    en = client.post(f"/api/chat/{jid}", json={"question": ""}).get_json()
    ar = client.post(f"/api/chat/{jid}", json={"question": "", "language": "ar"}).get_json()
    assert en["error"] == "No question provided" and en["code"] == "bad_request"
    assert _has_arabic(ar["error"]) and ar["code"] == "bad_request"


def test_chat_question_is_still_capped_at_500_chars(client, chat_llm):
    jid = _store({"title": "Plants"})
    q = "w" * 499 + "XYZ" + "z" * 1000
    assert client.post(f"/api/chat/{jid}", json={"question": q}).status_code == 200
    p = chat_llm["prompts"][0]
    assert "w" * 499 + "X" in p and "XY" not in p


@pytest.mark.parametrize("reply,expected", [
    ([{"answer": "From a list"}], "From a list"),               # used to 500 ('list'.get)
    ({"answer": ["Line one", "Line two"]}, "Line one\nLine two"),  # a list reached the client
    ("  A bare JSON string reply  ", "A bare JSON string reply"),  # used to 500 ('str'.get)
    ({"answer": 42}, "42"),
    ({"answer": None}, ""),            # falsy → the client shows its own localized "no answer"
    ({"answer": {"x": 1}}, ""),
    ({"text": "wrong key"}, "No answer found in the material."),   # unchanged default
])
def test_chat_loose_llm_reply_is_not_a_500(client, chat_llm, reply, expected):
    chat_llm["reply"] = reply
    jid = _store({"title": "Plants"})
    r = client.post(f"/api/chat/{jid}", json={"question": "why?"})
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert r.get_json()["answer"] == expected


@pytest.mark.parametrize("title,expected", [(1984, "1984"), (None, "Study Guide"), (["T"], "Study Guide"),
                                            ({"t": 1}, "Study Guide"), ("Cells", "Cells")])
def test_share_tolerates_non_string_title(client, monkeypatch, title, expected):
    sb = MagicMock()
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    jid = _store({"title": title, "sections": [{"title": "A", "bullets": ["b"]}]})
    r = client.post(f"/api/share/{jid}")
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert sb.table.return_value.insert.call_args[0][0]["title"] == expected


def _shared_page(client, monkeypatch, guide, language="en"):
    sb = MagicMock()
    row = {"slug": "abc123", "guide": guide, "title": "T", "language": language}
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = \
        SimpleNamespace(data=row)
    monkeypatch.setattr(appmod, "_get_sb", lambda: sb)
    return client.get("/s/abc123")


@pytest.mark.parametrize("guide", [
    {"title": "T", "sections": ["a string section", {"title": "S", "bullets": ["fact"]}]},  # desc from sections
    {"title": "T", "objectives": [], "sections": [{"title": "S", "bullets": 7}]},
    {"title": "T", "objectives": ["o"], "sections": [{"title": "S", "bullets": 7}]},
    {"title": "T", "objectives": 5},
    {"title": "T", "mcqs": [{"q": "Q", "options": 3, "answer": "A"}]},
    {"title": "T", "mcqs": "junk", "flashcards": 5, "keywords": 9},
    {"title": {"x": 1}, "subtitle": ["s"], "keywords": [{"term": "K", "definition": None}]},
    "a guide stored as a plain string",
    None,
])
def test_shared_page_tolerates_loose_shapes(client, monkeypatch, guide):
    r = _shared_page(client, monkeypatch, guide)
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert "<html" in r.get_data(as_text=True)


def test_shared_page_string_objective_is_one_item_and_no_none_text(client, monkeypatch):
    html = _shared_page(client, monkeypatch, {
        "title": "T", "objectives": "Explain the light reactions",
        "sections": [{"title": "S", "bullets": [None, {"text": None}, "Real fact", 3]}],
        "keywords": [{"term": "K", "definition": None}]}).get_data(as_text=True)
    assert "<li>Explain the light reactions</li>" in html
    assert "<dd>None</dd>" not in html
    assert "<li>Real fact</li>" in html and "<li>3</li>" in html
    assert "<li>None</li>" not in html


def test_shared_page_valid_guide_unchanged(client, monkeypatch):
    html = _shared_page(client, monkeypatch, {
        "title": "Photosynthesis", "subtitle": "Biology", "objectives": ["Explain it"],
        "sections": [{"title": "Light", "bullets": ["Water is split"]}],
        "keywords": [{"term": "Chlorophyll", "definition": "Green pigment"}],
        "flashcards": [{"q": "Where?", "a": "Chloroplast"}],
        "mcqs": [{"q": "Gas?", "options": ["A) O2", "B) N2"], "answer": "A", "explanation": "O2"}],
    }).get_data(as_text=True)
    for s in ("<h1>Photosynthesis</h1>", "<p class=\"sub\">Biology</p>", "<li>Explain it</li>",
              "<li>Water is split</li>", "<dt>Chlorophyll</dt><dd>Green pigment</dd>",
              "<div class=\"fc-q\">Where?</div>", "<li class=\"opt correct\">✓ A) O2</li>",
              "<li class=\"opt\">B) N2</li>", "<div class=\"expl\">O2</div>"):
        assert s in html, s


@pytest.mark.parametrize("route", ["md", "cards", "quiz"])
@pytest.mark.parametrize("guide", [
    {"title": "T", "flashcards": None, "mcqs": None},
    {"title": None, "flashcards": 5, "mcqs": 5},
    {"title": "T", "flashcards": {"q": "x"}, "mcqs": {"q": "x"}},
    None,
])
def test_view_routes_tolerate_loose_shapes(client, route, guide):
    jid = _store(guide)
    r = client.get(f"/api/view/{route}/{jid}")
    assert r.status_code == 200, r.get_data(as_text=True)[:300]


def test_view_quiz_options_are_always_a_list(client):
    # q.options.map(...) in the page script: a string/number/missing options value
    # crashed the quiz in the browser (and a question with no options can't be
    # answered — the Next button never appears).
    jid = _store({"title": "T", "mcqs": [
        {"q": "Good", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"},
        {"q": "Bare string", "options": "A) only one", "answer": "A"},
        {"q": "Number", "options": 4, "answer": "A"},
        {"q": "Missing", "answer": "A"},
        {"q": "Mixed", "options": ["A) x", None, 2, {"o": 1}], "answer": "A"},
    ]})
    html = client.get(f"/api/view/quiz/{jid}").get_data(as_text=True)
    line = next(l for l in html.splitlines() if l.startswith("const qs = "))
    qs = json.loads(line[len("const qs = "):].rstrip(";"))
    assert all(isinstance(q["options"], list) and q["options"] for q in qs)
    assert all(isinstance(o, str) for q in qs for o in q["options"])
    by_q = {q["q"]: q for q in qs}
    assert by_q["Good"] == {"q": "Good", "options": ["A) x", "B) y"], "answer": "A", "explanation": "e"}
    assert by_q["Bare string"]["options"] == ["A) only one"]
    assert by_q["Mixed"]["options"] == ["A) x", "2"]
    assert "Number" not in by_q and "Missing" not in by_q
