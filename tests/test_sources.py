from datetime import datetime, timezone

from hackdigest.sources import codenrock, devpost

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def contest(**kw):
    base = {"id": "1", "slug": "s", "name": " Хак ", "type": "hackathon", "status": "active",
            "startDate": "2026-10-20T00:00:00.000Z", "endDate": "2026-10-22T00:00:00.000Z",
            "endRegistration": "2026-10-19T00:00:00.000Z", "prizes": "100 ₽"}
    return {**base, **kw}


def test_codenrock_filters():
    data = {"contests": [
        contest(id="ok"),
        contest(id="finished", status="finished"),
        contest(id="internship", type="remote"),
        contest(id="started_reg_closed", startDate="2026-10-01T00:00:00.000Z",
                endRegistration="2026-09-30T00:00:00.000Z"),
        contest(id="started_reg_open", startDate="2026-10-01T00:00:00.000Z"),
        contest(id="ctf", type="ctf"),
    ]}
    items = codenrock.parse(data, now=NOW)
    assert [h.uid for h in items] == ["codenrock:ok", "codenrock:started_reg_open", "codenrock:ctf"]
    ok = items[0]
    assert ok.title == "Хак"
    assert ok.url == "https://codenrock.com/contests/s"
    assert ok.dates == "20.10.2026 – 22.10.2026 (рег. до 19.10.2026)"
    assert items[2].tags == ("CTF",)


def test_devpost_parse():
    data = {"hackathons": [
        {"id": 5, "title": "A", "url": "https://a.devpost.com/", "submission_period_dates": "Oct 10 - 12, 2026",
         "displayed_location": {"location": "Online"}, "themes": [{"name": "Web"}],
         "prize_amount": "$<span data-currency-value>10,000</span>", "invite_only": False},
        {"id": 6, "title": "Closed", "url": "u", "invite_only": True},
        {"id": 7, "title": "Free", "url": "u", "prize_amount": "₹ <span>0</span>"},
    ]}
    h, free = devpost.parse(data)
    assert free.prize == ""
    assert h.uid == "devpost:5"
    assert h.prize == "$10,000"
    assert h.location == "Online"
    assert h.tags == ("Web",)
