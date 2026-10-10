import json
from datetime import datetime, timezone

from hackdigest.dates import extract_dates
from hackdigest.sources import (changellenge, codenrock, ctftime, devfolio, devpost, dorahacks, lablab, mlh, taikai,
                                telegram)

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


def test_telegram_recap_vs_prize_wording():
    ann = "Альфа-Будущее Хакатон\nРегистрация до 18 октября. Призовой фонд 3 млн ₽, фаст-трек для победителей"
    assert telegram.is_announcement(ann)
    assert not telegram.is_announcement("Наши студенты — победители хакатона Московского транспорта\nрегистрация")


def test_telegram_roundup_split():
    text = ("Дедлайны ближайших хакатонов\n\nдо 08.10 — Old Hack\nold.devpost.com\n\n"
            "до 16.10 — О!Хакатон 2026\nhackrus.ru/1294\n\nдо 23.10 — Amazon Hackathon\namazon.devpost.com")
    items = telegram.parse_roundup(text, "chan/5", "Канал", NOW)
    assert [h.title for h in items] == ["О!Хакатон 2026", "Amazon Hackathon"]  # прошедший дедлайн отброшен
    assert items[0].url == "https://hackrus.ru/1294"
    assert items[0].reg_deadline.isoformat() == "2026-10-16T23:59:00+03:00"


def test_telegram_title_from_lowercase_post():
    assert telegram._title("дорогая, увольняйся с работы\nэто наш сезон Changellenge >> Hack & Change") == "Hack & Change"
    assert telegram._title("Продолжите фразу: хакатон — это…\nХакатоны PROD") == "Хакатоны PROD"


def test_deadline_lasts_whole_moscow_day():
    _, _, deadline = extract_dates("Регистрация до 27 октября", NOW)
    assert deadline.isoformat() == "2026-10-27T23:59:00+03:00"


def test_codenrock_eastern_midnight_and_format():
    [h] = codenrock.parse({"contests": [contest(startDate="2026-10-19T19:00:00.000Z",
                                                description="Офлайн-хакатон в Нижнем Новгороде")]}, now=NOW)
    assert h.start.isoformat() == "2026-10-20T00:00:00+03:00"
    assert h.online is False


def test_guess_online():
    from hackdigest.text import guess_online
    assert guess_online("Онлайн-хакатон для студентов") is True
    assert guess_online("Отбор онлайн, очный финал в Москве") is False
    assert guess_online("Хакатон по ML") is None


def ts(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def test_dorahacks_parse():
    base = {"owner": {"name": "WEEX"}, "timeline_start": ts(2026, 10, 1), "timeline_end": ts(2026, 10, 20),
            "venue_form": "Virtual", "bonus_price": 200000, "bonus_token": "USD", "tags": "AI, Web3", "hackers_count": 9}
    data = {"results": [
        {**base, "id": 1, "uname": "wars", "title": " AI Wars "},
        {**base, "id": 2, "uname": "wars-cn", "title": "AI Wars 中文"},  # тот же хакатон на другом языке
        {"id": 3, "uname": None, "title": "IRL", "owner": {"name": "Uni"}, "timeline_start": ts(2026, 11, 1),
         "timeline_end": ts(2026, 11, 2), "venue_form": "IRL", "venue_name": "Campus", "bonus_price": 0},
        {**base, "id": 4, "owner": None, "timeline_end": ts(2026, 10, 1)},  # уже закончился
    ]}
    wars, irl = dorahacks.parse(data, now=NOW)
    assert wars.title == "AI Wars" and wars.url == "https://dorahacks.io/hackathon/wars"
    assert wars.online is True and wars.prize == "$200,000" and wars.tags == ("AI", "Web3")
    assert wars.reg_deadline == wars.end and wars.organizer == "WEEX" and wars.participants == 9
    assert irl.url == "https://dorahacks.io/hackathon/3" and irl.online is False and irl.location == "Campus"
    assert irl.reg_deadline is None and irl.prize == "" and irl.participants is None


def test_ctftime_parse():
    base = {"start": "2026-10-17T09:00:00+00:00", "finish": "2026-10-18T21:00:00+00:00", "onsite": False,
            "location": "", "format": "Jeopardy", "weight": 0.0, "participants": 3, "restrictions": "Open",
            "organizers": [{"name": "Team"}], "description": "pwn, web"}
    data = [
        {**base, "id": 1, "title": "Rated CTF", "weight": 85.1, "ctftime_url": "https://ctftime.org/event/1/"},
        {**base, "id": 2, "title": "Tiny CTF"},  # без рейтинга и почти без команд — шум
        {**base, "id": 3, "title": "Russian CTF Cup Qualifier"},
        {**base, "id": 4, "title": "Finals", "weight": 50, "restrictions": "Prequalified"},
        {**base, "id": 5, "title": "Popular", "participants": 40, "onsite": True, "location": "Bali"},
    ]
    rated, ru, onsite = ctftime.parse(data, now=NOW)
    assert rated.url == "https://ctftime.org/event/1/" and rated.tags == ("CTF", "Jeopardy")
    assert rated.online is True and rated.organizer == "Team" and rated.participants == 3
    assert ru.uid == "ctftime:3" and ru.url == "https://ctftime.org/event/3/"
    assert onsite.online is False and onsite.location == "Bali"


def test_taikai_parse():
    def ch(**kw):
        base = {"id": "a", "name": "Space Hack", "slug": "space", "isClosed": False, "prize": 9000,
                "prizeCurrency": {"name": "EUR"}, "organization": {"slug": "cassini", "name": "CASSINI"},
                "participantsCount": 176, "industries": [{"title": "Space"}], "shortDescription": "Build for space",
                "steps": [{"name": "Registrations open", "startDate": "2026-09-28T00:00:00.000Z"},
                          {"name": " Registration Deadline", "startDate": "2026-11-20T00:00:00.000Z"},
                          {"name": "Hackathon Weekend", "startDate": "2026-11-27T00:00:00.000Z"},
                          {"name": "Awards", "startDate": "2026-12-02T00:00:00.000Z"}]}
        return {**base, **kw}
    data = {"data": {"challenges": [
        ch(),
        ch(id="closed", isClosed=True),
        ch(id="past", steps=[{"name": "Results", "startDate": "2026-09-01T00:00:00.000Z"}]),
        ch(id="irl", prize=0, shortDescription="In-person hackathon in Porto",
           steps=[{"name": "Registration", "startDate": "2026-09-01T00:00:00.000Z"},
                  {"name": "Development", "startDate": "2026-10-19T00:00:00.000Z"}]),
    ]}}
    h, irl = taikai.parse(data, now=NOW)
    assert h.url == "https://taikai.network/cassini/hackathons/space" and h.prize == "€9,000"
    assert h.start == datetime(2026, 11, 27, tzinfo=timezone.utc) and h.end.day == 2
    assert h.reg_deadline == datetime(2026, 11, 20, tzinfo=timezone.utc)
    assert h.online is True and h.organizer == "CASSINI" and h.participants == 176 and h.tags == ("Space",)
    # дедлайна нет — регистрация открыта до старта
    assert irl.reg_deadline == irl.start and irl.online is False and irl.prize == ""


def test_lablab_parse():
    events = {"sortedEvents": [
        {"id": "1", "name": "Agent Rush", "slug": "agent-rush", "type": "HACKATHON", "eventType": "HYBRID",
         "startAt": "2026-11-03T15:00:00.000Z", "endAt": "2026-11-08T22:00:00.000Z", "signupActive": True,
         "description": "Build agents", "_count": {"participants": 688},
         "technologyList": [{"techName": "Vultr"}]},
        {"id": "2", "name": "League", "slug": "league", "type": "HACKATHON", "eventType": "ONLINE",
         "startAt": "2026-09-01T19:00:00.000Z", "endAt": "2026-12-01T19:00:00.000Z", "signupActive": True},
        {"id": "3", "name": "Old", "slug": "old", "type": "HACKATHON", "eventType": "ONLINE",
         "startAt": "2026-08-01T00:00:00.000Z", "endAt": "2026-08-03T00:00:00.000Z"},
        {"id": "4", "name": "Meetup", "slug": "m", "type": "EVENT", "endAt": "2026-12-01T00:00:00.000Z"},
    ], "technologyListData": []}
    stream = '0:["$","div",null,' + json.dumps(events) + "]"
    # поток Next.js приходит кусками, разрезанными в произвольном месте
    pushes = "".join(f"<script>self.__next_f.push([1,{json.dumps(stream[i:i + 50])}])</script>"
                     for i in range(0, len(stream), 50))
    rush, league = lablab.parse(f"<html>{pushes}</html>", now=NOW)
    assert rush.url == "https://lablab.ai/ai-hackathons/agent-rush" and rush.online is True
    assert rush.tags == ("AI", "Vultr") and rush.participants == 688 and rush.reg_deadline is None
    assert league.reg_deadline == league.end  # уже идёт, но записаться можно


def test_changellenge_parse():
    def card(code, title, descr, chip, href=None):
        return (f'<article class="champ-card" data-code="{code}"><p class="champ-card__company">Changellenge &gt;&gt;</p>'
                f'<h3 class="champ-card__title"><a href="{href or f"/championships/{code}/?src=chemp"}">{title}</a></h3>'
                f'<p class="champ-card__descr">{descr}</p><span class="champ-card__chip">{chip}</span></article>')
    page = "".join([
        card("hack", "Хакатон Hack&amp;Change 2026", "Онлайн-хакатон по веб-разработке и ИИ", "09 ноября"),
        card("cup", "Changellenge &gt;&gt; Cup Moscow 2026", "Бизнес-кейсы от компаний-партнеров", "26 октября"),
        card("mts", "MTC Engineer Hack", "Задачи инженеров", "30 сентября"),
        card("alfa", "Альфа-Будущее Хакатон", "", "19 октября", href="https://alfa.example/hack?utm=1"),
    ])
    hack, alfa = changellenge.parse(page, now=NOW)
    assert hack.url == "https://changellenge.com/championships/hack/" and hack.title == "Хакатон Hack&Change 2026"
    assert (hack.start.month, hack.start.day, hack.start.year) == (11, 9, 2026) and hack.online is True
    assert hack.organizer == "Changellenge"
    assert alfa.url == "https://alfa.example/hack?utm=1" and alfa.online is None
