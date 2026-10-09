from datetime import datetime, timedelta, timezone

from hackdigest.digest import brief, format_item, topics_line
from hackdigest.filters import Filters
from hackdigest.models import Hackathon
from hackdigest.topics import classify

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def test_classify_from_description():
    assert classify("Геймджем «Моторика»", (), "Участники разработают игры для людей, использующих протезы. "
                    "Решение поможет освоить управление бионической рукой") == ["gamedev", "health"]
    assert classify("О! Хакатон", (), "Соревнование по разработке тревел-решений: переизобрести "
                    "бронирование отелей или создать AI-агента для путешествий") == ["ai", "retail"]
    assert classify("РадиоШторм", (), "Соревнование по радиосвязи и цифровой обработке сигналов "
                    "для студентов вузов") == ["hardware", "students"]
    assert classify("Banana Hacks", ("Beginner Friendly", "Machine Learning/AI")) == ["ai", "beginners"]
    assert classify("Wild Bugs", ("No Restrictions",)) == ["open"]


def test_classify_no_false_positives():
    # одно упоминание в длинном описании — не тема; «chain» не значит «ai»; «learning» не образование
    long_text = "Будет пицца и мерч, а ещё один банк-партнёр. " + "Команды работают двое суток. " * 10
    assert classify("Hack", (), long_text) == []
    # а в короткой фразе-описании одного упоминания хватает
    assert classify("РуКод", (), "Финал по алгоритмическому программированию") == ["algo"]
    assert classify("Blockchain build", (), "") == ["web3"]
    assert "edu" not in classify("ML hack", ("Machine Learning",), "deep learning, machine learning")
    assert "edu" not in classify("CTF", ("для школьников",), "")
    assert classify("InnoCTF Junior", ("CTF", "для школьников"), "") == ["security"]  # категории «школьникам» нет


def make(title: str, description: str = "", **kw) -> Hackathon:
    return Hackathon(uid=f"codenrock:{title}", source="codenrock", title=title, url="https://x",
                     start=NOW + timedelta(days=3), description=description, **kw)


def test_topic_filter_and_or():
    ai_health = make("ИИ в медицине", "Нейросети для анализа снимков пациентов, медицина и клиники")
    ai_fin = make("AI банк", "Финтех: нейросети для банков и платежей")
    game = make("Геймджем")
    f = Filters(topics=["ai", "gamedev"])  # одна группа — «или»
    assert [f.matches(h, NOW) for h in (ai_health, ai_fin, game)] == [True, True, True]
    f = Filters(topics=["ai", "health"])  # разные группы — «и»
    assert [f.matches(h, NOW) for h in (ai_health, ai_fin, game)] == [True, False, False]


def test_item_shows_topics_and_brief():
    h = make("О! Хакатон", "«О! Хакатон» — онлайн-соревнование по разработке тревел-решений для студентов. "
             "Участникам предстоит создать AI-агента для путешествий. Призовой фонд 1 млн.",
             reg_deadline=NOW + timedelta(days=1))
    assert topics_line(h) == "Направление: AI / ML · Сфера: ритейл, туризм и сервисы · Студентам"
    text = format_item(h, False, NOW)
    assert "<i>Направление: AI / ML · Сфера: ритейл, туризм и сервисы · Студентам</i>" in text
    assert "онлайн-соревнование по разработке тревел-решений для студентов." in text
    assert "регистрация до 10 окт" in text.splitlines()[1]


def test_brief():
    assert brief(make("Хантатон", "Хантатон")) == ""  # описание повторяет название
    long = make("X", "Очень " * 60 + "длинно.")
    assert len(brief(long)) <= 180 and brief(long).endswith("…")
    first = "Команды за двое суток делают сервис для городского транспорта."
    assert brief(make("X", f"{first} Вторая фраза.")) == first
    assert brief(make("X", "«О! Хакатон» — соревнование по разработке тревел-решений. Ещё")).startswith("«О! Хакатон» —")


def test_topics_line_shows_strongest_first():
    desc = ("AI agents, AI tools, machine learning and LLM apps. " * 3 + "Also web, mobile, security, design, "
            "open source, fintech, health, education, climate, transport tracks.")
    h = make("Multi-track", desc * 2)
    line = topics_line(h)
    assert line.startswith("Направление: AI / ML, ")
    assert line.split(" · ")[0].count(",") == 2  # не больше трёх направлений
