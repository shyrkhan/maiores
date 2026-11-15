"""A made-up family for trying the program. None of these people are real."""
from model import Family, Person, Tree


def _person(key, given, surname, born, died=None, birth_surname="", sex=""):
    return Person(
        key,
        given=given,
        surname=surname,
        birth_surname=birth_surname,
        sex=sex,
        birth={"date": born, "place": ""},
        death={"date": died, "place": ""} if died else None,
        living="no" if died else "yes",
    )


def _family(key, partners, children=()):
    return Family(
        key,
        list(partners),
        "married",
        [{"person": child, "link": "birth"} for child in children],
    )


def sample_tree():
    people = [
        _person("ante", "Ante", "Šimić", "abt 1921", "1988", sex="M"),
        _person("ruzica", "Ružica", "Šimić", "1925", "2004", "Kovač", "F"),
        _person("luka", "Luka", "Šimić", "1949", "2017", sex="M"),
        _person("mara", "Mara", "Šimić", "1951-03-02", None, "Bilić", "F"),
        _person("josip", "Josip", "Šimić", "1953-07-19", sex="M"),
        _person("ana", "Ana", "Šimić", "1956-11-30", None, "Perić", "F"),
        _person("ivan", "Ivan", "Šimić", "1958-01-08", sex="M"),
        _person("katica", "Katica", "Šimić", "1960-05-21", None, "Đurić", "F"),
        _person("ivana", "Ivana", "Šimić", "1976-02-14", sex="F"),
        _person("marko", "Marko", "Šimić", "1979-09-03", sex="M"),
        _person("petar", "Petar", "Šimić", "1983", sex="M"),
        _person("tomo", "Tomo", "Šimić", "1985-06-12", sex="M"),
        _person("nikola", "Nikola", "Šimić", "1988-10-25", sex="M"),
        _person("stipe", "Stipe", "Bilić", "abt 1920", "1990", sex="M"),
        _person("jela", "Jela", "Bilić", "1924", "2009", "Čulić", "F"),
        _person("zvonko", "Zvonko", "Bilić", "1948-04-04", sex="M"),
    ]
    families = [
        _family("f-ante", ["ante", "ruzica"], ["luka", "josip", "ivan"]),
        _family("f-luka", ["luka", "mara"], ["ivana", "marko", "petar"]),
        _family("f-josip", ["josip", "ana"], ["tomo"]),
        _family("f-ivan", ["ivan", "katica"], ["nikola"]),
        _family("f-stipe", ["stipe", "jela"], ["zvonko", "mara"]),
    ]
    return Tree({p.id: p for p in people}, {f.id: f for f in families})
