import json
from datetime import datetime, timezone

from hackdigest.dates import extract_dates
from hackdigest.sources import codenrock, devfolio, devpost, mlh, telegram

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
    assert items[0].title == "Хак"
    assert items[0].url == "https://codenrock.com/contests/s"
    assert items[0].reg_deadline == datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert items[2].tags == ("CTF",)


def test_devpost_dates():
    d = devpost.parse_dates
    assert d("Oct 09 - 12, 2026")[0] == datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert d("Oct 30 - Nov 02, 2026")[1].date().isoformat() == "2026-11-02"
    assert d("Dec 28, 2026 - Jan 02, 2027")[0].year == 2026
    assert d("Dec 28 - Jan 02, 2027")[0].year == 2026
    assert d("Oct 10, 2026")[0] == datetime(2026, 10, 10, tzinfo=timezone.utc)
    assert d("TBA") == (None, None)


def test_devpost_parse():
    data = {"hackathons": [
        {"id": 5, "title": "A", "url": "https://a.devpost.com/", "submission_period_dates": "Oct 10 - 12, 2026",
         "displayed_location": {"icon": "globe", "location": "Online"}, "themes": [{"name": "Web"}],
         "prize_amount": "$<span data-currency-value>10,000</span>", "invite_only": False},
        {"id": 6, "title": "Closed", "url": "u", "invite_only": True},
        {"id": 7, "title": "Free", "url": "u", "prize_amount": "₹ <span>0</span>",
         "displayed_location": {"icon": "map-marker-alt", "location": "MIT"}},
    ]}
    h, free = devpost.parse(data)
    assert h.uid == "devpost:5" and h.prize == "$10,000" and h.online is True and h.tags == ("Web",)
    assert h.start.day == 10 and h.end.day == 12
    assert free.prize == "" and free.online is False and free.location == "MIT"


def test_mlh_parse():
    page = {"props": {"upcomingEvents": [{
        "id": "u1", "name": "HackNC", "url": "/events/hacknc/prizes", "websiteUrl": "https://hacknc.com/",
        "startsAt": "2026-10-09T01:11:11Z", "endsAt": "2026-10-11T20:00:00Z",
        "location": "Chapel Hill", "formatType": "physical", "customFields": {"hackathon_focus": ["Software"]}}]}}
    html = f'<html><script data-page="app" type="application/json">{json.dumps(page)}</script></html>'
    [h] = mlh.parse(html)
    assert h.uid == "mlh:u1" and h.url == "https://hacknc.com/" and h.online is False
    assert h.location == "Chapel Hill" and h.tags == ("Software",)
    assert mlh.season(NOW) == 2027


def test_devfolio_parse():
    data = {"result": [{
        "uuid": "x", "name": "Wild Bugs", "tagline": "Code. Crash.", "desc": "## **24h** [online](https://x) hack", "slug": "wild-bugs", "starts_at": "2026-10-13T18:30:00.000Z",
        "ends_at": "2026-10-15T18:29:00.000Z", "is_online": True,
        "themes": [{"name": "No Restrictions"}, {"name": "AI"}],
        "hackathon_setting": {"subdomain": "wild-bugs", "reg_ends_at": "2026-10-09T18:29:00.000Z"}}]}
    [h] = devfolio.parse(data)
    assert h.url == "https://wild-bugs.devfolio.co/" and h.online is True
    assert h.tags == ("No Restrictions", "AI")
    assert h.reg_deadline.hour == 18
    assert h.description == "Code. Crash. 24h online hack"


def test_normalize_channel():
    n = telegram.normalize_channel
    assert n("@ITMO_news") == "itmo_news"
    assert n("https://t.me/s/codenrock") == "codenrock"
    assert n("t.me/hse_ru/123") == "hse_ru"
    assert n("плохое имя") is None
    assert n("ab") is None


def _post(post_id: str, text: str, when: str) -> str:
    return (f'<div class="tgme_widget_message" data-post="chan/{post_id}">'
            f'<div class="tgme_widget_message_text">{text}</div>'
            f'<a class="tgme_widget_message_date"><time datetime="{when}"></time></a></div>')


def test_telegram_parse():
    html = ('<div class="tgme_channel_info_header_title">Канал ВУЗа</div><section class="tgme_channel_history">'
            + _post("1", "Хакатон «Код города»<br>Пройдёт 15–17 ноября. Регистрация до 30 октября", "2026-10-05T10:00:00+00:00")
            + _post("2", "Открыт набор на курсы", "2026-10-06T10:00:00+00:00")
            + _post("4", "История: в 1999 году прошёл первый хакатон, участники и регистрация", "2026-10-06T11:00:00+00:00")
            + _post("3", "Старый хакатон", "2026-08-01T10:00:00+00:00")
            + "</section>")
    [h] = telegram.parse(html, "chan", now=NOW)
    assert h.uid == "telegram:chan/1" and h.url == "https://t.me/chan/1"
    assert h.title == "Хакатон «Код города»" and h.via == "Канал ВУЗа"
    assert (h.start.day, h.end.day, h.reg_deadline.day) == (15, 17, 30)


def test_extract_dates():
    def days(text):
        return tuple(d and d.date().isoformat() for d in extract_dates(text, NOW))
    assert days("Пройдёт 15–17 ноября. Регистрация до 30 октября") == ("2026-11-15", "2026-11-17", "2026-10-30")
    assert days("Приём заявок до 20.10, финал 1.11.2026") == ("2026-11-01", None, "2026-10-20")
    assert days("30 октября – 2 ноября онлайн") == ("2026-10-30", "2026-11-02", None)
    assert days("5 января") == ("2027-01-05", None, None)  # без года и «в прошлом» — следующий год
    assert days("без дат") == (None, None, None)


def test_hackathons_rus_parse():
    from hackdigest.sources import hackathons_rus
    data = {"posts": [
        {"uid": "a", "title": "Открой #Моспром", "date": "2026-10-21 23:00", "url": "https://x/a",
         "parts": "Регистрация открыта,offline,Москва,DS/ML/AI",
         "descr": "Даты: 23-25 октября 2026. Призовой фонд: 2,5 млн ₽"},
        {"uid": "b", "title": "Закрытый", "date": "2026-10-21 23:00", "url": "u", "parts": "Регистрация закрыта"},
    ]}
    [h] = hackathons_rus.parse(data, now=NOW)
    assert (h.start.day, h.end.day, h.reg_deadline.day) == (23, 25, 21)
    assert h.online is False and h.location == "Москва" and h.tags == ("AI / ML",) and h.prize == "2,5 млн ₽"


def test_leader_id_parse():
    from hackdigest.sources import leader_id
    base = {"date_start": "2026-10-22 09:30:00", "date_end": "2026-10-22 17:00:00",
            "registration_date_end": "2026-10-20 17:00:00", "timezone": {"value": "+03:00"},
            "format": "space", "city": "Севастополь", "themes": [{"name": "TechNet"}], "finished": False}
    data = {"data": {"_items": [
        {**base, "id": 1, "full_name": "Хакатон «ПриморТех»"},
        {**base, "id": 2, "full_name": "Хакатоны как точка старта: с чего начать"},
        {**base, "id": 3, "full_name": "Питч-сессия проектов"},
    ]}}
    [h] = leader_id.parse(data)
    assert h.url == "https://leader-id.ru/events/1" and h.online is False and h.location == "Севастополь"
    assert h.start.utcoffset().total_seconds() == 3 * 3600


def test_telegram_announcement_heuristic():
    assert telegram.is_announcement("Хакатон «Х». Регистрация до 20 октября")
    assert not telegram.is_announcement("Подвели итоги хакатона, поздравляем победителей! Регистрация была большой")
    assert not telegram.is_announcement("Открыт набор на курсы, регистрация")
    assert telegram.clean("🔥 Хакатон 🚀") == "Хакатон"


def test_leader_id_description():
    from hackdigest.sources import leader_id
    info = json.dumps({"blocks": [{"data": {"text": "Хакатон <b>для студентов</b>&nbsp;вузов"}}, {"type": "x"}]})
    assert leader_id._description(info) == "Хакатон для студентов вузов"
    assert leader_id._description("not json") == ""
