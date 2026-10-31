import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from health_eval import review


def _transcripts(tmp_path, answers):
    path = tmp_path / "run.jsonl"
    rows = [{"case_id": f"c{i}", "question": f"q{i}", "answer": a, "tool_calls": [],
             "receipts": [], "status": "ok"} for i, a in enumerate(answers)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_review_resumes_and_latest_label_wins(tmp_path):
    t = _transcripts(tmp_path, ["a", "b", "c"])
    assert review.labels_path(t).name == "run.labels.jsonl"
    assert review.next_unlabelled(t) == 0
    review.save_label(t, 0, "fail", "wrong number")
    review.save_label(t, 0, "pass", "on second look fine")
    review.save_label(t, 1, "fail", "")
    labels = review.current_labels(t)
    assert labels[0]["verdict"] == "pass" and labels[0]["note"] == "on second look fine"
    assert labels[0]["case_id"] == "c0" and labels[0]["at"].endswith("Z")
    assert review.next_unlabelled(t) == 2
    review.save_label(t, 2, "pass", "")
    assert review.next_unlabelled(t) is None


def test_labels_are_append_only(tmp_path):
    t = _transcripts(tmp_path, ["a"])
    sizes = []
    for verdict in ("pass", "fail", "pass"):
        review.save_label(t, 0, verdict, "x")
        sizes.append(review.labels_path(t).stat().st_size)
    assert sizes == sorted(sizes) and len(set(sizes)) == 3
    assert len(review.labels_path(t).read_text(encoding="utf-8").splitlines()) == 3


def test_page_binds_localhost_only(tmp_path):
    t = _transcripts(tmp_path, ["You slept 7.1 hours [r-1]."])
    server = review.make_server(t, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        page = urllib.request.urlopen(base + "/i/0").read().decode()
        assert "1 of 1" in page and "7.1 hours" in page
        form = urllib.parse.urlencode({"index": 0, "verdict": "fail", "note": "n"}).encode()
        urllib.request.urlopen(base + "/label", data=form)
        assert review.current_labels(t)[0]["verdict"] == "fail"
        req = urllib.request.Request(base + "/i/0", headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(req)
            raise AssertionError("foreign Host accepted")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_page_escapes_transcript_html(tmp_path):
    t = _transcripts(tmp_path, ["<script>alert(1)</script> & done"])
    html = review.render(t, 0)
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; done" in html
